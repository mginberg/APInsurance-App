import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Agency, SubmissionAgent, User

router = APIRouter(prefix="/api/deal-submission", tags=["deal_submission"])

GHL_V1_BASE_URL = "https://rest.gohighlevel.com/v1"
GHL_V2_BASE_URL = "https://services.leadconnectorhq.com"


def _get_ghl_base_url(api_key: str) -> str:
    """Return the correct GHL API base URL based on the API key type.
    Private Integration Tokens (PIT) start with 'pit-' and require the v2 API."""
    if api_key.startswith("pit-"):
        return GHL_V2_BASE_URL
    return GHL_V1_BASE_URL


class DealSubmissionRequest(BaseModel):
    firstName: str
    lastName: str
    dob: str
    phone: str
    address: Optional[str] = ""
    city: Optional[str] = ""
    state: str
    zipCode: Optional[str] = ""
    planType: str
    premium: str
    policyNumber: str
    effectiveDate: str
    draftDate: str
    agentName: str
    leadId: Optional[str] = ""
    hasAddon: bool = False
    addonPolicyNumber: Optional[str] = ""
    addonPremium: Optional[str] = ""
    addonPlanType: Optional[str] = ""


async def _create_ghl_contact(
    api_key: str, location_id: str, contact_data: dict
) -> dict:
    phone_raw = contact_data.get("phone", "")
    phone_digits = "".join(c for c in phone_raw if c.isdigit())
    phone = f"+1{phone_digits}" if phone_digits else None

    payload = {
        "firstName": contact_data["firstName"],
        "lastName": contact_data["lastName"],
        "phone": phone,
        "dateOfBirth": contact_data.get("dob"),
        "address1": contact_data.get("address"),
        "city": contact_data.get("city"),
        "state": contact_data.get("state"),
        "postalCode": contact_data.get("zipCode"),
        "locationId": location_id,
        "customFields": [
            {"key": "plan_type", "value": contact_data.get("planType")},
            {"key": "plan_premium", "value": contact_data.get("premium")},
            {"key": "policy_number", "value": contact_data.get("policyNumber")},
            {"key": "effective_date", "value": contact_data.get("effectiveDate")},
            {"key": "premium_draft_date", "value": contact_data.get("draftDate")},
            {"key": "agent_name", "value": contact_data.get("agentName")},
        ],
        "tags": [
            "indemnity-deal",
            (contact_data.get("planType") or "").lower().replace(" ", "-"),
        ],
        "source": contact_data.get("leadId") or "Deal Submission Portal",
    }
    payload["customFields"] = [f for f in payload["customFields"] if f.get("value")]
    payload["tags"] = [t for t in payload["tags"] if t]

    base_url = _get_ghl_base_url(api_key)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/contacts",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Version": "2021-07-28",
            },
        )
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=500,
                detail=f"GHL API error: {response.text}",
            )
        return response.json()


@router.get("/agents/{agency_slug}")
async def get_submission_agents(
    agency_slug: str,
    db: Session = Depends(get_db),
):
    """Public endpoint: return list of active submission agent names for the
    deal form dropdown.  Reads from the SubmissionAgent table (managed by admin
    in the Submission Agents section), NOT the User table."""
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


@router.post("/submit/{agency_slug}")
async def submit_deal(
    agency_slug: str,
    req: DealSubmissionRequest,
    db: Session = Depends(get_db),
):
    """Public endpoint: submit a deal and create contact(s) in GHL."""
    agency = db.query(Agency).filter(Agency.slug == agency_slug).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    api_key = agency.ghl_api_key
    location_id = agency.ghl_location_id
    if not api_key or not location_id:
        raise HTTPException(status_code=400, detail="Agency GHL not configured")

    # Validate required fields
    required = {
        "firstName": req.firstName,
        "lastName": req.lastName,
        "dob": req.dob,
        "phone": req.phone,
        "state": req.state,
        "planType": req.planType,
        "premium": req.premium,
        "policyNumber": req.policyNumber,
        "effectiveDate": req.effectiveDate,
        "draftDate": req.draftDate,
        "agentName": req.agentName,
    }
    missing = [k for k, v in required.items() if not v or not str(v).strip()]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Missing required fields: {', '.join(missing)}"
        )

    try:
        primary_contact = await _create_ghl_contact(
            api_key,
            location_id,
            {
                "firstName": req.firstName,
                "lastName": req.lastName,
                "dob": req.dob,
                "phone": req.phone,
                "address": req.address,
                "city": req.city,
                "state": req.state,
                "zipCode": req.zipCode,
                "planType": req.planType,
                "premium": req.premium,
                "policyNumber": req.policyNumber,
                "effectiveDate": req.effectiveDate,
                "draftDate": req.draftDate,
                "agentName": req.agentName,
                "leadId": req.leadId,
            },
        )

        addon_contact = None
        if req.hasAddon and req.addonPolicyNumber and req.addonPremium:
            addon_contact = await _create_ghl_contact(
                api_key,
                location_id,
                {
                    "firstName": req.firstName,
                    "lastName": req.lastName,
                    "dob": req.dob,
                    "phone": req.phone,
                    "address": req.address,
                    "city": req.city,
                    "state": req.state,
                    "zipCode": req.zipCode,
                    "planType": req.addonPlanType or req.planType,
                    "premium": req.addonPremium,
                    "policyNumber": req.addonPolicyNumber,
                    "effectiveDate": req.effectiveDate,
                    "draftDate": req.draftDate,
                    "agentName": req.agentName,
                    "leadId": req.leadId,
                },
            )

        return {
            "success": True,
            "primaryId": primary_contact.get("contact", {}).get("id"),
            "addonId": (
                addon_contact.get("contact", {}).get("id") if addon_contact else None
            ),
            "message": (
                "Both contacts created successfully in GHL."
                if addon_contact
                else "Contact created successfully in GHL."
            ),
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(
            status_code=500, detail=f"GHL API error: {str(err)}"
        )
