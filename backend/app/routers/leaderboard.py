from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Agency

import os
import time

router = APIRouter(tags=["leaderboard"])

GHL_BASE_URL = "https://services.leadconnectorhq.com"
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))

GHL_AGENT_FIELD_ID_DEFAULT = os.getenv("GHL_AGENT_FIELD_ID", "")
GHL_PREMIUM_FIELD_ID_DEFAULT = os.getenv("GHL_PREMIUM_FIELD_ID", "")
GHL_PLAN_NAME_FIELD_ID_DEFAULT = os.getenv("GHL_PLAN_NAME_FIELD_ID", "")


class SlimContact:
    __slots__ = ("agent", "premium", "date", "state", "plan_name")

    def __init__(self, agent: str, premium: float, date: Optional[datetime], state: str = "", plan_name: str = ""):
        self.agent = agent
        self.premium = premium
        self.date = date
        self.state = state
        self.plan_name = plan_name


agency_caches: dict[str, tuple[list[SlimContact], float]] = {}
CACHE_TTL = 300  # 5 minutes — reduces slow cold-cache fetches


def _extract_field(custom_fields: list, field_id: str) -> Optional[str]:
    for cf in custom_fields:
        if cf.get("id") == field_id:
            val = cf.get("value")
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
            return str(val) if val is not None else None
    return None


def _slim_contact(raw: dict, agent_field_id: str, premium_field_id: str, plan_name_field_id: str = "") -> Optional[SlimContact]:
    custom_fields = raw.get("customFields", [])
    if not isinstance(custom_fields, list):
        return None
    agent = _extract_field(custom_fields, agent_field_id)
    if not agent or not agent.strip():
        return None
    premium_str = _extract_field(custom_fields, premium_field_id)
    premium = _parse_premium(premium_str)
    date = _parse_contact_date(raw)
    state = (raw.get("state") or raw.get("address1State") or "").strip()
    plan_name = ""
    if plan_name_field_id:
        plan_name = (_extract_field(custom_fields, plan_name_field_id) or "").strip()
    return SlimContact(agent=agent.strip(), premium=premium, date=date, state=state, plan_name=plan_name)


async def fetch_contacts_for_agency(api_key: str, location_id: str, agent_field_id: str, premium_field_id: str, plan_name_field_id: str = "") -> list[SlimContact]:
    slim: list[SlimContact] = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                response = await client.post(
                    f"{GHL_BASE_URL}/contacts/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Version": "2021-07-28",
                        "Content-Type": "application/json",
                    },
                    json={
                        "locationId": location_id,
                        "page": page,
                        "pageLimit": 100,
                    },
                )
                if response.status_code != 200:
                    break

                data = response.json()
                batch = data.get("contacts", [])
                total = data.get("total", 0)
                for raw in batch:
                    sc = _slim_contact(raw, agent_field_id, premium_field_id, plan_name_field_id)
                    if sc:
                        slim.append(sc)
                fetched = page * 100 if len(batch) == 100 else (page - 1) * 100 + len(batch)
                if fetched >= total or len(batch) == 0:
                    break
                page += 1
            except Exception:
                break
    return slim


async def get_cached_contacts(api_key: str, location_id: str, agent_field_id: str, premium_field_id: str, plan_name_field_id: str = "") -> list[SlimContact]:
    cache_key = location_id
    now = time.time()
    if cache_key in agency_caches:
        cached, ts = agency_caches[cache_key]
        if (now - ts) < CACHE_TTL:
            return cached
        else:
            agency_caches.pop(cache_key, None)
    # Clear any other expired entries
    expired = [k for k, (_, ts) in agency_caches.items() if (now - ts) >= CACHE_TTL]
    for k in expired:
        agency_caches.pop(k, None)
    contacts = await fetch_contacts_for_agency(api_key, location_id, agent_field_id, premium_field_id, plan_name_field_id)
    agency_caches[cache_key] = (contacts, now)
    return contacts


def _parse_premium(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_contact_date(contact: dict) -> Optional[datetime]:
    date_str = contact.get("dateAdded", contact.get("createdAt", ""))
    if not date_str:
        return None
    try:
        if "T" in date_str:
            utc_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return utc_dt.astimezone(TZ).replace(tzinfo=None)
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def get_week_start_monday(dt: datetime) -> datetime:
    day_of_week = dt.weekday()
    return datetime(dt.year, dt.month, dt.day) - timedelta(days=day_of_week)


def get_month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1)


def get_day_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day)


class LeaderboardEntry(BaseModel):
    name: str
    deals: int
    premium: float


class LeaderboardData(BaseModel):
    leaders: list[LeaderboardEntry]
    period: str
    start_date: str
    end_date: str
    total_deals: int
    total_premium: float


class DealBreakdownItem(BaseModel):
    label: str
    count: int
    premium: float

class DealBreakdown(BaseModel):
    states: list[DealBreakdownItem]
    plan_types: list[DealBreakdownItem]

class LeaderboardResponse(BaseModel):
    daily: LeaderboardData
    weekly: LeaderboardData
    monthly: LeaderboardData
    last_sync: str
    agency_name: str = ""
    agency_slug: str = ""
    daily_breakdown: Optional[DealBreakdown] = None
    weekly_breakdown: Optional[DealBreakdown] = None
    monthly_breakdown: Optional[DealBreakdown] = None


