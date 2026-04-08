import asyncio
import csv
import io
import json
import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Agency, CommissionRecord, SyncLog, UnmatchedRecord, User
from app.routers.deals import (
    GHL_BASE_URL,
    _extract_field_by_id,
    _fetch_all_contacts,
)

router = APIRouter(prefix="/api/commission-sync", tags=["commission_sync"])


def _safe_float(val: str) -> float:
    try:
        cleaned = str(val).replace("$", "").replace(",", "").replace("(", "-").replace(")", "").replace("%", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_date(val: str) -> str:
    val = (val or "").strip()
    if not val:
        return ""
    for fmt in ("%m-%d-%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val


def _months_between(start_str: str, end_str: str) -> float:
    if not start_str or not end_str:
        return 0.0
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        diff = (end - start).days
        return max(round(diff / 30.44, 1), 0.0)
    except ValueError:
        return 0.0


def _extract_statement_date(filename: str) -> str:
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", filename or "")
    if m:
        return _parse_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return ""


def _plan_status_for_problem(effective_date: str, statement_date: str) -> str:
    if not effective_date or not statement_date:
        return "Non Effectuated"
    try:
        eff = datetime.strptime(effective_date, "%Y-%m-%d")
        stmt = datetime.strptime(statement_date, "%Y-%m-%d")
        days = (stmt - eff).days
        return "Chargeback" if days > 31 else "Non Effectuated"
    except ValueError:
        return "Non Effectuated"


def _aggregate_wa_rows(rows: list[dict]) -> dict[str, dict]:
    policies: dict[str, dict] = {}

    for row in rows:
        policy_nbr = (row.get("Policy Nbr") or "").strip()
        if not policy_nbr:
            continue

        agent_nbr = (row.get("Agent Nbr") or "").strip()
        prem_paid = _safe_float(row.get("Prem Paid Amt") or "0")
        comm_prem = _safe_float(row.get("Comm Prem Amt") or "0")
        amount = _safe_float(row.get("Amount") or "0")

        if policy_nbr in policies:
            p = policies[policy_nbr]
            p["prem_paid_amt"] += prem_paid
            p["comm_prem_amt"] += comm_prem
            p["advance_amount"] += amount
            p["line_count"] += 1
        else:
            first_name = (row.get("First Name") or "").strip()
            last_name = (row.get("Last Name") or "").strip()
            policies[policy_nbr] = {
                "policy_number": policy_nbr,
                "insured_name": (row.get("Desc") or "").strip(),
                "agent_nbr": agent_nbr,
                "agent_first_name": first_name,
                "agent_last_name": last_name,
                "agent_name_full": f"{first_name} {last_name}".strip(),
                "trans_type": (row.get("Trans Type") or "").strip(),
                "plan_code": (row.get("Plan") or "").strip(),
                "prem_paid_amt": prem_paid,
                "comm_rate": _safe_float(row.get("Comm Rate") or "0"),
                "comm_prem_amt": comm_prem,
                "adv_per": _safe_float(row.get("Adv Per") or "0"),
                "advance_amount": amount,
                "effective_date": _parse_date(row.get("Effective Date") or ""),
                "paid_to_date": _parse_date(row.get("Paid To Date") or ""),
                "last_activity_date": _parse_date(row.get("Last Activity Date") or ""),
                "line_count": 1,
                "raw": dict(row),
            }

    for p in policies.values():
        p["monthly_premium"] = round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0

    return policies


POLICY_NUMBER_FIELD_ID = "ejFlhOjXzjMuK04iyaDv"


async def _ghl_api_call_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    max_retries: int = 3,
    **kwargs,
) -> httpx.Response | None:
    for attempt in range(max_retries):
        try:
            if method == "GET":
                response = await client.get(url, headers=headers, **kwargs)
            else:
                response = await client.put(url, headers=headers, **kwargs)
            if response.status_code == 429:
                wait = 2.0 * (attempt + 1)
                logger.warning("GHL rate limited, waiting %.1fs (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            return response
        except Exception as exc:
            logger.warning("GHL API call failed (attempt %d): %s", attempt + 1, exc)
            if attempt < max_retries - 1:
                await asyncio.sleep(1.0)
    return None


async def _search_ghl_contact_by_name(
    client: httpx.AsyncClient,
    api_key: str,
    location_id: str,
    search_name: str,
    policy_number: str,
    agent_field_id: str = "",
) -> dict | None:
    if not search_name or not policy_number:
        return None
    response = await _ghl_api_call_with_retry(
        client, "GET",
        f"{GHL_BASE_URL}/contacts/",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Version": "2021-07-28",
        },
        params={
            "locationId": location_id,
            "query": search_name,
            "limit": 20,
        },
    )
    if not response or response.status_code != 200:
        logger.warning("GHL search failed for %s / %s: status=%s", search_name, policy_number, response.status_code if response else "no response")
        return None
    contacts = response.json().get("contacts", [])
    for raw in contacts:
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            continue
        for cf in custom_fields:
            if cf.get("id") == POLICY_NUMBER_FIELD_ID:
                val = str(cf.get("value", "")).strip()
                if val == policy_number:
                    first_name = raw.get("firstName", "") or ""
                    last_name = raw.get("lastName", "") or ""
                    agent_name = _extract_field_by_id(custom_fields, agent_field_id) or "" if agent_field_id else ""
                    return {
                        "contact_id": raw.get("id", ""),
                        "contact_name": f"{first_name} {last_name}".strip(),
                        "agent_name": agent_name.strip() if isinstance(agent_name, str) else "",
                    }
    return None


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def _is_off_by_one(a: str, b: str) -> bool:
    if a == b:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if abs(len(a) - len(b)) == 1:
        longer, shorter = (a, b) if len(a) > len(b) else (b, a)
        diffs = 0
        j = 0
        for i in range(len(longer)):
            if j < len(shorter) and longer[i] == shorter[j]:
                j += 1
            else:
                diffs += 1
            if diffs > 1:
                return False
        return True
    return False


def _fuzzy_match(
    policy_nbr: str,
    insured_name: str,
    all_ghl_policies: dict[str, dict],
    name_index: dict[str, list[dict]],
) -> dict | None:
    # Only match by off-by-one policy number — never fall back to name-only
    # matching, which can catastrophically match unrelated people.
    if not policy_nbr:
        return None
    near_matches = [
        info for ghl_pn, info in all_ghl_policies.items()
        if _is_off_by_one(policy_nbr, ghl_pn)
    ]
    if len(near_matches) == 1:
        return near_matches[0]
    if len(near_matches) > 1 and insured_name:
        csv_parts = insured_name.strip().split()
        csv_last = _normalize_name(csv_parts[0]) if csv_parts else ""
        if csv_last:
            for c in near_matches:
                ghl_last = _normalize_name(c.get("last_name", ""))
                if ghl_last == csv_last:
                    return c
    return None


async def _build_policy_map(
    rows: list[dict],
    api_key: str,
    location_id: str,
    agent_field_id: str = "",
) -> tuple[dict[str, dict], dict[str, list[dict]], dict[str, dict]]:
    csv_policies: set[str] = set()
    for row in rows:
        policy_nbr = (row.get("Policy Nbr") or row.get("Policy Number") or "").strip()
        if policy_nbr:
            csv_policies.add(policy_nbr)

    logger.info("Building policy map for %d unique CSV policies via bulk fetch", len(csv_policies))

    all_contacts = await _fetch_all_contacts(api_key, location_id)
    logger.info("Fetched %d total GHL contacts", len(all_contacts))

    ghl_policy_map: dict[str, dict] = {}
    all_ghl_policies: dict[str, dict] = {}
    name_index: dict[str, list[dict]] = {}

    for raw in all_contacts:
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            continue
        first_name = raw.get("firstName", "") or ""
        last_name = raw.get("lastName", "") or ""
        agent_name = _extract_field_by_id(custom_fields, agent_field_id) or "" if agent_field_id else ""
        contact_info = {
            "contact_id": raw.get("id", ""),
            "contact_name": f"{first_name} {last_name}".strip(),
            "first_name": first_name,
            "last_name": last_name,
            "agent_name": agent_name.strip() if isinstance(agent_name, str) else "",
        }

        norm_last = _normalize_name(last_name)
        if norm_last:
            name_index.setdefault(norm_last, []).append(contact_info)

        contact_policy_raw = ""
        for cf in custom_fields:
            if cf.get("id") == POLICY_NUMBER_FIELD_ID:
                contact_policy_raw = str(cf.get("value", "")).strip()
                break
        if not contact_policy_raw:
            continue
        policy_parts = [p.strip() for p in contact_policy_raw.split("-") if len(p.strip()) >= 5]
        if not policy_parts:
            policy_parts = [contact_policy_raw]
        for p in policy_parts:
            all_ghl_policies[p] = contact_info
        matched_parts = [p for p in policy_parts if p in csv_policies]
        if not matched_parts:
            continue
        for p in matched_parts:
            ghl_policy_map[p] = contact_info

    logger.info("Matched %d / %d policies in GHL (%d total GHL policies for fuzzy)", len(ghl_policy_map), len(csv_policies), len(all_ghl_policies))
    return ghl_policy_map, name_index, all_ghl_policies


async def _update_ghl_contact_field(
    api_key: str, contact_id: str, field_id: str, value: str
) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.put(
                f"{GHL_BASE_URL}/contacts/{contact_id}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Version": "2021-07-28",
                    "Content-Type": "application/json",
                },
                json={"customFields": [{"id": field_id, "value": value}]},
            )
            return response.status_code == 200
    except Exception:
        return False


