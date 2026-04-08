import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Agency, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deals", tags=["deals"])

GHL_BASE_URL = "https://services.leadconnectorhq.com"
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))

GHL_AGENT_FIELD_ID_DEFAULT = os.getenv("GHL_AGENT_FIELD_ID", "")
GHL_PREMIUM_FIELD_ID_DEFAULT = os.getenv("GHL_PREMIUM_FIELD_ID", "")

# GHL custom field IDs written by the commission sync — these live on
# the GHL contacts themselves and are the source of truth for dashboard
# classification (NOT the commission_records DB table).
COMMISSION_FIELD_IDS = {
    "advance_amount": "HuVWXrR9a297azTk3WjQ",
    "chargeback_amount": "flyi1jdkoFI0DyoAAMc6",
    "chargeback_date": "EKzoFKUzCkbuvgD4GJQq",
    "commission_status": "noRA9xjRD2CzJ74sRjzD",
    "statement_source": "hAqoFTDtVFF9FguS6OUe",
}
EFFECTIVE_DATE_FIELD_ID = "J26TUUZhziZUqBGB2Xlq"
PREMIUM_DRAFT_DATE_FIELD_ID = "3wNPC56VckXQtPOdwBpD"


def _safe_float(val: Optional[str]) -> float:
    if not val:
        return 0.0
    try:
        cleaned = str(val).replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_ghl_timestamp(val) -> Optional[str]:
    """Convert a GHL custom-field value to a YYYY-MM-DD string.

    Handles epoch-millisecond ints/floats, ISO timestamps with 'T', and
    plain YYYY-MM-DD strings.  Mirrors agent_portal._parse_ghl_timestamp.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 1_000_000_000:
        dt = datetime.fromtimestamp(val / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    val_str = str(val)
    if "T" in val_str:
        return val_str[:10]
    if len(val_str) >= 10 and val_str[:4].isdigit():
        return val_str[:10]
    return None

deals_cache: dict[str, tuple[list[dict], float]] = {}
CACHE_TTL = 300  # 5 minutes — reduces slow cold-cache fetches


def _extract_field_by_id(custom_fields: list, field_id: str) -> Optional[str]:
    for cf in custom_fields:
        if cf.get("id") == field_id:
            val = cf.get("value")
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
            return str(val) if val is not None else None
    return None


def _flexible_parse_date(val: str) -> Optional[datetime]:
    """Parse a date string in various formats, returning a datetime or None."""
    val = (val or "").strip()
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%m-%d-%y", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    # Try ISO format with time component
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    return None


def _parse_date_str(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        if "T" in date_str:
            utc_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return utc_dt.astimezone(TZ).strftime("%Y-%m-%d")
        return date_str[:10] if len(date_str) >= 10 else date_str
    except Exception:
        return date_str


def _parse_premium(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _build_deal(raw: dict, agent_field_id: str, premium_field_id: str, advance_status_field_id: str = "") -> dict:
    custom_fields = raw.get("customFields", [])
    if not isinstance(custom_fields, list):
        custom_fields = []

    agent_name = _extract_field_by_id(custom_fields, agent_field_id) or ""
    premium_str = _extract_field_by_id(custom_fields, premium_field_id)
    premium = _parse_premium(premium_str)
    advance_status = _extract_field_by_id(custom_fields, advance_status_field_id) if advance_status_field_id else None

    skip_ids = {agent_field_id, premium_field_id}
    if advance_status_field_id:
        skip_ids.add(advance_status_field_id)

    remaining: dict[str, str] = {}
    for cf in custom_fields:
        field_id = cf.get("id", "")
        val = cf.get("value")
        if val is None or field_id in skip_ids:
            continue
        val_str = ", ".join(str(v) for v in val) if isinstance(val, list) else str(val)
        if val_str.strip():
            remaining[field_id] = val_str

    contact_name = ""
    first = raw.get("firstName", "") or ""
    last = raw.get("lastName", "") or ""
    if first or last:
        contact_name = f"{first} {last}".strip()

    date_added = raw.get("dateAdded", raw.get("createdAt", ""))

    remaining_ids = list(remaining.keys())
    date_fields = [fid for fid in remaining_ids if "T" in (remaining.get(fid) or "")]
    non_date_fields = [fid for fid in remaining_ids if fid not in date_fields]

    policy_number = remaining.get(non_date_fields[0]) if len(non_date_fields) > 0 else None
    plan_name = remaining.get(non_date_fields[1]) if len(non_date_fields) > 1 else None

    date_fields_sorted = sorted(date_fields, key=lambda f: remaining.get(f, ""))
    effective_date = _parse_date_str(remaining.get(date_fields_sorted[0])) if len(date_fields_sorted) > 0 else None
    draft_date = _parse_date_str(remaining.get(date_fields_sorted[1])) if len(date_fields_sorted) > 1 else None

    return {
        "id": raw.get("id", ""),
        "contact_name": contact_name,
        "agent_name": agent_name.strip(),
        "premium": premium,
        "date_added": _parse_date_str(date_added),
        "policy_effective_date": effective_date,
        "premium_draft_date": draft_date,
        "plan_name": plan_name,
        "policy_number": policy_number,
        "advance_status": (advance_status or "").strip().upper(),
    }


def _slim_raw_contact(raw: dict) -> dict:
    """Keep only the fields we use — drops large unused blobs like tags,
    attributions, etc. to cut per-contact memory by ~60-80%.
    """
    return {
        "id": raw.get("id", ""),
        "firstName": raw.get("firstName", ""),
        "lastName": raw.get("lastName", ""),
        "dateAdded": raw.get("dateAdded", raw.get("createdAt", "")),
        "customFields": raw.get("customFields", []),
    }


async def _fetch_all_contacts(api_key: str, location_id: str) -> list[dict]:
    """Fetch all GHL contacts using the GET /contacts/ endpoint with cursor pagination.

    The POST /contacts/search endpoint caps page-based pagination at ~800 results
    and does not support startAfterId.  The GET endpoint uses meta.startAfter and
    meta.startAfterId cursors with no such limit.
    """
    all_contacts: list[dict] = []
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
    }
    params: dict = {
        "locationId": location_id,
        "limit": 100,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                response = await client.get(
                    f"{GHL_BASE_URL}/contacts/",
                    headers=headers,
                    params=params,
                )
                if response.status_code != 200:
                    logger.warning("GHL contacts returned %s, stopping pagination", response.status_code)
                    break
                data = response.json()
                batch = data.get("contacts", [])
                if not batch:
                    break
                all_contacts.extend(_slim_raw_contact(c) for c in batch)
                meta = data.get("meta", {})
                next_after_id = meta.get("startAfterId")
                next_after = meta.get("startAfter")
                if not next_after_id or not next_after or len(batch) < 100:
                    break
                params["startAfterId"] = next_after_id
                params["startAfter"] = next_after
            except Exception:
                logger.exception("Error during GHL contact fetch, stopping")
                break
    logger.info("Fetched %d total contacts for location %s", len(all_contacts), location_id)
    return all_contacts


async def _get_cached_raw_contacts(api_key: str, location_id: str) -> list[dict]:
    cache_key = location_id
    now = time.time()
    if cache_key in deals_cache:
        cached, ts = deals_cache[cache_key]
        if (now - ts) < CACHE_TTL:
            return cached
        else:
            # Expired — free memory immediately
            deals_cache.pop(cache_key, None)
    # Clear any other expired entries
    expired = [k for k, (_, ts) in deals_cache.items() if (now - ts) >= CACHE_TTL]
    for k in expired:
        deals_cache.pop(k, None)
    contacts = await _fetch_all_contacts(api_key, location_id)
    deals_cache[cache_key] = (contacts, now)
    return contacts


async def _get_deals_and_summary(agency: Agency, agent_name: str = ""):
    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        return {"deals": [], "total_count": 0, "total_premium": 0, "summary": None}

    agent_field_id = agency.ghl_agent_field_id or GHL_AGENT_FIELD_ID_DEFAULT
    premium_field_id = agency.ghl_premium_field_id or GHL_PREMIUM_FIELD_ID_DEFAULT
    advance_status_field_id = agency.ghl_advance_status_field_id or ""

    raw_contacts = await _get_cached_raw_contacts(api_key, location_id)

    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    deals = []
    total_premium = 0.0
    today_deals = 0
    today_premium = 0.0
    week_deals = 0
    week_premium = 0.0
    month_deals = 0
    month_premium = 0.0

    for raw in raw_contacts:
        deal = _build_deal(raw, agent_field_id, premium_field_id, advance_status_field_id)
        if agent_name and deal["agent_name"].lower() != agent_name.lower():
            continue
        deals.append(deal)
        total_premium += deal["premium"]

        date_str = deal.get("date_added")
        if date_str:
            try:
                deal_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
            except Exception:
                continue
            if deal_date >= today_start:
                today_deals += 1
                today_premium += deal["premium"]
            if deal_date >= week_start:
                week_deals += 1
                week_premium += deal["premium"]
            if deal_date >= month_start:
                month_deals += 1
                month_premium += deal["premium"]

    deals.sort(key=lambda d: d.get("date_added") or "", reverse=True)

    return {
        "deals": deals,
        "total_count": len(deals),
        "total_premium": round(total_premium, 2),
        "summary": {
            "total": {"deals": len(deals), "premium": round(total_premium, 2)},
            "today": {"deals": today_deals, "premium": round(today_premium, 2)},
            "week": {"deals": week_deals, "premium": round(week_premium, 2)},
            "month": {"deals": month_deals, "premium": round(month_premium, 2)},
        },
    }


@router.get("/{agency_slug}/dashboard-stats")
async def get_dashboard_stats(
    agency_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Policy lifecycle stats for the admin dashboard.

    Reads commission data directly from GHL contact custom fields
    (advance_amount, chargeback_amount, commission_status, chargeback_date,
    statement_source) — the same source of truth used by the agent portal.
    This matches the agent deals view exactly.

    Classification:
      - Not Effectuated: chargeback within 31 days of effective date
      - Cancelled (Chargeback): chargeback after 31 days from effective date
      - Active: advanced 2+ weeks ago, no chargeback
      - Future Active: draft date in the future
      - Pending: no commission data synced, or within 2-week window
    """
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role not in ("super_admin",) and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        return _empty_dashboard_stats()

    premium_field_id = agency.ghl_premium_field_id or GHL_PREMIUM_FIELD_ID_DEFAULT

    raw_contacts = await _get_cached_raw_contacts(api_key, location_id)

    now = datetime.now(TZ).date()

    total_deals = 0
    active_count = 0
    active_premium = 0.0
    pending_count = 0
    pending_premium = 0.0
    future_active_count = 0
    future_active_premium = 0.0
    cancelled_count = 0
    cancelled_premium = 0.0
    not_effectuated_count = 0
    not_effectuated_premium = 0.0
    total_premium = 0.0

    # Time-based deal counters
    today_start = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    today_deals = 0
    today_premium = 0.0
    week_deals = 0
    week_premium = 0.0
    month_deals = 0
    month_premium = 0.0

    for raw in raw_contacts:
        total_deals += 1
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            custom_fields = []

        premium_str = _extract_field_by_id(custom_fields, premium_field_id)
        premium = _parse_premium(premium_str)
        total_premium += premium

        # Time-based counting from dateAdded
        date_added = raw.get("dateAdded", raw.get("createdAt", ""))
        date_str = _parse_date_str(date_added)
        if date_str:
            try:
                deal_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
                if deal_date >= today_start:
                    today_deals += 1
                    today_premium += premium
                if deal_date >= week_start:
                    week_deals += 1
                    week_premium += premium
                if deal_date >= month_start:
                    month_deals += 1
                    month_premium += premium
            except (ValueError, TypeError):
                pass

        # Read commission fields directly from GHL custom fields
        advance_amount = _safe_float(
            _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["advance_amount"])
        )
        chargeback_amount = _safe_float(
            _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["chargeback_amount"])
        )
        chargeback_date_raw = (
            _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["chargeback_date"]) or ""
        )
        commission_status = (
            _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["commission_status"]) or ""
        )
        statement_source = (
            _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["statement_source"]) or ""
        )

        has_advance = advance_amount > 0
        has_chargeback = chargeback_amount > 0 or commission_status.lower() == "chargeback"
        has_any_sync = bool(statement_source)

        # Parse dates from GHL fields
        eff_date_raw = None
        draft_date_raw = None
        for cf in custom_fields:
            fid = cf.get("id", "")
            if fid == EFFECTIVE_DATE_FIELD_ID:
                eff_date_raw = cf.get("value")
            elif fid == PREMIUM_DRAFT_DATE_FIELD_ID:
                draft_date_raw = cf.get("value")

        eff_date_str = _parse_ghl_timestamp(eff_date_raw)
        eff_date = None
        if eff_date_str:
            parsed = _flexible_parse_date(eff_date_str)
            if parsed:
                eff_date = parsed.date()

        draft_date_str = _parse_ghl_timestamp(draft_date_raw)
        draft_date = None
        if draft_date_str:
            parsed = _flexible_parse_date(draft_date_str)
            if parsed:
                draft_date = parsed.date()

        cb_date_str = _parse_ghl_timestamp(chargeback_date_raw) if chargeback_date_raw else None
        cb_date = None
        if cb_date_str:
            parsed = _flexible_parse_date(cb_date_str)
            if parsed:
                cb_date = parsed.date()

        # Classification — mirrors _compute_deal_status in agent_portal.py
        if has_chargeback:
            is_first_month = False
            if eff_date and cb_date:
                days_diff = (cb_date - eff_date).days
                is_first_month = days_diff <= 31
            if is_first_month:
                not_effectuated_count += 1
                not_effectuated_premium += premium
            else:
                cancelled_count += 1
                cancelled_premium += premium
        elif draft_date and draft_date > now:
            # Draft date in the future
            future_active_count += 1
            future_active_premium += premium
        elif has_advance and draft_date:
            days_since_draft = (now - draft_date).days
            if days_since_draft >= 14:
                # Advanced 2+ weeks ago, no chargeback → Active
                active_count += 1
                active_premium += premium
            else:
                # Within 2-week window → Pending
                pending_count += 1
                pending_premium += premium
        elif not has_any_sync:
            # No commission data synced at all → Pending
            pending_count += 1
            pending_premium += premium
        else:
            # Has some sync but no advance and no chargeback → Pending
            pending_count += 1
            pending_premium += premium

    # Rates
    effectuation_rate = round(active_count / total_deals * 100, 1) if total_deals > 0 else 0.0
    cancel_rate = round(cancelled_count / total_deals * 100, 1) if total_deals > 0 else 0.0
    not_effectuated_rate = round(not_effectuated_count / total_deals * 100, 1) if total_deals > 0 else 0.0
    pending_rate = round(pending_count / total_deals * 100, 1) if total_deals > 0 else 0.0

    return {
        "total_deals": total_deals,
        "total_premium": round(total_premium, 2),
        "active_count": active_count,
        "active_premium": round(active_premium, 2),
        "pending_count": pending_count,
        "pending_premium": round(pending_premium, 2),
        "future_active_count": future_active_count,
        "future_active_premium": round(future_active_premium, 2),
        "cancelled_count": cancelled_count,
        "cancelled_premium": round(cancelled_premium, 2),
        "not_effectuated_count": not_effectuated_count,
        "not_effectuated_premium": round(not_effectuated_premium, 2),
        "effectuation_rate": effectuation_rate,
        "cancel_rate": cancel_rate,
        "not_effectuated_rate": not_effectuated_rate,
        "pending_rate": pending_rate,
        "today": {"deals": today_deals, "premium": round(today_premium, 2)},
        "week": {"deals": week_deals, "premium": round(week_premium, 2)},
        "month": {"deals": month_deals, "premium": round(month_premium, 2)},
    }


def _empty_dashboard_stats() -> dict:
    return {
        "total_deals": 0,
        "total_premium": 0.0,
        "active_count": 0,
        "active_premium": 0.0,
        "pending_count": 0,
        "pending_premium": 0.0,
        "future_active_count": 0,
        "future_active_premium": 0.0,
        "cancelled_count": 0,
        "cancelled_premium": 0.0,
        "not_effectuated_count": 0,
        "not_effectuated_premium": 0.0,
        "effectuation_rate": 0.0,
        "cancel_rate": 0.0,
        "not_effectuated_rate": 0.0,
        "pending_rate": 0.0,
        "today": {"deals": 0, "premium": 0.0},
        "week": {"deals": 0, "premium": 0.0},
        "month": {"deals": 0, "premium": 0.0},
    }


@router.get("/{agency_slug}")
async def get_deals_by_slug(
    agency_slug: str,
    agent_name: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role not in ("super_admin",) and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    filter_agent = ""
    if user.role == "agent":
        filter_agent = user.agent_name or ""
    elif agent_name:
        filter_agent = agent_name

    return await _get_deals_and_summary(agency, filter_agent)