def calculate_leaderboard(
    contacts: list[SlimContact], start_date: datetime, end_date: datetime
) -> LeaderboardData:
    agent_deals: dict[str, int] = defaultdict(int)
    agent_premium: dict[str, float] = defaultdict(float)

    end_of_day = end_date.replace(hour=23, minute=59, second=59)

    for c in contacts:
        if not c.date:
            continue
        if c.date < start_date or c.date > end_of_day:
            continue

        agent_deals[c.agent] += 1
        agent_premium[c.agent] += c.premium

    sorted_agents = sorted(
        agent_deals.keys(), key=lambda a: (-agent_premium[a], -agent_deals[a], a)
    )

    leaders = [
        LeaderboardEntry(
            name=agent,
            deals=agent_deals[agent],
            premium=round(agent_premium[agent], 2),
        )
        for agent in sorted_agents
    ]

    total_deals = sum(agent_deals.values())
    total_premium = round(sum(agent_premium.values()), 2)

    return LeaderboardData(
        leaders=leaders,
        period="",
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        total_deals=total_deals,
        total_premium=total_premium,
    )


@router.get("/leaderboard/{agency_slug}")
async def get_leaderboard_by_slug(agency_slug: str, db: Session = Depends(get_db)):
    agency = db.query(Agency).filter(Agency.slug == agency_slug, Agency.is_active == True).first()
    if not agency:
        return {"error": "Agency not found"}

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        return {"error": "Agency GHL not configured"}

    agent_field_id = agency.ghl_agent_field_id or GHL_AGENT_FIELD_ID_DEFAULT
    premium_field_id = agency.ghl_premium_field_id or GHL_PREMIUM_FIELD_ID_DEFAULT

    plan_name_field_id = GHL_PLAN_NAME_FIELD_ID_DEFAULT
    return await _build_leaderboard(api_key, location_id, agent_field_id, premium_field_id, agency.name, agency.slug, plan_name_field_id)


@router.get("/leaderboard")
async def get_leaderboard():
    api_key = os.getenv("GHL_API_KEY", "")
    location_id = os.getenv("GHL_LOCATION_ID", "")
    agent_field_id = GHL_AGENT_FIELD_ID_DEFAULT
    premium_field_id = GHL_PREMIUM_FIELD_ID_DEFAULT
    plan_name_field_id = GHL_PLAN_NAME_FIELD_ID_DEFAULT

    if not api_key or not location_id:
        return {"error": "GHL not configured"}

    return await _build_leaderboard(api_key, location_id, agent_field_id, premium_field_id, plan_name_field_id=plan_name_field_id)


def _normalize_plan_name(raw: str) -> str:
    key = " ".join(raw.lower().split())
    key = key.replace("healthcare", "health care")
    return key.title()


def _calculate_breakdown(contacts: list[SlimContact], start: datetime, end: datetime) -> DealBreakdown:
    state_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    plan_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for c in contacts:
        if not c.date or c.date < start or c.date > end:
            continue
        st = c.state.upper() if c.state else "Unknown"
        prev_s = state_counts[st]
        state_counts[st] = (prev_s[0] + 1, prev_s[1] + c.premium)
        pn = _normalize_plan_name(c.plan_name) if c.plan_name else "Other"
        prev_p = plan_counts[pn]
        plan_counts[pn] = (prev_p[0] + 1, prev_p[1] + c.premium)
    return DealBreakdown(
        states=sorted([DealBreakdownItem(label=k, count=v[0], premium=round(v[1], 2)) for k, v in state_counts.items()], key=lambda x: -x.count),
        plan_types=sorted([DealBreakdownItem(label=k, count=v[0], premium=round(v[1], 2)) for k, v in plan_counts.items()], key=lambda x: -x.count),
    )


async def _build_leaderboard(
    api_key: str, location_id: str, agent_field_id: str, premium_field_id: str,
    agency_name: str = "", agency_slug: str = "", plan_name_field_id: str = ""
) -> LeaderboardResponse:
    now = datetime.now(timezone.utc).astimezone(TZ).replace(tzinfo=None)

    day_start = get_day_start(now)
    week_start = get_week_start_monday(now)
    month_start = get_month_start(now)

    contacts = await get_cached_contacts(api_key, location_id, agent_field_id, premium_field_id, plan_name_field_id)

    daily = calculate_leaderboard(contacts, day_start, now)
    daily.period = "daily"

    weekly = calculate_leaderboard(contacts, week_start, now)
    weekly.period = "weekly"

    monthly = calculate_leaderboard(contacts, month_start, now)
    monthly.period = "monthly"

    end_of_day = now.replace(hour=23, minute=59, second=59)
    daily_breakdown = _calculate_breakdown(contacts, day_start, end_of_day)
    weekly_breakdown = _calculate_breakdown(contacts, week_start, end_of_day)
    monthly_breakdown = _calculate_breakdown(contacts, month_start, end_of_day)

    return LeaderboardResponse(
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        last_sync=now.isoformat(),
        agency_name=agency_name,
        agency_slug=agency_slug,
        daily_breakdown=daily_breakdown,
        weekly_breakdown=weekly_breakdown,
        monthly_breakdown=monthly_breakdown,
    )
