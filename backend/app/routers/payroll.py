import json
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, require_role
from app.database import get_db
from app.models import (
    Agency,
    AgentPayroll,
    CommissionRecord,
    HoursEntry,
    PayrollDealRecord,
    PayrollRun,
    User,
)
from app.routers.deals import (
    _build_deal,
    _extract_field_by_id,
    _get_cached_raw_contacts,
    GHL_AGENT_FIELD_ID_DEFAULT,
    GHL_PREMIUM_FIELD_ID_DEFAULT,
)

import re
import secrets
from urllib.parse import quote_plus


def _make_agent_email(agent_name: str, agency_slug: str) -> str:
    parts = agent_name.strip().split()
    if len(parts) >= 2:
        username = (parts[0][0] + parts[-1]).lower()
    else:
        username = agent_name.lower().replace(" ", "")
    return re.sub(r"[^a-z0-9]", "", username) or "agent"


def _make_temp_password() -> str:
    return f"GB{secrets.token_hex(4)}!"  # e.g. GB1a2b3c4d!

router = APIRouter(prefix="/api/payroll", tags=["payroll"])

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))


class HoursInput(BaseModel):
    user_id: str
    week_start: str
    hours: float


class RunPayrollRequest(BaseModel):
    hourly_period_start: str
    hourly_period_end: str
    bonus_period_start: str
    bonus_period_end: str


