import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Agency, User
from app.routers.deals import (
    _extract_field_by_id,
    _fetch_all_contacts,
    _get_cached_raw_contacts,
    _parse_date_str,
    _parse_premium,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache for CallTools data (avoids repeated slow API calls)
# ---------------------------------------------------------------------------
_ct_cache: dict[str, tuple[float, Any]] = {}  # key -> (expiry_timestamp, data)
_CT_AGENTS_TTL = 600   # 10 minutes for agent list
_CT_REPORT_TTL = 300   # 5 minutes for hourly report results
_CT_BILLABLE_TTL = 3600  # 1 hour — background task refreshes this


def _cache_get(key: str) -> Any | None:
    """Return cached value if key exists and hasn't expired, else None."""
    entry = _ct_cache.get(key)
    if entry is None:
        return None
    expiry, data = entry
    if time.monotonic() > expiry:
        _ct_cache.pop(key, None)
        return None
    return data


def _cache_clear_expired() -> None:
    """Remove all expired entries from the cache to free memory."""
    now = time.monotonic()
    expired = [k for k, (expiry, _) in _ct_cache.items() if now > expiry]
    for k in expired:
        _ct_cache.pop(k, None)


def _cache_set(key: str, data: Any, ttl: float) -> None:
    """Store data in cache with a TTL in seconds. Clears expired entries first."""
    _cache_clear_expired()
    _ct_cache[key] = (time.monotonic() + ttl, data)


# ---------------------------------------------------------------------------
# CallTools dialer status IDs
# ---------------------------------------------------------------------------
# These numeric IDs were discovered by correlating agentstatusevents with
# web_phone_status strings and analysing transition patterns.
CT_STATUS_AVAILABLE = 1815   # Agent is available / waiting for a call
CT_STATUS_ON_CALL   = 1820   # Agent is on a call
CT_STATUS_POST_CALL = 1819   # Post-call / wrap-up time

# Only the first 20 minutes (1200 seconds) of each post-call session count
# toward billable hours.
POST_CALL_CAP_SECONDS = 20 * 60

# Cap each Available session at 30 minutes (1800 seconds) to handle agents
# who forget to log off the dialer at night.
AVAILABLE_CAP_SECONDS = 30 * 60

router = APIRouter(prefix="/api/agent-portal", tags=["agent_portal"])

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))

GHL_PLAN_NAME_FIELD_ID_DEFAULT = os.getenv("GHL_PLAN_NAME_FIELD_ID", "")

COMMISSION_FIELD_IDS = {
    "advance_amount": "rCi4tXps9wESiJ0x0XiV",
    "chargeback_amount": "L0vXXdqaRYJuZOpAOOHz",
    "chargeback_date": "4QAy1aVGNPvK7WOowE2E",
    "commission_status": "YAg9HHNsx8fGts4CeVQr",
    "statement_source": "6oz2H79SJlLBwxpDuL3g",
    "transaction_type": "554NFCkbFZxcokqXajOH",
    "transaction_code": "w3KUPmjV5tw6saUBSqzz",
    "transaction_reason": "l7XLJ0JYXliiWZ4wQxRc",
    "code_reason": "SLKwpuoiU3uPCkFsw5X4",
    "wc_transaction_type": "554NFCkbFZxcokqXajOH",
    "wc_transaction_code": "w3KUPmjV5tw6saUBSqzz",
    "paid_to_date": "Q1HJfFTFXpdwHL6g0PL2",
    "last_activity_date": "hYUpojFbAcLuiPf72qrt",
}

POLICY_NUMBER_FIELD_ID = "FTrS62XRKzMJa13FBKYm"
EFFECTIVE_DATE_FIELD_ID = "YHGc05k3v3Feb7Yu4GlF"
PREMIUM_DRAFT_DATE_FIELD_ID = "eAM7bAij8So6a0yf2Hia"


