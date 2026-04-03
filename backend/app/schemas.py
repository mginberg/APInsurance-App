import json
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str  # accepts both usernames (e.g. "lwilliams") and emails
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: str
    must_change_password: bool = False
    user: dict
    agency: dict


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    agency_code: str
    role: str = "agent"
    agent_name: str = ""


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    agent_name: str
    agency_code: str
    is_active: bool
    created_at: datetime


class AgencyCreate(BaseModel):
    code: str
    name: str
    slug: str
    ghl_location_id: str = ""
    ghl_api_key: str = ""
    ghl_agent_field_id: str = ""
    ghl_premium_field_id: str = ""
    ghl_advance_status_field_id: str = ""
    ghl_paid_to_agent_field_id: str = ""
    ghl_commission_field_ids: str = "{}"


class AgencyUpdate(BaseModel):
    name: Optional[str] = None
    ghl_location_id: Optional[str] = None
    ghl_api_key: Optional[str] = None
    ghl_agent_field_id: Optional[str] = None
    ghl_premium_field_id: Optional[str] = None
    ghl_advance_status_field_id: Optional[str] = None
    ghl_paid_to_agent_field_id: Optional[str] = None
    ghl_commission_field_ids: Optional[str] = None
    is_active: Optional[bool] = None
    hourly_base_rate: Optional[float] = None
    hourly_tiers: Optional[str] = None
    production_bonus_pct: Optional[float] = None
    effectuation_bonus_pct: Optional[float] = None
    chargeback_tiers: Optional[str] = None
    pay_day: Optional[str] = None
    payroll_due_day: Optional[str] = None
    period_start_day: Optional[str] = None
    hours_tracking_method: Optional[str] = None
    calltools_api_key: Optional[str] = None
    calltools_base_url: Optional[str] = None
    calltools_team_id: Optional[str] = None


class AgencyOut(BaseModel):
    id: str
    code: str
    name: str
    slug: str
    ghl_location_id: str
    is_active: bool
    created_at: datetime
    hourly_base_rate: float
    hourly_tiers: str
    production_bonus_pct: float
    effectuation_bonus_pct: float
    chargeback_tiers: str
    pay_day: str
    payroll_due_day: str
    period_start_day: str
    hours_tracking_method: str

    @property
    def hourly_tiers_parsed(self) -> list:
        return json.loads(self.hourly_tiers) if self.hourly_tiers else []

    @property
    def chargeback_tiers_parsed(self) -> list:
        return json.loads(self.chargeback_tiers) if self.chargeback_tiers else []