@router.post("/{agency_slug}/upload")
async def upload_commission_statement(
    agency_slug: str,
    file: UploadFile = File(...),
    statement_type: str = Form("WA"),
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [{k.strip(): v for k, v in row.items()} for row in reader]

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    statement_type = statement_type.upper()
    if statement_type not in ("WA", "WC", "MC"):
        raise HTTPException(status_code=400, detail="statement_type must be WA, WC, or MC")

    api_key = agency.ghl_api_key or ""
    location_id = agency.ghl_location_id or ""
    agent_field_id = agency.ghl_agent_field_id or ""

    ghl_policy_map: dict[str, dict] = {}
    name_index: dict[str, list[dict]] = {}
    all_ghl_policies: dict[str, dict] = {}
    if api_key and location_id:
        ghl_policy_map, name_index, all_ghl_policies = await _build_policy_map(
            rows, api_key, location_id, agent_field_id
        )

    sync_log = SyncLog(
        agency_id=agency.id,
        statement_type=statement_type,
        file_name=file.filename or "unknown.csv",
        total_rows=len(rows),
        matched_rows=0,
        unmatched_rows=0,
    )
    db.add(sync_log)
    db.flush()

    # Clean old unpaid records for this statement type (preserves payroll data)
    paid_policies = _cleanup_old_records(db, agency.id, {statement_type})

    try:
        if statement_type == "WA":
            return await _process_wa_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
        elif statement_type == "WC":
            return await _process_wc_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
        else:
            return await _process_mc_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
    except Exception as exc:
        logger.error("Upload %s failed: %s", statement_type, exc, exc_info=True)
        raise


def _detect_statement_type(filename: str) -> str | None:
    name = filename.upper()
    if "_WA_" in name or name.startswith("WA_") or name.endswith("_WA.CSV"):
        return "WA"
    if "_WC_" in name or name.startswith("WC_") or name.endswith("_WC.CSV"):
        return "WC"
    if "_MC_" in name or name.startswith("MC_") or name.endswith("_MC.CSV"):
        return "MC"
    return None


@router.post("/{agency_slug}/upload-multiple")
async def upload_multiple_statements(
    agency_slug: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    type_order = {"WA": 0, "WC": 1, "MC": 2}
    file_queue: list[tuple[str, UploadFile]] = []
    for f in files:
        st = _detect_statement_type(f.filename or "")
        if not st:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot detect statement type from filename '{f.filename}'. "
                       "Filename must contain _WA_, _WC_, or _MC_.",
            )
        file_queue.append((st, f))

    file_queue.sort(key=lambda x: type_order.get(x[0], 99))

    api_key = agency.ghl_api_key or ""
    location_id = agency.ghl_location_id or ""
    agent_field_id = agency.ghl_agent_field_id or ""

    all_rows_combined: list[dict] = []
    parsed_files: list[tuple[str, list[dict], str]] = []
    for st, f in file_queue:
        content = await f.read()
        text = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = [{k.strip(): v for k, v in row.items()} for row in reader]
        if not rows:
            continue
        parsed_files.append((st, rows, f.filename or "unknown.csv"))
        all_rows_combined.extend(rows)

    ghl_policy_map: dict[str, dict] = {}
    name_index: dict[str, list[dict]] = {}
    all_ghl_policies: dict[str, dict] = {}
    if api_key and location_id and all_rows_combined:
        ghl_policy_map, name_index, all_ghl_policies = await _build_policy_map(
            all_rows_combined, api_key, location_id, agent_field_id
        )

    # Clean old unpaid records once per statement type before processing.
    # This prevents the second file of the same type from wiping records
    # created by the first file, and preserves payroll-linked records.
    types_in_batch = {st for st, _rows, _fname in parsed_files}
    paid_policies = _cleanup_old_records(db, agency.id, types_in_batch)

    results: list[dict] = []
    for st, rows, fname in parsed_files:
        sync_log = SyncLog(
            agency_id=agency.id,
            statement_type=st,
            file_name=fname,
            total_rows=len(rows),
            matched_rows=0,
            unmatched_rows=0,
        )
        db.add(sync_log)
        db.flush()

        try:
            if st == "WA":
                result = await _process_wa_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
            elif st == "WC":
                result = await _process_wc_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
            else:
                result = await _process_mc_upload(rows, agency, sync_log, ghl_policy_map, name_index, all_ghl_policies, db, paid_policies)
            results.append(result)
        except Exception as exc:
            logger.error("Multi-upload %s (%s) failed: %s", st, fname, exc, exc_info=True)
            results.append({"statement_type": st, "file_name": fname, "error": str(exc)})

    return {"files_processed": len(results), "results": results}


def _cleanup_old_records(db: Session, agency_id: int, statement_types: set[str]) -> set[str]:
    """Delete old CommissionRecords that have NOT been marked as paid.

    Records where ``paid_to_agent`` is True are preserved so the payroll
    audit trail is never lost.  Only unpaid records for the given statement
    types are removed; the processors will re-create them from the new CSV.

    Returns the set of policy_numbers that are paid (so processors can skip them).
    """
    paid_policy_numbers: set[str] = set()
    for st in statement_types:
        paid_rows = (
            db.query(CommissionRecord.policy_number)
            .filter(
                CommissionRecord.agency_id == agency_id,
                CommissionRecord.statement_source == st,
                CommissionRecord.paid_to_agent == True,  # noqa: E712
            )
            .all()
        )
        paid_policy_numbers.update(r[0] for r in paid_rows)

        db.query(CommissionRecord).filter(
            CommissionRecord.agency_id == agency_id,
            CommissionRecord.statement_source == st,
            CommissionRecord.paid_to_agent == False,  # noqa: E712
        ).delete(synchronize_session=False)
    return paid_policy_numbers


async def _process_wa_upload(
    rows: list[dict],
    agency: Agency,
    sync_log: SyncLog,
    ghl_policy_map: dict[str, dict],
    name_index: dict[str, list[dict]],
    all_ghl_policies: dict[str, dict],
    db: Session,
    paid_policies: set[str] | None = None,
) -> dict:
    policies = _aggregate_wa_rows(rows)

    api_key = agency.ghl_api_key or ""
    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}

    matched = 0
    fuzzy_matched = 0
    unmatched_list: list[dict] = []
    chargebacks_found = 0

    pending_updates: list[tuple[str, list[dict]]] = []

    for policy_nbr, p in policies.items():
        ghl_match = ghl_policy_map.get(policy_nbr)
        if not ghl_match:
            ghl_match = _fuzzy_match(policy_nbr, p["insured_name"], all_ghl_policies, name_index)
            if ghl_match:
                fuzzy_matched += 1
                logger.info("WA fuzzy matched %s (%s) → %s", policy_nbr, p["insured_name"], ghl_match["contact_name"])
            else:
                unmatched_list.append({
                    "policy_number": policy_nbr,
                    "csv_agent": p["agent_name_full"],
                    "insured_name": p["insured_name"],
                })
                continue

        matched += 1
        contact_id = ghl_match["contact_id"]

        is_chargeback = p["advance_amount"] < 0
        if is_chargeback:
            chargebacks_found += 1

        status = "chargeback" if is_chargeback else "active"
        monthly_prem = p["monthly_premium"] or (round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0)

        field_mapping: dict[str, str] = {}

        field_mapping["advance_amount"] = str(round(abs(p["advance_amount"]), 2))
        field_mapping["commission_rate"] = str(p["comm_rate"])
        field_mapping["advance_percentage"] = str(p["adv_per"])
        field_mapping["commission_premium_amount"] = str(round(p["comm_prem_amt"], 2))
        field_mapping["paid_to_date"] = p["paid_to_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["last_activity_date"] = p["last_activity_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["agent_number"] = p["agent_nbr"]
        field_mapping["commission_status"] = status
        field_mapping["earned_commission"] = str(monthly_prem)
        field_mapping["chargeback_amount"] = str(abs(round(p["advance_amount"], 2))) if is_chargeback else "0"
        field_mapping["chargeback_date"] = (p["last_activity_date"] or "") if is_chargeback else ""
        field_mapping["months_active"] = "0"
        field_mapping["statement_source"] = "WA"
        field_mapping["plan_status"] = "Non Effectuated" if is_chargeback else "Active"

        fields_to_update: list[dict] = []
        for field_key, value in field_mapping.items():
            ghl_field_id = field_ids.get(field_key, "")
            if ghl_field_id:
                fields_to_update.append({"id": ghl_field_id, "value": str(value)})

        stmt_date = _extract_statement_date(sync_log.file_name)
        fields_to_update.append({"key": "wa_status", "field_value": status})
        fields_to_update.append({"key": "wa_chargeback_amount", "field_value": str(abs(round(p["advance_amount"], 2))) if is_chargeback else "0"})
        fields_to_update.append({"key": "wa_statement_date", "field_value": stmt_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        fields_to_update.append({"key": "wa_comm_prem_amt", "field_value": str(round(p["comm_prem_amt"], 2))})

        if fields_to_update and api_key and contact_id:
            pending_updates.append((contact_id, fields_to_update))
            if len(pending_updates) == 1:
                logger.info("WA first contact %s: %d fields", contact_id, len(fields_to_update))

        # Persist a CommissionRecord so the dashboard stats populate.
        # Skip if this policy was already paid — the paid record is preserved.
        if paid_policies and policy_nbr in paid_policies:
            continue
        record = CommissionRecord(
            agency_id=agency.id,
            sync_log_id=sync_log.id,
            policy_number=policy_nbr,
            ghl_contact_id=contact_id,
            agent_nbr=p["agent_nbr"],
            agent_first_name=p["agent_first_name"],
            agent_last_name=p["agent_last_name"],
            agent_name_full=p["agent_name_full"],
            insured_name=p["insured_name"],
            trans_type=p["trans_type"],
            plan_code=p["plan_code"],
            prem_paid_amt=p["prem_paid_amt"],
            monthly_premium=monthly_prem,
            comm_rate=p["comm_rate"],
            comm_prem_amt=p["comm_prem_amt"],
            adv_per=p["adv_per"],
            advance_amount=abs(p["advance_amount"]),
            effective_date=p["effective_date"],
            paid_to_date=p["paid_to_date"],
            last_activity_date=p["last_activity_date"],
            status=status,
            chargeback_amount=abs(p["advance_amount"]) if is_chargeback else 0.0,
            chargeback_date=(p["last_activity_date"] or "") if is_chargeback else "",
            months_active=0.0,
            earned_commission=monthly_prem,
            net_owed=(abs(p["advance_amount"]) - monthly_prem) if is_chargeback else 0.0,
            statement_source="WA",
        )
        db.add(record)

    ghl_synced = 0
    if pending_updates:
        logger.info("WA: sending %d contacts, avg %.1f fields each", len(pending_updates), sum(len(f) for _, f in pending_updates) / len(pending_updates))
        ghl_synced = await _run_concurrent_updates(api_key, pending_updates)

    sync_log.matched_rows = matched + fuzzy_matched
    sync_log.unmatched_rows = len(unmatched_list)
    db.commit()

    return {
        "sync_log_id": sync_log.id,
        "statement_type": "WA",
        "file_name": sync_log.file_name,
        "total_csv_rows": sync_log.total_rows,
        "unique_policies": len(policies),
        "matched_to_ghl": matched + fuzzy_matched,
        "fuzzy_matched": fuzzy_matched,
        "unmatched": len(unmatched_list),
        "chargebacks_found": chargebacks_found,
        "ghl_synced": ghl_synced,
        "unmatched_records": [
            {"policy_number": u["policy_number"], "csv_agent": u["csv_agent"], "insured_name": u["insured_name"]}
            for u in unmatched_list
        ],
    }


def _get_commission_field_ids(agency: Agency) -> dict[str, str]:
    raw = agency.ghl_commission_field_ids or "{}"
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


async def _update_ghl_contact_fields(
    client: httpx.AsyncClient,
    api_key: str,
    contact_id: str,
    fields: list[dict],
) -> bool:
    if not api_key or not contact_id or not fields:
        return False
    response = await _ghl_api_call_with_retry(
        client, "PUT",
        f"{GHL_BASE_URL}/contacts/{contact_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Version": "2021-07-28",
            "Content-Type": "application/json",
        },
        json={"customFields": fields},
    )
    if not response:
        logger.warning("GHL sync failed for contact %s: no response after retries", contact_id)
        return False
    if response.status_code == 200:
        return True
    logger.warning(
        "GHL sync failed for contact %s: %s %s",
        contact_id, response.status_code, response.text[:200],
    )
    return False


async def _run_concurrent_updates(
    api_key: str,
    pending_updates: list[tuple[str, list[dict]]],
) -> int:
    sem = asyncio.Semaphore(10)
    synced = 0
    failed: list[tuple[str, list[dict]]] = []

    async def _do_one(client: httpx.AsyncClient, contact_id: str, fields: list[dict]) -> tuple[str, list[dict], bool]:
        async with sem:
            ok = await _update_ghl_contact_fields(client, api_key, contact_id, fields)
            return contact_id, fields, ok

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [_do_one(client, cid, flds) for cid, flds in pending_updates]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("GHL update task failed: %s", r)
            else:
                cid, flds, ok = r
                if ok:
                    synced += 1
                else:
                    failed.append((cid, flds))

    if failed:
        logger.info("Retrying %d failed GHL updates", len(failed))
        await asyncio.sleep(2.0)
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [_do_one(client, cid, flds) for cid, flds in failed]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("GHL retry task failed: %s", r)
                else:
                    _, _, ok = r
                    if ok:
                        synced += 1

    logger.info("GHL concurrent updates: %d/%d synced", synced, len(pending_updates))
    return synced


async def _background_ghl_sync(
    api_key: str,
    pending_updates: list[tuple[str, list[dict]]],
    label: str = "",
) -> None:
    try:
        synced = await _run_concurrent_updates(api_key, pending_updates)
        logger.info("Background GHL sync [%s]: %d/%d contacts synced", label, synced, len(pending_updates))
    except Exception as exc:
        logger.error("Background GHL sync [%s] FAILED: %s", label, exc)


GHL_COMMISSION_FIELD_IDS: dict[str, str] = {
    "advance_amount": "HuVWXrR9a297azTk3WjQ",
    "commission_rate": "dQFMq98Nc9aLW7N9W1by",
    "advance_percentage": "sS5iEg2eUUchRTwFjbEO",
    "commission_premium_amount": "y45y1NLqcdTRhUro5S2y",
    "remaining_balance": "ZvSIEN8jQFFMP9mZQ7n5",
    "transaction_type": "6aoxH9aaNJ6LEbjn7n4d",
    "transaction_code": "tO7PkrJKdLvXAoPrKVRr",
    "transaction_reason": "WGuNk8GCNZ7qFHAgy430",
    "code_reason": "szAjQozaccuZx6IqsCTS",
    "wc_transaction_type": "6aoxH9aaNJ6LEbjn7n4d",
    "wc_transaction_code": "tO7PkrJKdLvXAoPrKVRr",
    "chargeback_amount": "flyi1jdkoFI0DyoAAMc6",
    "chargeback_date": "EKzoFKUzCkbuvgD4GJQq",
    "paid_to_date": "URW4Th0bbL7boLjfo41v",
    "last_activity_date": "dQBax4TvDlnHH7vYKetF",
    "agent_number": "OPovg0T4ntVzMX9ao5aS",
    "issue_state": "AJK8w0L5NEOE6NyYwvkE",
    "policy_form": "lNYEnWsOlLVNcmai9Ept",
    "commission_status": "noRA9xjRD2CzJ74sRjzD",
    "months_active": "3LYcp1XOEe5i5K3nsnvx",
    "earned_commission": "QjBNVLCWIclnOv08gtHY",
    "net_owed": "TSDVwpxFz6m6MhU81FYD",
    "paid_to_agent_date": "r2ZKh3um2SlNgqNdMC0s",
    "mc_comm_amt": "vJFELG1ERvFz1fMSC4A5",
    "mc_comm_amt_due": "P8FZaYj2CoETH0svUuY9",
    "statement_source": "hAqoFTDtVFF9FguS6OUe",
    "plan_status": "UjccY8SnCtNooAFSA1FK",
}



def _aggregate_wc_rows(rows: list[dict]) -> dict[str, dict]:
    policies: dict[str, dict] = {}

    non_normal_trans = {"C", "F", "I", "O", "N", "S", "R"}

    for row in rows:
        policy_nbr = (row.get("Policy Nbr") or row.get("Policy Number") or "").strip()
        if not policy_nbr or len(policy_nbr) < 5:
            continue

        comm_amt = _safe_float(row.get("Comm Amt") or row.get("Amount") or "0")
        comm_prem = _safe_float(row.get("Comm Prem Amt") or "0")
        prem_paid = _safe_float(row.get("Prem Paid Amt") or "0")
        trans_type = (row.get("Trans Type") or "").strip()
        code = (row.get("Code") or "").strip()

        if policy_nbr in policies:
            p = policies[policy_nbr]
            p["comm_amt"] += comm_amt
            p["comm_prem_amt"] += comm_prem
            p["prem_paid_amt"] += prem_paid
            p["line_count"] += 1
            if comm_prem < 0 or comm_amt < 0:
                p["has_negative"] = True
            if trans_type in non_normal_trans:
                p["trans_type"] = trans_type
            if code and not p.get("code"):
                p["code"] = code
        else:
            first_name = (row.get("First Name") or "").strip()
            last_name = (row.get("Last Name") or "").strip()
            policies[policy_nbr] = {
                "policy_number": policy_nbr,
                "insured_name": (row.get("Desc") or "").strip(),
                "agent_nbr": (row.get("Agent Nbr") or "").strip(),
                "agent_first_name": first_name,
                "agent_last_name": last_name,
                "agent_name_full": f"{first_name} {last_name}".strip(),
                "comm_rate": _safe_float(row.get("Comm Rate") or "0"),
                "comm_prem_amt": comm_prem,
                "prem_paid_amt": prem_paid,
                "comm_amt": comm_amt,
                "effective_date": _parse_date(row.get("Effective Date") or ""),
                "paid_to_date": _parse_date(row.get("Paid To Date") or ""),
                "last_activity_date": _parse_date(
                    row.get("Last Activity Date") or row.get("Effective Date") or ""
                ),
                "has_negative": comm_prem < 0 or comm_amt < 0,
                "trans_type": trans_type,
                "code": code,
                "line_count": 1,
            }

    return policies


async def _process_wc_upload(
    rows: list[dict],
    agency: Agency,
    sync_log: SyncLog,
    ghl_policy_map: dict[str, dict],
    name_index: dict[str, list[dict]],
    all_ghl_policies: dict[str, dict],
    db: Session,
    paid_policies: set[str] | None = None,
) -> dict:
    policies = _aggregate_wc_rows(rows)

    api_key = agency.ghl_api_key or ""
    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}

    matched = 0
    fuzzy_matched = 0
    unmatched_list: list[dict] = []
    chargebacks_found = 0

    pending_updates: list[tuple[str, list[dict]]] = []

    for policy_nbr, p in policies.items():
        ghl_match = ghl_policy_map.get(policy_nbr)
        if not ghl_match:
            ghl_match = _fuzzy_match(policy_nbr, p["insured_name"], all_ghl_policies, name_index)
            if ghl_match:
                fuzzy_matched += 1
                logger.info("WC fuzzy matched %s (%s) → %s", policy_nbr, p["insured_name"], ghl_match["contact_name"])
            else:
                unmatched_list.append({
                    "policy_number": policy_nbr,
                    "csv_agent": p["agent_name_full"],
                    "insured_name": p["insured_name"],
                })
                continue

        matched += 1
        contact_id = ghl_match["contact_id"]

        wc_trans = p.get("trans_type", "")
        if wc_trans in REINSTATEMENT_TRANS_TYPES:
            is_chargeback = False
        else:
            is_chargeback = p.get("has_negative", False) or wc_trans in CANCEL_TRANS_TYPES or wc_trans in PAYMENT_ISSUE_TRANS_TYPES
        if is_chargeback:
            chargebacks_found += 1

        status = "chargeback" if is_chargeback else "active"
        earned_commission = round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0

        stmt_date = _extract_statement_date(sync_log.file_name)
        if is_chargeback:
            plan_status = _plan_status_for_problem(p.get("effective_date", ""), stmt_date)
        else:
            plan_status = "Active"

        field_mapping: dict[str, str] = {}

        field_mapping["commission_rate"] = str(p["comm_rate"])
        field_mapping["commission_premium_amount"] = str(round(p["comm_prem_amt"], 2))
        field_mapping["chargeback_amount"] = str(abs(round(p["comm_amt"], 2))) if is_chargeback else "0"
        field_mapping["chargeback_date"] = (p.get("last_activity_date") or "") if is_chargeback else ""
        field_mapping["paid_to_date"] = p.get("paid_to_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["last_activity_date"] = p.get("last_activity_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["agent_number"] = p["agent_nbr"]
        field_mapping["commission_status"] = status
        field_mapping["earned_commission"] = str(earned_commission)
        field_mapping["months_active"] = "0"
        field_mapping["statement_source"] = "WC"
        field_mapping["plan_status"] = plan_status

        raw_trans = p.get("trans_type", "")
        raw_code = p.get("code", "")
        field_mapping["wc_transaction_type"] = TRANS_TYPE_LABELS.get(raw_trans, raw_trans)
        field_mapping["wc_transaction_code"] = CODE_LABELS.get(raw_code, raw_code) if raw_code else ""

        fields_to_update: list[dict] = []
        for field_key, value in field_mapping.items():
            ghl_field_id = field_ids.get(field_key, "")
            if ghl_field_id:
                fields_to_update.append({"id": ghl_field_id, "value": str(value)})

        fields_to_update.append({"key": "wc_status", "field_value": status})
        fields_to_update.append({"key": "wc_chargeback_amount", "field_value": str(abs(round(p["comm_amt"], 2))) if is_chargeback else "0"})
        fields_to_update.append({"key": "wc_statement_date", "field_value": stmt_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        fields_to_update.append({"key": "wc_comm_prem_amt", "field_value": str(round(p["comm_prem_amt"], 2))})

        if fields_to_update and api_key and contact_id:
            pending_updates.append((contact_id, fields_to_update))

        # Persist a CommissionRecord so the dashboard stats populate.
        # Skip if this policy was already paid — the paid record is preserved.
        if paid_policies and policy_nbr in paid_policies:
            continue
        chargeback_amt = abs(round(p["comm_amt"], 2)) if is_chargeback else 0.0
        record = CommissionRecord(
            agency_id=agency.id,
            sync_log_id=sync_log.id,
            policy_number=policy_nbr,
            ghl_contact_id=contact_id,
            agent_nbr=p["agent_nbr"],
            agent_first_name=p["agent_first_name"],
            agent_last_name=p["agent_last_name"],
            agent_name_full=p["agent_name_full"],
            insured_name=p["insured_name"],
            trans_type=p.get("trans_type", ""),
            plan_code=p.get("plan_code", ""),
            prem_paid_amt=p["prem_paid_amt"],
            monthly_premium=round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0,
            comm_rate=p["comm_rate"],
            comm_prem_amt=p["comm_prem_amt"],
            adv_per=0.0,
            advance_amount=0.0,
            effective_date=p.get("effective_date", ""),
            paid_to_date=p.get("paid_to_date", ""),
            last_activity_date=p.get("last_activity_date", ""),
            status=status,
            chargeback_amount=chargeback_amt,
            chargeback_date=(p.get("last_activity_date") or "") if is_chargeback else "",
            months_active=0.0,
            earned_commission=earned_commission,
            net_owed=(chargeback_amt - earned_commission) if is_chargeback else 0.0,
            statement_source="WC",
        )
        db.add(record)

    ghl_synced = 0
    if pending_updates:
        ghl_synced = await _run_concurrent_updates(api_key, pending_updates)

    sync_log.matched_rows = matched + fuzzy_matched
    sync_log.unmatched_rows = len(unmatched_list)
    db.commit()

    return {
        "sync_log_id": sync_log.id,
        "statement_type": "WC",
        "file_name": sync_log.file_name,
        "total_csv_rows": sync_log.total_rows,
        "unique_policies": len(policies),
        "chargebacks_found": chargebacks_found,
        "matched_to_ghl": matched + fuzzy_matched,
        "fuzzy_matched": fuzzy_matched,
        "unmatched": len(unmatched_list),
        "ghl_synced": ghl_synced,
        "unmatched_records": [
            {"policy_number": u["policy_number"], "csv_agent": u["csv_agent"], "insured_name": u["insured_name"]}
            for u in unmatched_list
        ],
    }


CANCEL_TRANS_TYPES = {"C", "F", "I"}
PAYMENT_ISSUE_TRANS_TYPES = {"O", "N", "S", "R"}
REINSTATEMENT_TRANS_TYPES = {"2"}
SKIP_TRANS_TYPES = {"9", "8"}

TRANS_TYPE_LABELS = {
    "1": "Regular Payment",
    "2": "Reinstatement",
    "3": "Bal. on Del.",
    "5": "A.P.L.",
    "6": "Waiver",
    "7": "Reversion",
    "8": "Manual Adjustments",
    "9": "Manual Adjustments",
    "C": "Account Closed",
    "F": "Flat Cancel",
    "I": "Cancel-Reissue",
    "N": "NSF",
    "O": "Other Bank Problem",
    "R": "Refund",
    "S": "Stop Pay",
}

CODE_LABELS = {
    "A": "Advance Recovery",
    "D": "1st Yr Death",
    "E": "Credit-Nets",
    "H": "Rate Correction",
    "J": "Registrate Fee",
    "L": "For Lead Bal",
    "M": "Manual Entry",
    "P": "Appeared on Wkly",
    "Q": "For Adv Bal",
    "R": "Retained",
    "Y": "Over/Short",
    "*": "Affected by Vesting",
}


def _aggregate_mc_rows(rows: list[dict]) -> dict[str, dict]:
    policies: dict[str, dict] = {}

    for row in rows:
        policy_nbr = (row.get("Policy Nbr") or "").strip()
        trans_type = (row.get("Trans Type") or "").strip()

        if trans_type in SKIP_TRANS_TYPES:
            continue

        if not policy_nbr or len(policy_nbr) < 5:
            continue

        comm_amt = _safe_float(row.get("Comm Amt") or row.get("Comm Amt ") or "0")
        retained = _safe_float(row.get("Retained or Recovery") or "0")
        comm_due = _safe_float(row.get("Comm Amt Due") or "0")
        comm_prem = _safe_float(row.get("Comm Prem Amt") or "0")
        prem_paid = _safe_float(row.get("Prem Paid Amt") or "0")
        comm_rate = _safe_float(row.get("Comm Rate") or "0")

        code = (row.get("Code") or "").strip()

        if policy_nbr in policies:
            p = policies[policy_nbr]
            p["mc_comm_amt"] += comm_amt
            p["mc_retained_recovery"] += retained
            p["mc_comm_amt_due"] += comm_due
            p["comm_prem_amt"] += comm_prem
            p["prem_paid_amt"] += prem_paid
            p["line_count"] += 1
            if comm_prem < 0:
                p["has_negative_comm_prem"] = True
            if code and not p["mc_code"]:
                p["mc_code"] = code
            if trans_type and trans_type != "1" and p["mc_trans_type"] in ("", "1"):
                p["mc_trans_type"] = trans_type
        else:
            first_name = (row.get("First Name") or "").strip()
            last_name = (row.get("Last Name") or "").strip()
            policies[policy_nbr] = {
                "policy_number": policy_nbr,
                "insured_name": (row.get("Desc") or "").strip(),
                "agent_nbr": (row.get("Agent Nbr") or "").strip(),
                "agent_first_name": first_name,
                "agent_last_name": last_name,
                "agent_name_full": f"{first_name} {last_name}".strip(),
                "issue_state": (row.get("Issue State") or "").strip(),
                "policy_form": (row.get("Policy Form") or "").strip(),
                "effective_date": _parse_date(row.get("Effective Date") or ""),
                "paid_to_date": _parse_date(row.get("Paid To Date") or ""),
                "comm_rate": comm_rate,
                "comm_prem_amt": comm_prem,
                "prem_paid_amt": prem_paid,
                "mc_comm_amt": comm_amt,
                "mc_retained_recovery": retained,
                "mc_comm_amt_due": comm_due,
                "mc_code": code,
                "mc_trans_type": trans_type,
                "has_negative_comm_prem": comm_prem < 0,
                "line_count": 1,
                "raw": dict(row),
            }

    return policies


async def _process_mc_upload(
    rows: list[dict],
    agency: Agency,
    sync_log: SyncLog,
    ghl_policy_map: dict[str, dict],
    name_index: dict[str, list[dict]],
    all_ghl_policies: dict[str, dict],
    db: Session,
    paid_policies: set[str] | None = None,
) -> dict:
    policies = _aggregate_mc_rows(rows)

    api_key = agency.ghl_api_key or ""
    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}

    matched = 0
    fuzzy_matched = 0
    unmatched_list: list[dict] = []
    chargebacks_found = 0

    pending_updates: list[tuple[str, list[dict]]] = []

    for policy_nbr, p in policies.items():
        ghl_match = ghl_policy_map.get(policy_nbr)
        if not ghl_match:
            ghl_match = _fuzzy_match(policy_nbr, p["insured_name"], all_ghl_policies, name_index)
            if ghl_match:
                fuzzy_matched += 1
                logger.info("MC fuzzy matched %s (%s) → %s", policy_nbr, p["insured_name"], ghl_match["contact_name"])
            else:
                unmatched_list.append({
                    "policy_number": policy_nbr,
                    "csv_agent": p["agent_name_full"],
                    "insured_name": p["insured_name"],
                })
                continue

        matched += 1
        contact_id = ghl_match["contact_id"]

        mc_trans = p["mc_trans_type"]
        if mc_trans in REINSTATEMENT_TRANS_TYPES:
            is_chargeback = False
        else:
            is_chargeback = mc_trans in CANCEL_TRANS_TYPES or mc_trans in PAYMENT_ISSUE_TRANS_TYPES or p.get("has_negative_comm_prem", False)

        if is_chargeback:
            chargebacks_found += 1

        status = "chargeback" if is_chargeback else "active"
        earned_commission = round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0

        stmt_date = _extract_statement_date(sync_log.file_name)
        if is_chargeback:
            plan_status = _plan_status_for_problem(p.get("effective_date", ""), stmt_date)
        else:
            plan_status = "Active"

        field_mapping: dict[str, str] = {}

        field_mapping["commission_rate"] = str(p["comm_rate"])
        field_mapping["commission_premium_amount"] = str(round(p["comm_prem_amt"], 2))
        raw_mc_trans = mc_trans
        raw_mc_code = p["mc_code"]
        field_mapping["transaction_type"] = raw_mc_trans
        field_mapping["transaction_code"] = raw_mc_code
        field_mapping["transaction_reason"] = TRANS_TYPE_LABELS.get(raw_mc_trans, raw_mc_trans) if raw_mc_trans else ""
        field_mapping["code_reason"] = CODE_LABELS.get(raw_mc_code, raw_mc_code) if raw_mc_code else ""
        field_mapping["chargeback_amount"] = str(abs(round(p["mc_comm_amt"], 2))) if is_chargeback else "0"
        field_mapping["chargeback_date"] = (p["paid_to_date"] or "") if is_chargeback else ""
        field_mapping["paid_to_date"] = p["paid_to_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["last_activity_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        field_mapping["agent_number"] = p["agent_nbr"]
        field_mapping["issue_state"] = p["issue_state"]
        field_mapping["policy_form"] = p["policy_form"]
        field_mapping["commission_status"] = status
        field_mapping["earned_commission"] = str(earned_commission)
        field_mapping["mc_comm_amt"] = str(round(p["mc_comm_amt"], 2))
        field_mapping["mc_comm_amt_due"] = str(round(p["mc_comm_amt_due"], 2))
        field_mapping["months_active"] = "0"
        field_mapping["statement_source"] = "MC"
        field_mapping["plan_status"] = plan_status

        fields_to_update: list[dict] = []
        for field_key, value in field_mapping.items():
            ghl_field_id = field_ids.get(field_key, "")
            if ghl_field_id:
                fields_to_update.append({"id": ghl_field_id, "value": str(value)})

        mc_stmt_date = _extract_statement_date(sync_log.file_name)
        fields_to_update.append({"key": "mc_status", "field_value": status})
        fields_to_update.append({"key": "mc_chargeback_amount", "field_value": str(abs(round(p["mc_comm_amt"], 2))) if is_chargeback else "0"})
        fields_to_update.append({"key": "mc_statement_date", "field_value": mc_stmt_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        fields_to_update.append({"key": "mc_comm_prem_amt", "field_value": str(round(p["comm_prem_amt"], 2))})

        if fields_to_update and api_key and contact_id:
            pending_updates.append((contact_id, fields_to_update))

        # Persist a CommissionRecord so the dashboard stats populate.
        # Skip if this policy was already paid — the paid record is preserved.
        if paid_policies and policy_nbr in paid_policies:
            continue
        mc_chargeback_amt = abs(round(p["mc_comm_amt"], 2)) if is_chargeback else 0.0
        record = CommissionRecord(
            agency_id=agency.id,
            sync_log_id=sync_log.id,
            policy_number=policy_nbr,
            ghl_contact_id=contact_id,
            agent_nbr=p["agent_nbr"],
            agent_first_name=p["agent_first_name"],
            agent_last_name=p["agent_last_name"],
            agent_name_full=p["agent_name_full"],
            insured_name=p["insured_name"],
            trans_type=p["mc_trans_type"],
            plan_code="",
            prem_paid_amt=p["prem_paid_amt"],
            monthly_premium=round(p["prem_paid_amt"] / 12, 2) if p["prem_paid_amt"] else 0.0,
            comm_rate=p["comm_rate"],
            comm_prem_amt=p["comm_prem_amt"],
            adv_per=0.0,
            advance_amount=0.0,
            effective_date=p.get("effective_date", ""),
            paid_to_date=p["paid_to_date"],
            last_activity_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            status=status,
            chargeback_amount=mc_chargeback_amt,
            chargeback_date=(p["paid_to_date"] or "") if is_chargeback else "",
            months_active=0.0,
            earned_commission=earned_commission,
            net_owed=(mc_chargeback_amt - earned_commission) if is_chargeback else 0.0,
            mc_comm_amt=round(p["mc_comm_amt"], 2),
            mc_comm_amt_due=round(p["mc_comm_amt_due"], 2),
            mc_code=p["mc_code"],
            mc_trans_type=p["mc_trans_type"],
            statement_source="MC",
            issue_state=p["issue_state"],
            policy_form=p["policy_form"],
        )
        db.add(record)

    ghl_synced = 0
    if pending_updates:
        ghl_synced = await _run_concurrent_updates(api_key, pending_updates)

    sync_log.matched_rows = matched + fuzzy_matched
    sync_log.unmatched_rows = len(unmatched_list)
    db.commit()

    return {
        "sync_log_id": sync_log.id,
        "statement_type": "MC",
        "file_name": sync_log.file_name,
        "total_csv_rows": sync_log.total_rows,
        "unique_policies": len(policies),
        "matched_to_ghl": matched + fuzzy_matched,
        "fuzzy_matched": fuzzy_matched,
        "unmatched": len(unmatched_list),
        "chargebacks_found": chargebacks_found,
        "ghl_synced": ghl_synced,
        "unmatched_records": [
            {"policy_number": u["policy_number"], "csv_agent": u["csv_agent"], "insured_name": u["insured_name"]}
            for u in unmatched_list
        ],
    }


@router.get("/{agency_slug}/stats")
async def get_commission_stats(
    agency_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role not in ("super_admin",) and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    records = (
        db.query(CommissionRecord)
        .filter(CommissionRecord.agency_id == agency.id)
        .all()
    )

    total_advanced = 0.0
    total_advance_count = 0
    total_chargeback_count = 0
    total_chargeback_amount = 0.0
    total_earned_on_chargebacks = 0.0
    total_net_owed = 0.0
    total_paid_to_agents = 0
    total_comm_prem = 0.0

    for r in records:
        # For WA records, the primary commission metric is advance_amount.
        # For WC/MC records, advance_amount is always 0; use comm_prem_amt instead.
        commission_value = r.advance_amount if r.advance_amount > 0 else abs(r.comm_prem_amt)
        if commission_value > 0 and r.status != "chargeback":
            total_advanced += commission_value
            total_advance_count += 1
            total_comm_prem += r.comm_prem_amt

        if r.status == "chargeback":
            total_chargeback_count += 1
            # Use chargeback_amount if set; fall back to abs(comm_prem_amt)
            cb_amt = r.chargeback_amount if r.chargeback_amount > 0 else abs(r.comm_prem_amt)
            total_chargeback_amount += cb_amt
            total_earned_on_chargebacks += r.earned_commission
            total_net_owed += max(cb_amt - r.earned_commission, 0.0)

        if r.paid_to_agent:
            total_paid_to_agents += 1

    chargeback_rate = (
        round(total_chargeback_count / total_advance_count * 100, 1)
        if total_advance_count > 0 else 0.0
    )

    net_commission = round(total_advanced - total_chargeback_amount + total_earned_on_chargebacks, 2)

    return {
        "total_advanced": round(total_advanced, 2),
        "total_advance_count": total_advance_count,
        "total_chargeback_count": total_chargeback_count,
        "total_chargeback_amount": round(total_chargeback_amount, 2),
        "total_earned_on_chargebacks": round(total_earned_on_chargebacks, 2),
        "total_net_owed": round(total_net_owed, 2),
        "net_commission": net_commission,
        "chargeback_rate": chargeback_rate,
        "total_paid_to_agents": total_paid_to_agents,
        "total_comm_prem": round(total_comm_prem, 2),
        "total_records": len(records),
    }


@router.get("/{agency_slug}/records")
async def get_commission_records(
    agency_slug: str,
    status: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role not in ("super_admin",) and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    query = db.query(CommissionRecord).filter(CommissionRecord.agency_id == agency.id)
    if status:
        query = query.filter(CommissionRecord.status == status)

    records = query.order_by(CommissionRecord.last_activity_date.desc()).limit(500).all()

    return {
        "records": [
            {
                "id": r.id,
                "policy_number": r.policy_number,
                "agent_name": r.agent_name_full,
                "insured_name": r.insured_name,
                "plan_code": r.plan_code,
                "prem_paid_amt": r.prem_paid_amt,
                "monthly_premium": r.monthly_premium,
                "comm_rate": r.comm_rate,
                "comm_prem_amt": r.comm_prem_amt,
                "adv_per": r.adv_per,
                "advance_amount": r.advance_amount,
                "effective_date": r.effective_date,
                "last_activity_date": r.last_activity_date,
                "status": r.status,
                "chargeback_amount": r.chargeback_amount,
                "chargeback_date": r.chargeback_date,
                "months_active": r.months_active,
                "earned_commission": r.earned_commission,
                "net_owed": r.net_owed,
                "paid_to_agent": r.paid_to_agent,
                "mc_comm_amt": r.mc_comm_amt,
                "mc_retained_recovery": r.mc_retained_recovery,
                "mc_comm_amt_due": r.mc_comm_amt_due,
                "mc_code": r.mc_code,
                "mc_trans_type": r.mc_trans_type,
                "statement_source": r.statement_source,
                "issue_state": r.issue_state,
                "policy_form": r.policy_form,
                "remaining_balance": r.remaining_balance,
            }
            for r in records
        ],
        "total": len(records),
    }


@router.get("/{agency_slug}/logs")
async def get_sync_logs(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    logs = (
        db.query(SyncLog)
        .filter(SyncLog.agency_id == agency.id)
        .order_by(SyncLog.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "logs": [
            {
                "id": log.id,
                "statement_type": log.statement_type,
                "file_name": log.file_name,
                "total_rows": log.total_rows,
                "matched_rows": log.matched_rows,
                "unmatched_rows": log.unmatched_rows,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ]
    }


@router.get("/{agency_slug}/unmatched/{sync_log_id}")
async def get_unmatched_records(
    agency_slug: str,
    sync_log_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    sync_log = db.query(SyncLog).filter(SyncLog.id == sync_log_id).first()
    if not sync_log:
        raise HTTPException(status_code=404, detail="Sync log not found")
    if sync_log.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    records = [
        {
            "id": r.id,
            "policy_number": r.policy_number,
            "raw_data": json.loads(r.raw_data) if r.raw_data else {},
            "resolved": r.resolved,
        }
        for r in sync_log.unmatched_records
    ]
    return {"unmatched_records": records, "total": len(records)}


# ── Commission Audit ──────────────────────────────────────────────


POLICY_NUMBER_FIELD_ID_AUDIT = "MElxhb8gTHUIQocxEEkQ"


@router.get("/{agency_slug}/audit")
async def commission_audit(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Scan all GHL contacts and return those with commission data set."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        raise HTTPException(status_code=400, detail="GHL API key / location not configured")

    # Merge default + agency-specific commission field IDs
    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}
    field_id_set = set(field_ids.values())

    all_contacts = await _fetch_all_contacts(api_key, location_id)

    flagged: list[dict] = []
    for raw in all_contacts:
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            continue

        # Check if any commission field has a non-empty value
        commission_vals: dict[str, str] = {}
        for cf in custom_fields:
            fid = cf.get("id", "")
            val = str(cf.get("value", "")).strip()
            if fid in field_id_set and val and val not in ("0", "0.0", "0.00"):
                # Reverse-lookup the field name
                name = next((k for k, v in field_ids.items() if v == fid), fid)
                commission_vals[name] = val

        if not commission_vals:
            continue

        # Extract policy number
        policy_number = ""
        for cf in custom_fields:
            if cf.get("id") == POLICY_NUMBER_FIELD_ID_AUDIT:
                policy_number = str(cf.get("value", "")).strip()
                break

        first_name = raw.get("firstName", "") or ""
        last_name = raw.get("lastName", "") or ""
        flagged.append({
            "contact_id": raw.get("id", ""),
            "name": f"{first_name} {last_name}".strip(),
            "policy_number": policy_number,
            "commission_fields": commission_vals,
        })

    return {
        "total_contacts": len(all_contacts),
        "contacts_with_commission": len(flagged),
        "flagged": flagged,
    }


@router.post("/{agency_slug}/audit/clear")
async def clear_commission_data(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Clear all commission custom fields from ALL GHL contacts."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        raise HTTPException(status_code=400, detail="GHL API key / location not configured")

    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}
    field_id_set = set(field_ids.values())

    all_contacts = await _fetch_all_contacts(api_key, location_id)

    # Find contacts with commission data
    to_clear: list[tuple[str, str]] = []
    for raw in all_contacts:
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            continue
        has_data = False
        for cf in custom_fields:
            fid = cf.get("id", "")
            val = str(cf.get("value", "")).strip()
            if fid in field_id_set and val and val not in ("0", "0.0", "0.00"):
                has_data = True
                break
        if has_data:
            first = raw.get("firstName", "") or ""
            last = raw.get("lastName", "") or ""
            to_clear.append((raw.get("id", ""), f"{first} {last}".strip()))

    if not to_clear:
        return {"cleared": 0, "total_scanned": len(all_contacts), "message": "No contacts with commission data found"}

    # Build clear updates
    clear_fields = [{"id": fid, "field_value": ""} for fid in field_id_set]
    pending_updates = [(cid, clear_fields) for cid, _ in to_clear]

    synced = await _run_concurrent_updates(api_key, pending_updates)
    return {
        "cleared": synced,
        "attempted": len(to_clear),
        "total_scanned": len(all_contacts),
        "message": f"Cleared commission data from {synced} of {len(to_clear)} contacts",
    }


@router.post("/{agency_slug}/audit/clear-selected")
async def clear_selected_commission_data(
    agency_slug: str,
    contact_ids: list[str] = Body(..., embed=True),
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Clear commission fields from specific contacts by ID."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    api_key = agency.ghl_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="GHL API key not configured")

    if not contact_ids:
        raise HTTPException(status_code=400, detail="No contact IDs provided")

    agency_field_ids = _get_commission_field_ids(agency)
    field_ids = {**GHL_COMMISSION_FIELD_IDS, **agency_field_ids}
    clear_fields = [{"id": fid, "field_value": ""} for fid in field_ids.values()]
    pending_updates = [(cid, clear_fields) for cid in contact_ids]

    synced = await _run_concurrent_updates(api_key, pending_updates)
    return {
        "cleared": synced,
        "attempted": len(contact_ids),
        "message": f"Cleared commission data from {synced} of {len(contact_ids)} contacts",
    }