def _safe_float(val: Optional[str]) -> float:
    if not val:
        return 0.0
    try:
        cleaned = str(val).replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _generate_bonus_weeks(count: int = 12) -> list[dict]:
    now = datetime.now(TZ)
    today = now.date()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)

    weeks = []
    for i in range(count):
        week_monday = current_monday - timedelta(weeks=i)
        week_sunday = week_monday + timedelta(days=6)
        weeks.append({
            "week_start": week_monday.isoformat(),
            "week_end": week_sunday.isoformat(),
            "label": f"{week_monday.strftime('%m/%d/%Y')} - {week_sunday.strftime('%m/%d/%Y')}",
        })
    return weeks


def _parse_ghl_timestamp(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 1000000000:
        dt = datetime.fromtimestamp(val / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    val_str = str(val)
    if "T" in val_str:
        return val_str[:10]
    if len(val_str) >= 10 and val_str[:4].isdigit():
        return val_str[:10]
    return None


def _compute_deal_status(
    effective_date_str: Optional[str],
    premium_draft_date_str: Optional[str],
    advance_amount: float,
    chargeback_amount: float,
    chargeback_date_str: Optional[str],
    commission_status: str,
    statement_source: str,
    wc_reason: str,
    mc_reason: str,
) -> dict:
    now = datetime.now(TZ).date()

    has_advance = advance_amount > 0
    has_chargeback = chargeback_amount > 0 or commission_status.lower() == "chargeback"
    has_any_sync = bool(statement_source)

    if has_chargeback:
        eff_date = None
        cb_date = None
        if effective_date_str:
            try:
                eff_date = datetime.strptime(effective_date_str[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass
        if chargeback_date_str:
            try:
                cb_date = datetime.strptime(chargeback_date_str[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        is_first_month = False
        if eff_date and cb_date:
            days_diff = (cb_date - eff_date).days
            is_first_month = days_diff <= 31

        reason_parts = []
        if wc_reason:
            reason_parts.append(f"WC: {wc_reason}")
        if mc_reason:
            reason_parts.append(f"MC: {mc_reason}")
        reason = " | ".join(reason_parts) if reason_parts else ""

        if is_first_month:
            return {"status": "Not Effectuated", "payable": False, "reason": reason}
        else:
            return {"status": "Chargeback", "payable": False, "reason": reason}

    draft_date = None
    if premium_draft_date_str:
        try:
            draft_date = datetime.strptime(premium_draft_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    if has_advance and draft_date:
        days_since_draft = (now - draft_date).days
        if days_since_draft >= 14:
            return {"status": "Active / Billable", "payable": True, "reason": ""}

    if not has_any_sync:
        return {"status": "Pending", "payable": False, "reason": ""}

    if has_advance and not draft_date:
        return {"status": "Pending", "payable": False, "reason": "Awaiting premium draft"}

    if has_advance and draft_date:
        return {"status": "Pending", "payable": False, "reason": "Within 2-week window"}

    return {"status": "Pending", "payable": False, "reason": ""}


def _build_agent_deal(raw: dict, agent_field_id: str, premium_field_id: str) -> dict:
    custom_fields = raw.get("customFields", [])
    if not isinstance(custom_fields, list):
        custom_fields = []

    agent_name = _extract_field_by_id(custom_fields, agent_field_id) or ""
    premium_str = _extract_field_by_id(custom_fields, premium_field_id)
    premium = _parse_premium(premium_str)

    first = raw.get("firstName", "") or ""
    last = raw.get("lastName", "") or ""
    contact_name = f"{first} {last}".strip()

    date_added = raw.get("dateAdded", raw.get("createdAt", ""))
    date_added_parsed = _parse_date_str(date_added)

    advance_amount = _safe_float(_extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["advance_amount"]))
    chargeback_amount = _safe_float(_extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["chargeback_amount"]))
    chargeback_date = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["chargeback_date"]) or ""
    commission_status = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["commission_status"]) or ""
    statement_source = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["statement_source"]) or ""

    wc_trans_type = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["wc_transaction_type"]) or ""
    wc_trans_code = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["wc_transaction_code"]) or ""
    mc_trans_reason = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["transaction_reason"]) or ""
    mc_code_reason = _extract_field_by_id(custom_fields, COMMISSION_FIELD_IDS["code_reason"]) or ""

    wc_parts = [p for p in [wc_trans_type, wc_trans_code] if p]
    wc_reason = " \u2014 ".join(wc_parts) if wc_parts else ""
    mc_parts = [p for p in [mc_trans_reason, mc_code_reason] if p]
    mc_reason = " \u2014 ".join(mc_parts) if mc_parts else ""

    policy_number = _extract_field_by_id(custom_fields, POLICY_NUMBER_FIELD_ID) or ""
    plan_name = _extract_field_by_id(custom_fields, GHL_PLAN_NAME_FIELD_ID_DEFAULT) or ""

    eff_date_raw = None
    draft_date_raw = None
    for cf in custom_fields:
        fid = cf.get("id", "")
        if fid == EFFECTIVE_DATE_FIELD_ID:
            eff_date_raw = cf.get("value")
        elif fid == PREMIUM_DRAFT_DATE_FIELD_ID:
            draft_date_raw = cf.get("value")
    effective_date = _parse_ghl_timestamp(eff_date_raw)
    premium_draft_date = _parse_ghl_timestamp(draft_date_raw)

    chargeback_date_parsed = _parse_ghl_timestamp(chargeback_date) if chargeback_date else None

    status_info = _compute_deal_status(
        effective_date_str=effective_date,
        premium_draft_date_str=premium_draft_date,
        advance_amount=advance_amount,
        chargeback_amount=chargeback_amount,
        chargeback_date_str=chargeback_date_parsed or chargeback_date,
        commission_status=commission_status,
        statement_source=statement_source,
        wc_reason=wc_reason,
        mc_reason=mc_reason,
    )

    return {
        "id": raw.get("id", ""),
        "contact_name": contact_name,
        "agent_name": agent_name.strip(),
        "premium": premium,
        "date_added": date_added_parsed,
        "policy_number": policy_number,
        "effective_date": effective_date,
        "premium_draft_date": premium_draft_date,
        "plan_name": plan_name,
        "status": status_info["status"],
        "payable": status_info["payable"],
        "reason": status_info["reason"],
    }