def _get_monday(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def _parse_agency_tiers(tiers_json: str) -> list[dict]:
    try:
        return json.loads(tiers_json) if tiers_json else []
    except (json.JSONDecodeError, TypeError):
        return []


def calculate_hourly_rate(
    base_rate: float,
    tiers: list[dict],
    deal_count: int,
    avg_premium: float,
) -> float:
    rate = base_rate
    for tier in tiers:
        min_policies = tier.get("min_policies", 0)
        min_avg = tier.get("min_avg_premium", 0)
        max_avg = tier.get("max_avg_premium", 99999)
        tier_rate = tier.get("rate", base_rate)
        if deal_count >= min_policies and min_avg <= avg_premium <= max_avg:
            rate = max(rate, tier_rate)
    return rate


def _get_already_paid_contact_ids(db: Session, agency_id: str) -> set[str]:
    paid_records = (
        db.query(PayrollDealRecord.ghl_contact_id)
        .join(AgentPayroll)
        .join(PayrollRun)
        .filter(
            PayrollRun.agency_id == agency_id,
            PayrollRun.status == "approved",
            PayrollDealRecord.status == "paid",
        )
        .all()
    )
    return {r[0] for r in paid_records}


async def _get_all_agency_deals(agency: Agency) -> list[dict]:
    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        return []
    agent_field_id = agency.ghl_agent_field_id or GHL_AGENT_FIELD_ID_DEFAULT
    premium_field_id = agency.ghl_premium_field_id or GHL_PREMIUM_FIELD_ID_DEFAULT
    advance_status_field_id = agency.ghl_advance_status_field_id or ""
    raw_contacts = await _get_cached_raw_contacts(api_key, location_id)
    deals = []
    for raw in raw_contacts:
        deal = _build_deal(raw, agent_field_id, premium_field_id, advance_status_field_id)
        deals.append(deal)
    return deals


async def _get_agent_deals(agency: Agency, agent_name: str) -> list[dict]:
    all_deals = await _get_all_agency_deals(agency)
    return [d for d in all_deals if d["agent_name"].lower() == agent_name.lower()]


def _deal_is_payable(deal: dict, as_of_date: str) -> bool:
    if (deal.get("advance_status") or "").upper() != "ADVANCED":
        return False
    draft_date = deal.get("premium_draft_date")
    effective_date = deal.get("policy_effective_date")
    if not draft_date or not effective_date:
        return False
    return draft_date <= as_of_date and effective_date <= as_of_date


def _find_pending_deals_from_prior_runs(
    db: Session, agency_id: str
) -> list[dict]:
    pending = (
        db.query(PayrollDealRecord)
        .join(AgentPayroll)
        .join(PayrollRun)
        .filter(
            PayrollRun.agency_id == agency_id,
            PayrollRun.status == "approved",
            PayrollDealRecord.status == "pending_effectuation",
        )
        .all()
    )
    return [
        {
            "record_id": r.id,
            "ghl_contact_id": r.ghl_contact_id,
            "contact_name": r.contact_name,
            "agent_name": r.agent_name,
            "premium": r.premium,
            "date_added": r.date_added,
            "policy_effective_date": r.policy_effective_date,
            "premium_draft_date": r.premium_draft_date,
            "policy_number": r.policy_number,
            "plan_name": r.plan_name,
            "bonus_type": r.bonus_type,
        }
        for r in pending
    ]


def _make_deal_record_dict(d: dict, bonus_amount: float, status: str, source: str) -> dict:
    return {
        "contact_name": d.get("contact_name", ""),
        "premium": d["premium"],
        "bonus_amount": bonus_amount,
        "draft_date": d.get("premium_draft_date", ""),
        "date_added": d.get("date_added", ""),
        "status": status,
        "source": source,
        "policy_number": d.get("policy_number", ""),
    }


def _make_deal_record_model(
    agent_payroll_id: str, d: dict, bonus_amount: float,
    status: str, source_period: str,
) -> PayrollDealRecord:
    return PayrollDealRecord(
        agent_payroll_id=agent_payroll_id,
        ghl_contact_id=d["id"],
        contact_name=d.get("contact_name", ""),
        agent_name=d.get("agent_name", ""),
        premium=d["premium"],
        bonus_type="production",
        bonus_amount=bonus_amount,
        date_added=d.get("date_added", ""),
        policy_effective_date=d.get("policy_effective_date", "") or "",
        premium_draft_date=d.get("premium_draft_date", "") or "",
        policy_number=d.get("policy_number", "") or "",
        plan_name=d.get("plan_name", "") or "",
        status=status,
        source_period=source_period,
    )


class RunPayrollBody(BaseModel):
    hourly_start: str
    hourly_end: str
    bonus_start: str
    bonus_end: str
    hours_worked: float = 40.0


@router.post("/{agency_slug}/run")
async def run_payroll_slug(
    agency_slug: str,
    body: RunPayrollBody,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    req = RunPayrollRequest(
        hourly_period_start=body.hourly_start,
        hourly_period_end=body.hourly_end,
        bonus_period_start=body.bonus_start,
        bonus_period_end=body.bonus_end,
    )
    return await _run_payroll_impl(req, agency, body.hours_worked, user, db)


async def _run_payroll_impl(
    req: RunPayrollRequest,
    agency: Agency,
    default_hours: float,
    user: User,
    db: Session,
):
    agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent", User.is_active == True)
        .all()
    )

    all_deals = await _get_all_agency_deals(agency)
    already_paid_ids = _get_already_paid_contact_ids(db, agency.id)
    pending_from_prior = _find_pending_deals_from_prior_runs(db, agency.id)
    pending_by_contact: dict[str, dict] = {
        p["ghl_contact_id"]: p for p in pending_from_prior
    }

    hourly_tiers = _parse_agency_tiers(agency.hourly_tiers)
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")

    payroll_run = PayrollRun(
        agency_id=agency.id,
        hourly_period_start=req.hourly_period_start,
        hourly_period_end=req.hourly_period_end,
        bonus_period_start=req.bonus_period_start,
        bonus_period_end=req.bonus_period_end,
        status="draft",
    )
    db.add(payroll_run)
    db.flush()

    agent_results = []

    for agent in agents:
        if not agent.agent_name:
            continue

        agent_deals = [
            d for d in all_deals
            if d["agent_name"].lower() == agent.agent_name.lower()
        ]

        bonus_deals_current = [
            d for d in agent_deals
            if d.get("date_added")
            and req.bonus_period_start <= d["date_added"] <= req.bonus_period_end
            and d["id"] not in already_paid_ids
            and (d.get("advance_status") or "").upper() == "ADVANCED"
        ]

        rolled_forward_deals = []
        bonus_current_ids = {d["id"] for d in bonus_deals_current}
        for d in agent_deals:
            if d["id"] in pending_by_contact and d["id"] not in already_paid_ids and d["id"] not in bonus_current_ids:
                if _deal_is_payable(d, today_str):
                    rolled_forward_deals.append(d)

        hourly_deals = [
            d for d in agent_deals
            if d.get("date_added")
            and req.hourly_period_start <= d["date_added"] <= req.hourly_period_end
        ]
        deal_count = len(hourly_deals)
        total_premium = sum(d["premium"] for d in hourly_deals)
        avg_premium = round(total_premium / deal_count, 2) if deal_count > 0 else 0.0

        hourly_rate = calculate_hourly_rate(
            agency.hourly_base_rate, hourly_tiers, deal_count, avg_premium
        )

        hours_entry = (
            db.query(HoursEntry)
            .filter(HoursEntry.user_id == agent.id, HoursEntry.week_start == _get_monday(req.hourly_period_start))
            .first()
        )
        hours_worked = hours_entry.hours if hours_entry else 0.0
        hourly_pay = round(hourly_rate * hours_worked, 2)

        agent_payroll = AgentPayroll(
            payroll_run_id=payroll_run.id,
            user_id=agent.id,
            agent_name=agent.agent_name,
            hourly_rate=hourly_rate,
            hours_worked=hours_worked,
            hourly_pay=hourly_pay,
            deal_count=deal_count,
            total_premium=round(total_premium, 2),
            avg_premium=avg_premium,
        )
        db.add(agent_payroll)
        db.flush()

        production_bonus = 0.0
        deal_records_data = []

        for d in bonus_deals_current:
            effectuated = _deal_is_payable(d, today_str)
            if effectuated:
                bonus_amount = round(d["premium"] * (agency.production_bonus_pct / 100.0), 2)
                production_bonus += bonus_amount
                db.add(_make_deal_record_model(agent_payroll.id, d, bonus_amount, "paid", "current"))
                deal_records_data.append(_make_deal_record_dict(d, bonus_amount, "paid", "current"))
            else:
                db.add(_make_deal_record_model(agent_payroll.id, d, 0.0, "pending_effectuation", "current"))
                deal_records_data.append(_make_deal_record_dict(d, 0.0, "pending_effectuation", "current"))

        for d in rolled_forward_deals:
            bonus_amount = round(d["premium"] * (agency.production_bonus_pct / 100.0), 2)
            production_bonus += bonus_amount

            db.add(_make_deal_record_model(agent_payroll.id, d, bonus_amount, "paid", "rolled_forward"))
            deal_records_data.append(_make_deal_record_dict(d, bonus_amount, "paid", "rolled_forward"))

        production_bonus = round(production_bonus, 2)
        total_pay = round(hourly_pay + production_bonus, 2)

        agent_payroll.production_bonus = production_bonus
        agent_payroll.total_pay = total_pay

        agent_results.append({
            "agent_id": agent.id,
            "agent_name": agent.agent_name,
            "agent_email": agent.email,
            "hourly_rate": hourly_rate,
            "hours_worked": hours_worked,
            "hourly_pay": hourly_pay,
            "deal_count": deal_count,
            "total_premium": round(total_premium, 2),
            "avg_premium": avg_premium,
            "production_bonus": production_bonus,
            "total_pay": total_pay,
            "deals": deal_records_data,
            "deals_paid": len([d for d in deal_records_data if d["status"] == "paid"]),
            "deals_pending": len([d for d in deal_records_data if d["status"] == "pending_effectuation"]),
            "deals_rolled_forward": len([d for d in deal_records_data if d["source"] == "rolled_forward"]),
        })

    db.commit()

    return {
        "payroll_run_id": payroll_run.id,
        "agency": agency.name,
        "hourly_period": f"{req.hourly_period_start} to {req.hourly_period_end}",
        "bonus_period": f"{req.bonus_period_start} to {req.bonus_period_end}",
        "status": "draft",
        "agents": agent_results,
        "total_payroll": round(sum(r["total_pay"] for r in agent_results), 2),
        "total_deals_paid": sum(r["deals_paid"] for r in agent_results),
        "total_deals_pending": sum(r["deals_pending"] for r in agent_results),
        "total_deals_rolled_forward": sum(r["deals_rolled_forward"] for r in agent_results),
    }


@router.post("/{agency_slug}/runs/{run_id}/approve")
async def approve_payroll(
    agency_slug: str,
    run_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    payroll_run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not payroll_run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if payroll_run.agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="Not your agency")
    payroll_run.status = "approved"

    agency = db.query(Agency).filter(Agency.id == payroll_run.agency_id).first()
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    ghl_updates = 0

    for ap in payroll_run.agent_payrolls:
        for dr in ap.deal_records:
            if dr.source_period == "rolled_forward" and dr.status == "paid":
                prior_pending = (
                    db.query(PayrollDealRecord)
                    .join(AgentPayroll)
                    .join(PayrollRun)
                    .filter(
                        PayrollDealRecord.ghl_contact_id == dr.ghl_contact_id,
                        PayrollDealRecord.status == "pending_effectuation",
                        PayrollRun.id != run_id,
                        PayrollRun.agency_id == payroll_run.agency_id,
                        PayrollRun.status == "approved",
                    )
                    .first()
                )
                if prior_pending:
                    prior_pending.status = "rolled_forward"

            if dr.status == "paid" and dr.policy_number:
                comm_rec = (
                    db.query(CommissionRecord)
                    .filter(
                        CommissionRecord.agency_id == payroll_run.agency_id,
                        CommissionRecord.policy_number == dr.policy_number,
                    )
                    .first()
                )
                if comm_rec:
                    comm_rec.paid_to_agent = True
                    comm_rec.paid_to_agent_date = today_str
                    comm_rec.payroll_run_id = run_id

            if dr.status == "paid" and agency and agency.ghl_paid_to_agent_field_id and agency.ghl_api_key and dr.ghl_contact_id:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        await client.put(
                            f"https://services.leadconnectorhq.com/contacts/{dr.ghl_contact_id}",
                            headers={
                                "Authorization": f"Bearer {agency.ghl_api_key}",
                                "Version": "2021-07-28",
                                "Content-Type": "application/json",
                            },
                            json={"customFields": [{"id": agency.ghl_paid_to_agent_field_id, "value": f"Paid {today_str}"}]},
                        )
                        ghl_updates += 1
                except Exception:
                    pass

    db.commit()
    return {"success": True, "run_id": run_id, "status": "approved", "ghl_updates": ghl_updates}


@router.delete("/{agency_slug}/runs/{run_id}")
async def delete_payroll_run(
    agency_slug: str,
    run_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    payroll_run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not payroll_run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if payroll_run.agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="Not your agency")
    if payroll_run.status == "approved":
        raise HTTPException(status_code=400, detail="Cannot delete approved payroll")
    db.delete(payroll_run)
    db.commit()
    return {"success": True, "deleted": run_id}


@router.get("/{agency_slug}/runs")
async def list_payroll_runs(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    runs = (
        db.query(PayrollRun)
        .filter(PayrollRun.agency_id == user.agency_id)
        .order_by(PayrollRun.created_at.desc())
        .all()
    )
    results = []
    for run in runs:
        total_pay = sum(ap.total_pay for ap in run.agent_payrolls)
        agent_count = len(run.agent_payrolls)
        total_deals = sum(ap.deal_count for ap in run.agent_payrolls)
        paid_deals = sum(
            len([dr for dr in ap.deal_records if dr.status == "paid"])
            for ap in run.agent_payrolls
        )
        pending_deals = sum(
            len([dr for dr in ap.deal_records if dr.status == "pending_effectuation"])
            for ap in run.agent_payrolls
        )
        results.append({
            "id": run.id,
            "hourly_period": f"{run.hourly_period_start} to {run.hourly_period_end}",
            "bonus_period": f"{run.bonus_period_start} to {run.bonus_period_end}",
            "status": run.status,
            "agent_count": agent_count,
            "total_deals": total_deals,
            "paid_deals": paid_deals,
            "pending_deals": pending_deals,
            "total_pay": round(total_pay, 2),
            "created_at": run.created_at.isoformat() if run.created_at else "",
        })
    return {"runs": results}


@router.get("/{agency_slug}/runs/{run_id}")
async def get_payroll_run(
    agency_slug: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payroll_run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not payroll_run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if payroll_run.agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="Not your agency")

    agents_data = []
    for ap in payroll_run.agent_payrolls:
        if user.role == "agent" and ap.user_id != user.id:
            continue
        deal_records = [
            {
                "id": dr.id,
                "contact_name": dr.contact_name,
                "premium": dr.premium,
                "bonus_amount": dr.bonus_amount,
                "date_added": dr.date_added,
                "draft_date": dr.premium_draft_date,
                "policy_number": dr.policy_number,
                "plan_name": dr.plan_name,
                "status": dr.status,
                "source": dr.source_period,
            }
            for dr in ap.deal_records
        ]
        agents_data.append({
            "agent_id": ap.user_id,
            "agent_name": ap.agent_name,
            "agent_email": ap.user.email if ap.user else "",
            "hourly_rate": ap.hourly_rate,
            "hours_worked": ap.hours_worked,
            "hourly_pay": ap.hourly_pay,
            "deal_count": ap.deal_count,
            "total_premium": ap.total_premium,
            "avg_premium": ap.avg_premium,
            "production_bonus": ap.production_bonus,
            "total_pay": ap.total_pay,
            "deals": deal_records,
            "deals_paid": len([d for d in deal_records if d["status"] == "paid"]),
            "deals_pending": len([d for d in deal_records if d["status"] == "pending_effectuation"]),
            "deals_rolled_forward": len([d for d in deal_records if d["source"] == "rolled_forward"]),
        })

    return {
        "id": payroll_run.id,
        "agency": payroll_run.agency.name if payroll_run.agency else "",
        "hourly_period": f"{payroll_run.hourly_period_start} to {payroll_run.hourly_period_end}",
        "bonus_period": f"{payroll_run.bonus_period_start} to {payroll_run.bonus_period_end}",
        "status": payroll_run.status,
        "agents": agents_data,
        "total_payroll": round(sum(a["total_pay"] for a in agents_data), 2),
        "created_at": payroll_run.created_at.isoformat() if payroll_run.created_at else "",
    }


@router.get("/{agency_slug}/pending-deals")
async def get_pending_deals(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    pending = (
        db.query(PayrollDealRecord)
        .join(AgentPayroll)
        .join(PayrollRun)
        .filter(PayrollRun.agency_id == user.agency_id, PayrollRun.status == "approved", PayrollDealRecord.status == "pending_effectuation")
        .all()
    )

    all_deals = await _get_all_agency_deals(agency)
    live_deal_map = {d["id"]: d for d in all_deals}

    results = []
    for r in pending:
        live = live_deal_map.get(r.ghl_contact_id, {})
        current_draft_date = live.get("premium_draft_date") or r.premium_draft_date
        now_effectuated = bool(
            current_draft_date and current_draft_date <= datetime.now(TZ).strftime("%Y-%m-%d")
        )
        results.append({
            "id": r.id,
            "contact_name": r.contact_name,
            "agent_name": r.agent_name,
            "premium": r.premium,
            "date_added": r.date_added,
            "original_draft_date": r.premium_draft_date,
            "current_draft_date": current_draft_date,
            "policy_number": r.policy_number,
            "now_effectuated": now_effectuated,
        })

    return {
        "pending_deals": results,
        "total": len(results),
        "ready_to_pay": len([r for r in results if r["now_effectuated"]]),
    }


@router.get("/{agency_slug}/summary")
async def my_payroll_summary(
    agency_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    if not user.agent_name:
        return {"message": "No agent name configured", "payroll": None}

    deals = await _get_agent_deals(agency, user.agent_name)

    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    month_start = now.replace(day=1).strftime("%Y-%m-%d")

    week_deals = [d for d in deals if d.get("date_added") and week_start <= d["date_added"] <= today]
    month_deals = [d for d in deals if d.get("date_added") and month_start <= d["date_added"] <= today]

    week_count = len(week_deals)
    week_premium = sum(d["premium"] for d in week_deals)
    week_avg = round(week_premium / week_count, 2) if week_count > 0 else 0.0

    hourly_tiers = _parse_agency_tiers(agency.hourly_tiers)
    hourly_rate = calculate_hourly_rate(agency.hourly_base_rate, hourly_tiers, week_count, week_avg)

    hours_entry = (
        db.query(HoursEntry).filter(HoursEntry.user_id == user.id, HoursEntry.week_start == week_start).first()
    )
    hours_worked = hours_entry.hours if hours_entry else 0.0

    recent_agent_payrolls = (
        db.query(AgentPayroll)
        .join(PayrollRun)
        .filter(AgentPayroll.user_id == user.id, PayrollRun.status == "approved")
        .order_by(PayrollRun.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "agent_name": user.agent_name,
        "current_week": {
            "period": f"{week_start} to {today}",
            "deals": week_count,
            "total_premium": round(week_premium, 2),
            "avg_premium": week_avg,
            "hourly_rate": hourly_rate,
            "hours_worked": hours_worked,
            "estimated_hourly_pay": round(hourly_rate * hours_worked, 2),
        },
        "current_month": {
            "deals": len(month_deals),
            "total_premium": round(sum(d["premium"] for d in month_deals), 2),
        },
        "recent_payroll": [
            {
                "id": ap.payroll_run_id,
                "agent_payroll_id": ap.id,
                "period": f"{ap.payroll_run.hourly_period_start} to {ap.payroll_run.hourly_period_end}",
                "hourly_pay": ap.hourly_pay,
                "production_bonus": ap.production_bonus,
                "total_pay": ap.total_pay,
                "status": ap.payroll_run.status,
            }
            for ap in recent_agent_payrolls
        ],
    }


@router.post("/hours")
def set_hours(
    entry: HoursInput,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    target_user = db.query(User).filter(User.id == entry.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.agency_id != target_user.agency_id:
        raise HTTPException(status_code=403, detail="Cannot set hours for another agency")

    monday = _get_monday(entry.week_start)
    existing = (
        db.query(HoursEntry).filter(HoursEntry.user_id == entry.user_id, HoursEntry.week_start == monday).first()
    )
    if existing:
        existing.hours = entry.hours
    else:
        new_entry = HoursEntry(
            agency_id=target_user.agency_id, user_id=entry.user_id,
            week_start=monday, hours=entry.hours, source="manual",
        )
        db.add(new_entry)
    db.commit()
    return {"success": True, "week_start": monday, "hours": entry.hours}


@router.post("/hours/bulk")
def set_hours_bulk(
    entries: list[HoursInput],
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    results = []
    for entry in entries:
        target_user = db.query(User).filter(User.id == entry.user_id).first()
        if not target_user:
            continue
        if user.role == "admin" and user.agency_id != target_user.agency_id:
            continue
        monday = _get_monday(entry.week_start)
        existing = (
            db.query(HoursEntry).filter(HoursEntry.user_id == entry.user_id, HoursEntry.week_start == monday).first()
        )
        if existing:
            existing.hours = entry.hours
        else:
            new_entry = HoursEntry(
                agency_id=target_user.agency_id, user_id=entry.user_id,
                week_start=monday, hours=entry.hours, source="manual",
            )
            db.add(new_entry)
        results.append({"user_id": entry.user_id, "week_start": monday, "hours": entry.hours})
    db.commit()
    return {"success": True, "entries": results}


@router.get("/hours")
def get_hours(
    week_start: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(TZ)
    if not week_start:
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    else:
        week_start = _get_monday(week_start)

    if user.role == "agent":
        entries = db.query(HoursEntry).filter(HoursEntry.user_id == user.id, HoursEntry.week_start == week_start).all()
    else:
        entries = db.query(HoursEntry).filter(HoursEntry.agency_id == user.agency_id, HoursEntry.week_start == week_start).all()

    return {
        "week_start": week_start,
        "entries": [{"id": e.id, "user_id": e.user_id, "hours": e.hours, "source": e.source} for e in entries],
    }


@router.post("/sync-agents")
async def sync_agents_from_ghl(
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    if not agency.ghl_api_key or not agency.ghl_location_id:
        raise HTTPException(status_code=400, detail="Agency GHL not configured")

    agent_field_id = agency.ghl_agent_field_id or GHL_AGENT_FIELD_ID_DEFAULT
    if not agent_field_id:
        raise HTTPException(status_code=400, detail="Agency GHL agent field not configured")

    raw_contacts = await _get_cached_raw_contacts(agency.ghl_api_key, agency.ghl_location_id)
    ghl_agent_names: set[str] = set()
    for raw in raw_contacts:
        custom_fields = raw.get("customFields", [])
        if not isinstance(custom_fields, list):
            continue
        raw_name = _extract_field_by_id(custom_fields, agent_field_id)
        name = (raw_name or "").strip()
        if name:
            ghl_agent_names.add(name)

    existing_agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent")
        .all()
    )
    existing_names = {(a.agent_name or "").lower() for a in existing_agents}

    created_accounts: list[dict] = []
    for name in sorted(ghl_agent_names):
        if name.lower() in existing_names:
            continue

        email = _make_agent_email(name, agency.slug)
        if db.query(User).filter(User.email == email).first():
            continue

        temp_password = _make_temp_password()
        new_agent = User(
            email=email,
            password_hash=hash_password(temp_password),
            role="agent",
            agency_id=agency.id,
            agent_name=name,
        )
        db.add(new_agent)
        created_accounts.append({"email": email, "agent_name": name, "temp_password": temp_password})

    if len(created_accounts) > 0:
        db.commit()

    agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent", User.is_active == True)
        .all()
    )
    return {
        "agents": [
            {"id": a.id, "email": a.email, "agent_name": a.agent_name, "is_active": a.is_active}
            for a in agents
        ],
        "synced": len(created_accounts),
        "created_accounts": created_accounts,
    }


@router.get("/agents")
async def list_agents(
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agents = (
        db.query(User)
        .filter(User.agency_id == user.agency_id, User.role == "agent", User.is_active == True)
        .all()
    )
    return {
        "agents": [
            {"id": a.id, "email": a.email, "agent_name": a.agent_name, "is_active": a.is_active}
            for a in agents
        ]
    }
