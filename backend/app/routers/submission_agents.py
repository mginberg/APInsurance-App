"""CRUD routes for Submission Agents — the agent names shown in the deal
submission form dropdown.  Completely separate from the User / GHL agent
tables.  Names are stored ALL CAPS and de-duplicated per agency."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import Agency, SubmissionAgent, User

router = APIRouter(
    prefix="/api/submission-agents",
    tags=["submission_agents"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AddAgentsRequest(BaseModel):
    """Accepts one or more agent names.  Each is uppercased and trimmed."""
    names: list[str]


class RemoveAgentRequest(BaseModel):
    agent_id: str


# ---------------------------------------------------------------------------
# Public — used by the deal submission form
# ---------------------------------------------------------------------------

@router.get("/{agency_slug}")
def list_submission_agents(agency_slug: str, db: Session = Depends(get_db)):
    """Return the sorted list of active submission agent names for the
    deal-form dropdown.  Public endpoint (no auth required)."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    agents = (
        db.query(SubmissionAgent)
        .filter(SubmissionAgent.agency_id == agency.id, SubmissionAgent.is_active == True)
        .order_by(SubmissionAgent.name)
        .all()
    )
    return {"agents": [a.name for a in agents]}


# ---------------------------------------------------------------------------
# Admin — manage the list
# ---------------------------------------------------------------------------

@router.get("/{agency_slug}/admin")
def list_submission_agents_admin(
    agency_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin", "admin")),
):
    """Admin view — returns full objects (id, name, created_at)."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if current_user.role == "admin" and current_user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")
    agents = (
        db.query(SubmissionAgent)
        .filter(SubmissionAgent.agency_id == agency.id, SubmissionAgent.is_active == True)
        .order_by(SubmissionAgent.name)
        .all()
    )
    return {
        "agents": [
            {"id": a.id, "name": a.name, "created_at": str(a.created_at)}
            for a in agents
        ]
    }


@router.post("/{agency_slug}")
def add_submission_agents(
    agency_slug: str,
    req: AddAgentsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin", "admin")),
):
    """Add one or more agent names (bulk).  Names are uppercased, trimmed,
    and de-duplicated against existing entries for this agency."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if current_user.role == "admin" and current_user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    # Normalise & deduplicate input
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in req.names:
        name = raw.strip().upper()
        if name and name not in seen:
            cleaned.append(name)
            seen.add(name)

    if not cleaned:
        raise HTTPException(status_code=400, detail="No valid names provided")

    # Existing names for this agency (active)
    existing_names: set[str] = {
        a.name
        for a in db.query(SubmissionAgent)
        .filter(SubmissionAgent.agency_id == agency.id, SubmissionAgent.is_active == True)
        .all()
    }

    added: list[str] = []
    for name in cleaned:
        if name not in existing_names:
            db.add(SubmissionAgent(agency_id=agency.id, name=name))
            added.append(name)

    if added:
        db.commit()

    return {
        "added": sorted(added),
        "skipped_duplicates": sorted(seen - set(added)),
        "total_added": len(added),
    }


@router.delete("/{agency_slug}/{agent_id}")
def remove_submission_agent(
    agency_slug: str,
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin", "admin")),
):
    """Soft-delete a submission agent by marking it inactive."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")
    if current_user.role == "admin" and current_user.agency_id != agency.id:
        raise HTTPException(status_code=403, detail="Not your agency")

    agent = (
        db.query(SubmissionAgent)
        .filter(
            SubmissionAgent.id == agent_id,
            SubmissionAgent.agency_id == agency.id,
        )
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Submission agent not found")

    agent.is_active = False
    db.commit()
    return {"success": True, "removed": agent.name}