def _monday_of(d: datetime) -> str:
    dt = d if hasattr(d, 'weekday') else d.date() if hasattr(d, 'date') else d
    monday = dt - timedelta(days=dt.weekday())
    return monday.isoformat()


@router.get("/{agency_slug}/bonus-weeks")
async def get_bonus_weeks(
    agency_slug: str,
    agent_name: Optional[str] = Query(None, description="Agent name override (admin only)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        return {"weeks": []}

    agent_field_id = agency.ghl_agent_field_id or ""
    is_admin = user.role in ("super_admin", "admin")
    if is_admin and agent_name:
        agent_name = agent_name
    else:
        agent_name = user.agent_name or ""

    raw_contacts = await _get_cached_raw_contacts(api_key, location_id)

    week_mondays: set[str] = set()
    for raw in raw_contacts:
        cfs = raw.get("customFields", [])
        if not isinstance(cfs, list):
            continue
        name = _extract_field_by_id(cfs, agent_field_id) or ""
        if agent_name and name.strip().lower() != agent_name.lower():
            continue

        date_added = raw.get("dateAdded", raw.get("createdAt", ""))
        da_parsed = _parse_date_str(date_added)
        if da_parsed:
            try:
                dt = datetime.strptime(da_parsed, "%Y-%m-%d").date()
                week_mondays.add(_monday_of(dt))
            except (ValueError, TypeError):
                pass

    weeks = []
    for mon_str in sorted(week_mondays, reverse=True):
        mon = datetime.strptime(mon_str, "%Y-%m-%d").date()
        sun = mon + timedelta(days=6)
        weeks.append({
            "week_start": mon.isoformat(),
            "week_end": sun.isoformat(),
            "label": f"{mon.strftime('%m/%d/%Y')} - {sun.strftime('%m/%d/%Y')}",
        })

    return {"weeks": weeks}


# ---------------------------------------------------------------------------
# CallTools billable-hours helpers
# ---------------------------------------------------------------------------

def _normalize_ct_key(api_key: str) -> str:
    """Ensure CallTools key has exactly one 'Token ' prefix."""
    key = api_key.strip()
    if key.lower().startswith("token "):
        key = key[6:]  # strip existing prefix regardless of case
    return f"Token {key}"


async def _fetch_calltools_agents(
    base_url: str, api_key: str,
) -> dict[str, str]:
    """Return {app_user_uuid: full_name} from CallTools /agentstatuses/.

    Results are cached for 10 minutes to avoid repeated slow API calls.
    """
    cache_key = f"ct_agents:{base_url}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    mapping: dict[str, str] = {}
    url = f"{base_url}/agentstatuses/"
    headers = {"Authorization": _normalize_ct_key(api_key)}
    async with httpx.AsyncClient(timeout=90) as client:
        while url:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            for agent in data.get("results", []):
                uid = agent.get("app_user", "")
                name = agent.get("full_name", "")
                if uid and name:
                    mapping[uid] = name
            url = data.get("next")
    _cache_set(cache_key, mapping, _CT_AGENTS_TTL)
    return mapping


async def _fetch_team_agents(
    base_url: str, api_key: str, team_id: str,
) -> dict[str, str]:
    """Return {app_user_uuid: full_name} for agents in a specific CallTools team.

    Uses /api/agentstatuses/?team={team_id} to get only agents belonging to
    that team.  Results are cached for 10 minutes.
    """
    cache_key = f"ct_team_agents:{base_url}:{team_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    mapping: dict[str, str] = {}
    url = f"{base_url}/agentstatuses/"
    headers = {"Authorization": _normalize_ct_key(api_key)}
    params: dict[str, str] = {"team": team_id, "page_size": "250"}
    async with httpx.AsyncClient(timeout=90) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            for agent in data.get("results", []):
                uid = agent.get("app_user", "")
                name = agent.get("full_name", "")
                if uid and name:
                    mapping[uid] = name
            url = data.get("next")
            params = {}  # next URL already includes params
    logger.info("Fetched %d agents from CallTools team %s", len(mapping), team_id)
    _cache_set(cache_key, mapping, _CT_AGENTS_TTL)
    return mapping


async def _fetch_and_compute_billable(
    base_url: str, api_key: str,
    start_date: str, end_date: str,
) -> dict[str, dict]:
    """Fetch ALL agents' status events and compute billable seconds per agent.

    Returns a dict of {app_user_uuid: billable_breakdown} where each
    breakdown has available_sec, on_call_sec, post_call_billable_sec,
    post_call_total_sec, total_billable_sec.

    **Memory-efficient**: Events are processed page-by-page and discarded
    immediately.  Only running per-agent second totals (~4 ints per agent)
    are kept in memory — never the 42K+ raw event dicts.
    """
    page_size = 250
    params: dict[str, str] = {
        "start__gte": start_date,
        "start__lte": end_date,
        "page_size": str(page_size),
    }
    url = f"{base_url}/agentstatusevents/"
    headers = {"Authorization": _normalize_ct_key(api_key)}

    # Running totals per agent — only ~4 ints per agent, not 42K event dicts
    agent_available: dict[str, int] = {}
    agent_on_call: dict[str, int] = {}
    agent_post_call_billable: dict[str, int] = {}
    agent_post_call_total: dict[str, int] = {}
    total_raw = 0
    total_kept = 0

    def _process_events(events: list[dict]) -> None:
        nonlocal total_raw, total_kept
        total_raw += len(events)
        for ev in events:
            ev_start = (ev.get("start") or "")[:10]
            if not (ev_start and start_date <= ev_start < end_date):
                continue
            uid = ev.get("app_user", "")
            if not uid:
                continue
            total_kept += 1
            status = ev.get("agent_status")
            dur = ev.get("duration", 0) or 0
            if status == CT_STATUS_AVAILABLE:
                agent_available[uid] = agent_available.get(uid, 0) + min(dur, AVAILABLE_CAP_SECONDS)
            elif status == CT_STATUS_ON_CALL:
                agent_on_call[uid] = agent_on_call.get(uid, 0) + dur
            elif status == CT_STATUS_POST_CALL:
                agent_post_call_total[uid] = agent_post_call_total.get(uid, 0) + dur
                agent_post_call_billable[uid] = agent_post_call_billable.get(uid, 0) + min(dur, POST_CALL_CAP_SECONDS)

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        page1_events: list[dict] = data.get("results", [])
        total_count = data.get("count", 0)
        total_pages = (total_count + page_size - 1) // page_size if total_count else 1
        logger.info(
            "CallTools bulk fetch: %d events across %d pages",
            total_count, total_pages,
        )

        _process_events(page1_events)
        del page1_events

        if total_pages > 1:
            sem = asyncio.Semaphore(10)

            async def _fetch_page(page_num: int) -> list[dict]:
                async with sem:
                    page_params = {**params, "page": str(page_num)}
                    r = await client.get(url, headers=headers, params=page_params)
                    r.raise_for_status()
                    return r.json().get("results", [])

            remaining_pages = list(range(2, total_pages + 1))
            batch_size = 10
            for i in range(0, len(remaining_pages), batch_size):
                batch = remaining_pages[i:i + batch_size]
                tasks = [_fetch_page(p) for p in batch]
                page_results = await asyncio.gather(*tasks)
                for page_events in page_results:
                    _process_events(page_events)
                del page_results

    logger.info(
        "CallTools bulk fetch complete: kept %d / %d events for %d agents in [%s, %s)",
        total_kept, total_raw, len(agent_available), start_date, end_date,
    )

    # Build per-agent breakdown dicts (tiny — ~5 numbers per agent)
    all_uids = set(agent_available) | set(agent_on_call) | set(agent_post_call_billable)
    result: dict[str, dict] = {}
    for uid in all_uids:
        avail = agent_available.get(uid, 0)
        on_call = agent_on_call.get(uid, 0)
        pc_bill = agent_post_call_billable.get(uid, 0)
        pc_total = agent_post_call_total.get(uid, 0)
        result[uid] = {
            "available_sec": avail,
            "on_call_sec": on_call,
            "post_call_billable_sec": pc_bill,
            "post_call_total_sec": pc_total,
            "total_billable_sec": avail + on_call + pc_bill,
        }

    return result


@router.get("/{agency_slug}/billable-hours")
async def get_billable_hours(
    agency_slug: str,
    week_start: str = Query(..., description="Monday of the week (YYYY-MM-DD)"),
    week_end: str = Query(..., description="Sunday of the week (YYYY-MM-DD)"),
    agent_name: Optional[str] = Query(None, description="Agent name override (admin only)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return billable hours for a single agent from the pre-computed cache.

    The background task refreshes the cache every hour.  This endpoint
    never hits CallTools directly — it reads from the tiny cached
    per-agent breakdown (~5 numbers per agent).
    """
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    ct_key = agency.calltools_api_key or os.getenv("CALLTOOLS_API_KEY", "")
    ct_base = agency.calltools_base_url or "https://west-4.calltools.io/api"
    if not ct_key:
        raise HTTPException(status_code=400, detail="CallTools API key not configured")

    is_admin = user.role in ("super_admin", "admin")
    target_agent = agent_name if (is_admin and agent_name) else (user.agent_name or "")

    try:
        datetime.strptime(week_start, "%Y-%m-%d")
        datetime.strptime(week_end, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    end_dt = datetime.strptime(week_end, "%Y-%m-%d") + timedelta(days=1)
    api_end = end_dt.strftime("%Y-%m-%d")

    # Try the pre-computed bulk cache first (background task refreshes hourly)
    bulk_key = f"billable_bulk:{agency_slug}:{week_start}:{api_end}"
    per_agent_billable = _cache_get(bulk_key)

    if per_agent_billable is None:
        # Cache miss — compute on demand (first request after startup)
        logger.info("Billable cache miss for %s — computing on demand", agency_slug)
        try:
            per_agent_billable = await _fetch_and_compute_billable(
                ct_base, ct_key, week_start, api_end,
            )
            _cache_set(bulk_key, per_agent_billable, _CT_BILLABLE_TTL)
        except Exception as exc:
            logger.error("CallTools events error: %s", exc)
            raise HTTPException(status_code=502, detail="Failed to fetch CallTools events")

    # Match agent name to CallTools UUID
    try:
        ct_agents = await _fetch_calltools_agents(ct_base, ct_key)
    except httpx.HTTPError as exc:
        logger.error("CallTools agentstatuses error: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch CallTools agents")

    matched_uuid: str | None = None
    for uid, ct_name in ct_agents.items():
        if target_agent and ct_name.strip().lower() == target_agent.strip().lower():
            matched_uuid = uid
            break

    if not matched_uuid and target_agent:
        target_lower = target_agent.strip().lower()
        for uid, ct_name in ct_agents.items():
            if target_lower in ct_name.lower() or ct_name.lower() in target_lower:
                matched_uuid = uid
                break

    if not matched_uuid:
        return {
            "agent_name": target_agent,
            "week_start": week_start,
            "week_end": week_end,
            "billable_hours": 0.0,
            "available_hours": 0.0,
            "on_call_hours": 0.0,
            "post_call_billable_hours": 0.0,
            "hourly_rate": agency.hourly_base_rate or 15.0,
            "hourly_pay": 0.0,
            "error": f"No matching CallTools agent found for '{target_agent}'",
        }

    breakdown = per_agent_billable.get(matched_uuid, {
        "available_sec": 0,
        "on_call_sec": 0,
        "post_call_billable_sec": 0,
        "post_call_total_sec": 0,
        "total_billable_sec": 0,
    })
    billable_hours = round(breakdown["total_billable_sec"] / 3600, 2)
    available_hours = round(breakdown["available_sec"] / 3600, 2)
    on_call_hours = round(breakdown["on_call_sec"] / 3600, 2)
    post_call_hours = round(breakdown["post_call_billable_sec"] / 3600, 2)

    hourly_rate = agency.hourly_base_rate or 15.0
    hourly_pay = round(billable_hours * hourly_rate, 2)

    return {
        "agent_name": target_agent,
        "week_start": week_start,
        "week_end": week_end,
        "billable_hours": billable_hours,
        "available_hours": available_hours,
        "on_call_hours": on_call_hours,
        "post_call_billable_hours": post_call_hours,
        "hourly_rate": hourly_rate,
        "hourly_pay": hourly_pay,
    }


@router.get("/{agency_slug}/standard-weeks")
async def get_standard_weeks(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Return the last 12 calendar weeks (no GHL dependency)."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")
    return {"weeks": _generate_bonus_weeks(12)}


async def _build_hourly_report(
    agency_slug: str,
    agency: Agency,
    ct_key: str,
    ct_base: str,
    week_start: str,
    api_end: str,
    db: Session,
    per_agent_billable: dict[str, dict] | None = None,
) -> dict:
    """Heavy lifting for hourly report — separated so results can be cached.

    Uses CallTools Team ID (stored on the agency) to determine which agents
    to include in the report instead of matching registered agent logins.

    If *per_agent_billable* is provided (e.g. from background task), the
    expensive CallTools event fetch is skipped entirely.
    """
    team_id = agency.calltools_team_id or ""

    # Fetch team members from CallTools (or fall back to all agents)
    try:
        if team_id:
            team_agents = await _fetch_team_agents(ct_base, ct_key, team_id)
        else:
            team_agents = await _fetch_calltools_agents(ct_base, ct_key)
    except httpx.HTTPError as exc:
        logger.error(
            "CallTools agentstatuses error: %s (status=%s, url=%s)",
            exc,
            getattr(exc, 'response', {}) and getattr(exc.response, 'status_code', '?'),
            ct_base,
        )
        raise HTTPException(status_code=502, detail=f"Failed to fetch CallTools agents: {exc}")
    except Exception as exc:
        logger.error("CallTools unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=f"CallTools error: {exc}")

    # Use pre-computed data if provided, otherwise fetch fresh
    if per_agent_billable is None:
        try:
            per_agent_billable = await _fetch_and_compute_billable(
                ct_base, ct_key, week_start, api_end,
            )
        except httpx.HTTPError as exc:
            logger.error("CallTools agentstatusevents bulk fetch error: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch CallTools events: {exc}",
            )
        except Exception as exc:
            logger.error("CallTools unexpected error fetching events: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"CallTools error: {exc}",
            )

    agent_rows = []
    total_billable = 0.0

    # Iterate over team members (not registered logins)
    for uid, agent_name in team_agents.items():
        if uid in per_agent_billable:
            breakdown = per_agent_billable[uid]
            billable = round(breakdown["total_billable_sec"] / 3600, 2)
            available = round(breakdown["available_sec"] / 3600, 2)
            on_call = round(breakdown["on_call_sec"] / 3600, 2)
            post_call = round(breakdown["post_call_billable_sec"] / 3600, 2)
        else:
            billable = available = on_call = post_call = 0.0

        total_billable += billable

        agent_rows.append({
            "agent_name": agent_name,
            "matched": True,
            "billable_hours": billable,
            "available_hours": available,
            "on_call_hours": on_call,
            "post_call_billable_hours": post_call,
        })

    agent_rows.sort(key=lambda r: r["billable_hours"], reverse=True)

    return {
        "week_start": week_start,
        "week_end": api_end,
        "agents": agent_rows,
        "total_billable_hours": round(total_billable, 2),
    }


@router.get("/{agency_slug}/hourly-report")
async def get_hourly_report(
    agency_slug: str,
    week_start: str = Query(..., description="Monday of the week (YYYY-MM-DD)"),
    week_end: str = Query(..., description="Sunday of the week (YYYY-MM-DD)"),
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Admin endpoint: fetch billable hours for ALL agents in a given week.

    Results are cached for 5 minutes to avoid repeated slow CallTools API calls.
    """
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    ct_key = agency.calltools_api_key or os.getenv("CALLTOOLS_API_KEY", "")
    ct_base = agency.calltools_base_url or "https://west-4.calltools.io/api"
    if not ct_key:
        raise HTTPException(status_code=400, detail="CallTools API key not configured")

    try:
        datetime.strptime(week_start, "%Y-%m-%d")
        datetime.strptime(week_end, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    end_dt = datetime.strptime(week_end, "%Y-%m-%d") + timedelta(days=1)
    api_end = end_dt.strftime("%Y-%m-%d")

    # Check for pre-computed hourly report from background task first
    report_cache_key = f"hourly_report:{agency_slug}:{week_start}:{week_end}"
    cached_report = _cache_get(report_cache_key)
    if cached_report is not None:
        logger.info("Hourly report cache hit for %s week %s", agency_slug, week_start)
        return cached_report

    logger.info("Hourly report cache miss for %s week %s — computing on demand", agency_slug, week_start)
    report = await _build_hourly_report(
        agency_slug, agency, ct_key, ct_base, week_start, api_end, db,
    )

    report["week_start"] = week_start
    report["week_end"] = week_end

    # Cache with the longer TTL (1 hour) — background task will refresh it
    _cache_set(report_cache_key, report, _CT_BILLABLE_TTL)
    return report


@router.get("/{agency_slug}/deals")
async def get_agent_deals_by_week(
    agency_slug: str,
    week_start: str = Query(..., description="Monday of the bonus week (YYYY-MM-DD)"),
    week_end: str = Query(..., description="Sunday of the bonus week (YYYY-MM-DD)"),
    agent_name: Optional[str] = Query(None, description="Agent name override (admin only)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        raise HTTPException(status_code=400, detail="GHL not configured")

    agent_field_id = agency.ghl_agent_field_id or ""
    premium_field_id = agency.ghl_premium_field_id or ""
    is_admin = user.role in ("super_admin", "admin")
    if is_admin and agent_name:
        agent_name = agent_name
    else:
        agent_name = user.agent_name or ""

    try:
        ws = datetime.strptime(week_start, "%Y-%m-%d").date()
        we = datetime.strptime(week_end, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    raw_contacts = await _get_cached_raw_contacts(api_key, location_id)

    all_deals = []
    for raw in raw_contacts:
        deal = _build_agent_deal(raw, agent_field_id, premium_field_id)
        if agent_name and deal["agent_name"].lower() != agent_name.lower():
            continue
        all_deals.append(deal)

    submitted_deals = []
    payable_deals = []
    failed_deals = []

    failed_statuses = {"not effectuated", "chargeback"}

    for deal in all_deals:
        # Submitted deals: filtered by date_added (created date) in the week
        da = deal.get("date_added")
        if da:
            try:
                added_date = datetime.strptime(da, "%Y-%m-%d").date()
                if ws <= added_date <= we:
                    submitted_deals.append(deal)
            except (ValueError, TypeError):
                pass

        # Payable and Failed deals: filtered by premium_draft_date in the week
        dpd = deal.get("premium_draft_date")
        if dpd:
            try:
                draft_date = datetime.strptime(dpd, "%Y-%m-%d").date()
                if ws <= draft_date <= we:
                    if deal["status"].lower() in failed_statuses:
                        failed_deals.append(deal)
                    elif deal["payable"]:
                        payable_deals.append(deal)
            except (ValueError, TypeError):
                pass

    submitted_deals.sort(key=lambda d: d.get("date_added") or "", reverse=True)
    payable_deals.sort(key=lambda d: d.get("premium_draft_date") or "", reverse=True)
    failed_deals.sort(key=lambda d: d.get("premium_draft_date") or "", reverse=True)

    total_submitted_premium = sum(d["premium"] for d in submitted_deals)
    total_payable_premium = sum(d["premium"] for d in payable_deals)
    total_failed_premium = sum(d["premium"] for d in failed_deals)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "submitted_deals": submitted_deals,
        "submitted_count": len(submitted_deals),
        "submitted_premium": round(total_submitted_premium, 2),
        "payable_deals": payable_deals,
        "payable_count": len(payable_deals),
        "payable_premium": round(total_payable_premium, 2),
        "failed_deals": failed_deals,
        "failed_count": len(failed_deals),
        "failed_premium": round(total_failed_premium, 2),
        "all_deals_count": len(all_deals),
    }


# ---------------------------------------------------------------------------
# Background task: pre-compute billable hours for all agencies every hour
# ---------------------------------------------------------------------------
async def refresh_billable_cache_for_all_agencies() -> None:
    """Fetch CallTools events for the current week for every agency that has a
    CallTools API key configured, compute per-agent billable seconds, and
    cache the results.

    Called once at startup and then every hour by the background scheduler
    in main.py.  This means agent/admin endpoints never need to hit CallTools
    live — they always read from the pre-computed cache.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        agencies = db.query(Agency).all()
    finally:
        db.close()

    today = datetime.now(timezone.utc).astimezone(
        ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))
    ).date()
    # Current week: Monday to Sunday
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_start = monday.strftime("%Y-%m-%d")
    week_end = sunday.strftime("%Y-%m-%d")
    api_end = (sunday + timedelta(days=1)).strftime("%Y-%m-%d")

    for agency in agencies:
        ct_key = agency.calltools_api_key or os.getenv("CALLTOOLS_API_KEY", "")
        ct_base = agency.calltools_base_url or "https://west-4.calltools.io/api"
        if not ct_key:
            continue

        slug = agency.slug or agency.code.lower()
        bulk_key = f"billable_bulk:{slug}:{week_start}:{api_end}"

        try:
            logger.info(
                "Background refresh: computing billable data for %s week %s",
                slug, week_start,
            )
            per_agent_billable = await _fetch_and_compute_billable(
                ct_base, ct_key, week_start, api_end,
            )
            _cache_set(bulk_key, per_agent_billable, _CT_BILLABLE_TTL)
            logger.info(
                "Background refresh: cached billable data for %s (%d agents)",
                slug, len(per_agent_billable),
            )

            # Also pre-build the hourly report — pass pre-computed billable
            # data so _build_hourly_report skips the duplicate CallTools fetch
            db2 = SessionLocal()
            try:
                agency_fresh = db2.query(Agency).filter(Agency.id == agency.id).first()
                if agency_fresh:
                    report = await _build_hourly_report(
                        slug, agency_fresh, ct_key, ct_base, week_start, api_end, db2,
                        per_agent_billable=per_agent_billable,
                    )
                    report["week_start"] = week_start
                    report["week_end"] = week_end
                    report_key = f"hourly_report:{slug}:{week_start}:{week_end}"
                    _cache_set(report_key, report, _CT_BILLABLE_TTL)
                    logger.info(
                        "Background refresh: cached hourly report for %s (%d agents)",
                        slug, len(report.get("agents", [])),
                    )
            finally:
                db2.close()

        except Exception as exc:
            logger.error(
                "Background refresh failed for %s: %s", slug, exc,
            )
