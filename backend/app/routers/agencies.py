import json
import secrets
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, require_role
from app.database import get_db
from app.models import Agency, User
from app.schemas import AgencyCreate, AgencyUpdate, UserCreate

router = APIRouter(prefix="/api/agencies", tags=["agencies"])

DEFAULT_HOURLY_TIERS = json.dumps([
    {"min_policies": 10, "min_avg_premium": 30, "max_avg_premium": 33, "rate": 16.0},
    {"min_policies": 10, "min_avg_premium": 34, "max_avg_premium": 36, "rate": 18.0},
    {"min_policies": 10, "min_avg_premium": 37, "max_avg_premium": 39, "rate": 20.0},
    {"min_policies": 10, "min_avg_premium": 40, "max_avg_premium": 99999, "rate": 22.0},
])

DEFAULT_CHARGEBACK_TIERS = json.dumps([
    {"min_premium": 75, "max_premium": 99999, "window_days": 60},
    {"min_premium": 35, "max_premium": 74.99, "window_days": 90},
    {"min_premium": 0, "max_premium": 34.99, "window_days": 120},
])


@router.get("/")
def list_agencies(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "super_admin":
        agencies = db.query(Agency).all()
    else:
        agencies = db.query(Agency).filter(Agency.id == user.agency_id).all()

    return [
        {
            "id": a.id,
            "code": a.code,
            "name": a.name,
            "slug": a.slug,
            "ghl_location_id": a.ghl_location_id,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else "",
            "hourly_base_rate": a.hourly_base_rate,
            "production_bonus_pct": a.production_bonus_pct,
            "effectuation_bonus_pct": a.effectuation_bonus_pct,
            "pay_day": a.pay_day,
            "payroll_due_day": a.payroll_due_day,
            "period_start_day": a.period_start_day,
            "hours_tracking_method": a.hours_tracking_method,
        }
        for a in agencies
    ]


@router.post("/")
def create_agency(
    req: AgencyCreate,
    user: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    existing = db.query(Agency).filter(
        (Agency.code == req.code) | (Agency.slug == req.slug)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Agency code or slug already exists")

    agency = Agency(
        code=req.code,
        name=req.name,
        slug=req.slug,
        ghl_location_id=req.ghl_location_id,
        ghl_api_key=req.ghl_api_key,
        ghl_agent_field_id=req.ghl_agent_field_id,
        ghl_premium_field_id=req.ghl_premium_field_id,
        hourly_tiers=DEFAULT_HOURLY_TIERS,
        chargeback_tiers=DEFAULT_CHARGEBACK_TIERS,
    )
    db.add(agency)
    db.commit()
    db.refresh(agency)

    return {"id": agency.id, "code": agency.code, "name": agency.name, "slug": agency.slug}


@router.put("/{code}")
def update_agency(
    code: str,
    req: AgencyUpdate,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.code == code).first()
    if not agency:
        agency = db.query(Agency).filter(Agency.slug == code).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Cannot update another agency")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(agency, key, value)

    db.commit()
    db.refresh(agency)
    return {"id": agency.id, "code": agency.code, "name": agency.name, "updated": True}


@router.delete("/{code}")
def deactivate_agency(
    code: str,
    user: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.code == code).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    agency.is_active = False
    db.commit()
    return {"deactivated": True, "code": code}


@router.get("/settings")
def get_agency_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    return {
        "id": agency.id,
        "code": agency.code,
        "name": agency.name,
        "slug": agency.slug,
        "ghl_location_id": agency.ghl_location_id,
        "hourly_base_rate": agency.hourly_base_rate,
        "hourly_tiers": json.loads(agency.hourly_tiers) if agency.hourly_tiers else [],
        "production_bonus_pct": agency.production_bonus_pct,
        "effectuation_bonus_pct": agency.effectuation_bonus_pct,
        "chargeback_tiers": json.loads(agency.chargeback_tiers) if agency.chargeback_tiers else [],
        "pay_day": agency.pay_day,
        "payroll_due_day": agency.payroll_due_day,
        "period_start_day": agency.period_start_day,
        "hours_tracking_method": agency.hours_tracking_method,
    }


@router.put("/settings")
def update_agency_settings(
    req: AgencyUpdate,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            if key in ("hourly_tiers", "chargeback_tiers") and isinstance(value, list):
                setattr(agency, key, json.dumps(value))
            else:
                setattr(agency, key, value)

    db.commit()
    db.refresh(agency)
    return {
        "updated": True,
        "hourly_base_rate": agency.hourly_base_rate,
        "production_bonus_pct": agency.production_bonus_pct,
        "effectuation_bonus_pct": agency.effectuation_bonus_pct,
    }


@router.get("/users")
def list_users(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "super_admin":
        users = db.query(User).all()
    elif user.role == "admin":
        users = db.query(User).filter(User.agency_id == user.agency_id).all()
    else:
        raise HTTPException(status_code=403, detail="Agents cannot list users")

    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "agent_name": u.agent_name,
            "agency_id": u.agency_id,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }
        for u in users
    ]


@router.post("/users")
def create_user(
    req: UserCreate,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = db.query(Agency).filter(Agency.code == req.agency_code).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Cannot create users for another agency")

    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
        agency_id=agency.id,
        agent_name=req.agent_name,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "agent_name": new_user.agent_name,
        "agency_id": new_user.agency_id,
    }


@router.put("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.agency_id != target.agency_id:
        raise HTTPException(status_code=403, detail="Cannot modify another agency's user")
    target.is_active = False
    db.commit()
    return {"success": True, "user_id": user_id, "is_active": False}


@router.put("/users/{user_id}/reactivate")
def reactivate_user(
    user_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.agency_id != target.agency_id:
        raise HTTPException(status_code=403, detail="Cannot modify another agency's user")
    target.is_active = True
    db.commit()
    return {"success": True, "user_id": user_id, "is_active": True}


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.put("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    req: ResetPasswordRequest,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.agency_id != target.agency_id:
        raise HTTPException(status_code=403, detail="Cannot modify another agency's user")
    target.password_hash = hash_password(req.new_password)
    db.commit()
    return {"success": True, "user_id": user_id, "message": "Password reset"}


@router.get("/users/inactive")
def list_inactive_users(
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    users = (
        db.query(User)
        .filter(User.agency_id == user.agency_id, User.role == "agent", User.is_active == False)
        .all()
    )
    return [
        {
            "id": u.id,
            "email": u.email,
            "agent_name": u.agent_name,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }
        for u in users
    ]


def _resolve_agency(slug: str, user: User, db: Session) -> Agency:
    agency = db.query(Agency).filter(Agency.slug == slug).first()
    if not agency:
        agency = db.query(Agency).filter(Agency.code == slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if user.role == "admin" and user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")
    return agency


def _agency_settings_dict(agency: Agency) -> dict:
    return {
        "id": agency.id,
        "code": agency.code,
        "name": agency.name,
        "slug": agency.slug,
        "ghl_api_key": agency.ghl_api_key or "",
        "ghl_location_id": agency.ghl_location_id or "",
        "ghl_agent_field_id": agency.ghl_agent_field_id or "",
        "ghl_premium_field_id": agency.ghl_premium_field_id or "",
        "ghl_advance_status_field_id": agency.ghl_advance_status_field_id or "",
        "ghl_paid_to_agent_field_id": agency.ghl_paid_to_agent_field_id or "",
        "ghl_commission_field_ids": json.loads(agency.ghl_commission_field_ids) if agency.ghl_commission_field_ids else {},
        "hourly_base_rate": agency.hourly_base_rate,
        "hourly_tiers": json.loads(agency.hourly_tiers) if agency.hourly_tiers else [],
        "production_bonus_pct": agency.production_bonus_pct,
        "effectuation_bonus_pct": agency.effectuation_bonus_pct,
        "chargeback_tiers": json.loads(agency.chargeback_tiers) if agency.chargeback_tiers else [],
        "pay_day": agency.pay_day,
        "payroll_due_day": agency.payroll_due_day,
        "period_start_day": agency.period_start_day,
        "hours_tracking_method": agency.hours_tracking_method,
        "calltools_api_key": agency.calltools_api_key or "",
        "calltools_base_url": agency.calltools_base_url or "https://west-4.calltools.io/api",
        "calltools_team_id": agency.calltools_team_id or "",
    }


@router.get("/{agency_slug}")
def get_agency_by_slug(
    agency_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    return _agency_settings_dict(agency)


@router.put("/{agency_slug}")
def update_agency_by_slug(
    agency_slug: str,
    req: AgencyUpdate,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            if key in ("hourly_tiers", "chargeback_tiers") and isinstance(value, list):
                agency.__setattr__(key, json.dumps(value))
            else:
                agency.__setattr__(key, value)

    db.commit()
    db.refresh(agency)
    return {"updated": True, **_agency_settings_dict(agency)}


@router.get("/{agency_slug}/agents")
def list_agents_by_slug(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent")
        .all()
    )
    return [
        {
            "id": a.id,
            "email": a.email,
            "agent_name": a.agent_name,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        for a in agents
    ]


class SlugResetPasswordRequest(BaseModel):
    email: str
    new_password: str


@router.post("/{agency_slug}/agents/reset-password")
def reset_agent_password_by_slug(
    agency_slug: str,
    req: SlugResetPasswordRequest,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    target = db.query(User).filter(User.email == req.email, User.agency_id == agency.id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    target.password_hash = hash_password(req.new_password)
    db.commit()
    return {"success": True, "email": req.email, "message": "Password reset"}


@router.post("/{agency_slug}/agents/{agent_id}/deactivate")
def deactivate_agent_by_slug(
    agency_slug: str,
    agent_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    target = db.query(User).filter(User.id == agent_id, User.agency_id == agency.id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    target.is_active = False
    db.commit()
    return {"success": True, "agent_id": agent_id, "is_active": False}


@router.post("/{agency_slug}/agents/{agent_id}/reactivate")
def reactivate_agent_by_slug(
    agency_slug: str,
    agent_id: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    target = db.query(User).filter(User.id == agent_id, User.agency_id == agency.id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    target.is_active = True
    db.commit()
    return {"success": True, "agent_id": agent_id, "is_active": True}


def _create_agent_username(agent_name: str) -> str:
    parts = agent_name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1]).lower().replace("'", "")
    return agent_name.lower().replace(" ", "").replace("'", "")


@router.get("/{agency_slug}/ghl-agents")
async def list_ghl_agents(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    from app.routers.deals import _get_cached_raw_contacts, _extract_field_by_id

    agency = _resolve_agency(agency_slug, user, db)
    if not agency.ghl_api_key or not agency.ghl_location_id:
        return {"ghl_agents": [], "registered": []}

    raw_contacts = await _get_cached_raw_contacts(agency.ghl_api_key, agency.ghl_location_id)
    agent_field_id = agency.ghl_agent_field_id or ""

    ghl_names: dict[str, int] = {}
    for c in raw_contacts:
        cfs = c.get("customFields", [])
        if not isinstance(cfs, list):
            continue
        name = _extract_field_by_id(cfs, agent_field_id) or ""
        name = name.strip()
        if name:
            ghl_names[name] = ghl_names.get(name, 0) + 1

    existing = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent")
        .all()
    )
    registered_names = {u.agent_name for u in existing}

    # Auto-create logins for GHL agents that don't have one
    auto_created = []
    used_emails: set[str] = set()
    for name in sorted(ghl_names.keys()):
        if name not in registered_names:
            username = _create_agent_username(name)
            email = username
            email_exists = db.query(User).filter(User.email == email).first()
            if email_exists or email in used_emails:
                email = f"{username}{secrets.token_hex(3)}"
            used_emails.add(email)
            new_user = User(
                email=email,
                password_hash=hash_password(DEFAULT_AGENT_PASSWORD),
                role="agent",
                agency_id=agency.id,
                agent_name=name,
                must_change_password=True,
            )
            db.add(new_user)
            auto_created.append(name)
            registered_names.add(name)
    if auto_created:
        db.commit()

    # Re-fetch after auto-creation
    existing = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent")
        .all()
    )

    ghl_agents = []
    for name, count in sorted(ghl_names.items()):
        ghl_agents.append({
            "agent_name": name,
            "deal_count": count,
            "has_login": True,
        })

    return {
        "ghl_agents": ghl_agents,
        "registered": [
            {"id": u.id, "email": u.email, "agent_name": u.agent_name, "is_active": u.is_active}
            for u in existing
        ],
        "auto_created": auto_created,
    }


@router.post("/{agency_slug}/agents/fix-emails")
def fix_agent_emails(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)
    agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent")
        .all()
    )
    updated = []
    for agent in agents:
        parts = agent.agent_name.strip().split()
        if len(parts) >= 2:
            username = (parts[0][0] + parts[-1]).lower().replace("'", "")
        else:
            username = agent.agent_name.lower().replace(" ", "").replace("'", "")
        if agent.email != username:
            updated.append({"old": agent.email, "new": username, "agent_name": agent.agent_name})
            agent.email = username
    db.commit()
    return {"updated": updated, "total": len(updated)}


class GenerateLoginRequest(BaseModel):
    agent_name: str


DEFAULT_AGENT_PASSWORD = "Platinum2026!"


@router.post("/{agency_slug}/agents/generate-login")
def generate_agent_login(
    agency_slug: str,
    req: GenerateLoginRequest,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    agency = _resolve_agency(agency_slug, user, db)

    existing = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.agent_name == req.agent_name, User.role == "agent")
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Agent already has a login")

    username = _create_agent_username(req.agent_name)
    email = username

    email_exists = db.query(User).filter(User.email == email).first()
    if email_exists:
        email = f"{username}{secrets.token_hex(3)}"

    new_user = User(
        email=email,
        password_hash=hash_password(DEFAULT_AGENT_PASSWORD),
        role="agent",
        agency_id=agency.id,
        agent_name=req.agent_name,
        must_change_password=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "email": email,
        "password": DEFAULT_AGENT_PASSWORD,
        "agent_name": req.agent_name,
    }


@router.post("/{agency_slug}/agents/reset-all-passwords")
def reset_all_agent_passwords(
    agency_slug: str,
    user: User = Depends(require_role("super_admin", "admin")),
    db: Session = Depends(get_db),
):
    """Reset ALL agent passwords to the shared default and flag them for change."""
    agency = _resolve_agency(agency_slug, user, db)
    agents = (
        db.query(User)
        .filter(User.agency_id == agency.id, User.role == "agent", User.is_active == True)
        .all()
    )
    count = 0
    for agent in agents:
        agent.password_hash = hash_password(DEFAULT_AGENT_PASSWORD)
        agent.must_change_password = True
        count += 1
    db.commit()
    return {"success": True, "reset_count": count, "default_password": DEFAULT_AGENT_PASSWORD}
