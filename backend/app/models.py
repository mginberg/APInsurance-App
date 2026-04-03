import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Agency(Base):
    __tablename__ = "agencies"

    id = Column(String, primary_key=True, default=new_uuid)
    code = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    ghl_api_key = Column(String, default="")
    ghl_location_id = Column(String, default="")
    ghl_agent_field_id = Column(String, default="")
    ghl_premium_field_id = Column(String, default="")
    ghl_advance_status_field_id = Column(String, default="")
    ghl_paid_to_agent_field_id = Column(String, default="")
    ghl_commission_field_ids = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    hourly_base_rate = Column(Float, default=15.0)
    hourly_tiers = Column(Text, default="[]")
    production_bonus_pct = Column(Float, default=100.0)
    effectuation_bonus_pct = Column(Float, default=10.0)
    chargeback_tiers = Column(Text, default="[]")
    pay_day = Column(String, default="friday")
    payroll_due_day = Column(String, default="wednesday")
    period_start_day = Column(String, default="monday")
    hours_tracking_method = Column(String, default="manual")

    calltools_api_key = Column(String, default="")
    calltools_base_url = Column(String, default="https://west-4.calltools.io/api")
    calltools_team_id = Column(String, default="")

    users = relationship("User", back_populates="agency", lazy="selectin")
    sync_logs = relationship("SyncLog", back_populates="agency", lazy="selectin")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="agent")
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    agent_name = Column(String, default="")
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    agency = relationship("Agency", back_populates="users")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(String, primary_key=True, default=new_uuid)
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    statement_type = Column(String, nullable=False)
    file_name = Column(String, default="")
    total_rows = Column(Integer, default=0)
    matched_rows = Column(Integer, default=0)
    unmatched_rows = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

    agency = relationship("Agency", back_populates="sync_logs")
    unmatched_records = relationship(
        "UnmatchedRecord", back_populates="sync_log", lazy="selectin"
    )


class UnmatchedRecord(Base):
    __tablename__ = "unmatched_records"

    id = Column(String, primary_key=True, default=new_uuid)
    sync_log_id = Column(String, ForeignKey("sync_logs.id"), nullable=False)
    policy_number = Column(String, default="")
    raw_data = Column(Text, default="{}")
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    sync_log = relationship("SyncLog", back_populates="unmatched_records")


class HoursEntry(Base):
    __tablename__ = "hours_entries"

    id = Column(String, primary_key=True, default=new_uuid)
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    week_start = Column(String, nullable=False)
    hours = Column(Float, default=0.0)
    source = Column(String, default="manual")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    agency = relationship("Agency")
    user = relationship("User")


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id = Column(String, primary_key=True, default=new_uuid)
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    hourly_period_start = Column(String, nullable=False)
    hourly_period_end = Column(String, nullable=False)
    bonus_period_start = Column(String, nullable=False)
    bonus_period_end = Column(String, nullable=False)
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    agency = relationship("Agency")
    agent_payrolls = relationship(
        "AgentPayroll", back_populates="payroll_run", lazy="selectin",
        cascade="all, delete-orphan",
    )


class AgentPayroll(Base):
    __tablename__ = "agent_payrolls"

    id = Column(String, primary_key=True, default=new_uuid)
    payroll_run_id = Column(String, ForeignKey("payroll_runs.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    agent_name = Column(String, default="")
    hourly_rate = Column(Float, default=0.0)
    hours_worked = Column(Float, default=0.0)
    hourly_pay = Column(Float, default=0.0)
    deal_count = Column(Integer, default=0)
    total_premium = Column(Float, default=0.0)
    avg_premium = Column(Float, default=0.0)
    production_bonus = Column(Float, default=0.0)
    effectuation_bonus = Column(Float, default=0.0)
    chargebacks = Column(Float, default=0.0)
    total_pay = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)

    payroll_run = relationship("PayrollRun", back_populates="agent_payrolls")
    user = relationship("User")
    deal_records = relationship(
        "PayrollDealRecord", back_populates="agent_payroll", lazy="selectin",
        cascade="all, delete-orphan",
    )


class PayrollDealRecord(Base):
    __tablename__ = "payroll_deal_records"

    id = Column(String, primary_key=True, default=new_uuid)
    agent_payroll_id = Column(String, ForeignKey("agent_payrolls.id"), nullable=False)
    ghl_contact_id = Column(String, nullable=False)
    contact_name = Column(String, default="")
    agent_name = Column(String, default="")
    premium = Column(Float, default=0.0)
    bonus_type = Column(String, default="production")
    bonus_amount = Column(Float, default=0.0)
    date_added = Column(String, default="")
    policy_effective_date = Column(String, default="")
    premium_draft_date = Column(String, default="")
    policy_number = Column(String, default="")
    plan_name = Column(String, default="")
    status = Column(String, default="paid")
    source_period = Column(String, default="current")
    created_at = Column(DateTime, default=utcnow)

    agent_payroll = relationship("AgentPayroll", back_populates="deal_records")


class SubmissionAgent(Base):
    """Agent names that appear in the deal submission form dropdown.

    Completely separate from the User table — managed manually by the
    agency admin via the Submission Agents admin section.
    """
    __tablename__ = "submission_agents"

    id = Column(String, primary_key=True, default=new_uuid)
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    name = Column(String, nullable=False)  # stored ALL CAPS
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    agency = relationship("Agency")


class CommissionRecord(Base):
    __tablename__ = "commission_records"

    id = Column(String, primary_key=True, default=new_uuid)
    agency_id = Column(String, ForeignKey("agencies.id"), nullable=False)
    sync_log_id = Column(String, ForeignKey("sync_logs.id"), nullable=True)
    policy_number = Column(String, nullable=False, index=True)
    ghl_contact_id = Column(String, default="")

    agent_nbr = Column(String, default="")
    agent_first_name = Column(String, default="")
    agent_last_name = Column(String, default="")
    agent_name_full = Column(String, default="")
    insured_name = Column(String, default="")

    trans_type = Column(String, default="")
    plan_code = Column(String, default="")

    prem_paid_amt = Column(Float, default=0.0)
    monthly_premium = Column(Float, default=0.0)
    comm_rate = Column(Float, default=0.0)
    comm_prem_amt = Column(Float, default=0.0)
    adv_per = Column(Float, default=0.0)
    advance_amount = Column(Float, default=0.0)

    effective_date = Column(String, default="")
    paid_to_date = Column(String, default="")
    last_activity_date = Column(String, default="")

    status = Column(String, default="active")
    chargeback_amount = Column(Float, default=0.0)
    chargeback_date = Column(String, default="")
    months_active = Column(Float, default=0.0)
    earned_commission = Column(Float, default=0.0)
    net_owed = Column(Float, default=0.0)

    paid_to_agent = Column(Boolean, default=False)
    paid_to_agent_date = Column(String, default="")
    payroll_run_id = Column(String, ForeignKey("payroll_runs.id"), nullable=True)

    mc_comm_amt = Column(Float, default=0.0)
    mc_retained_recovery = Column(Float, default=0.0)
    mc_comm_amt_due = Column(Float, default=0.0)
    mc_code = Column(String, default="")
    mc_trans_type = Column(String, default="")
    statement_source = Column(String, default="")
    issue_state = Column(String, default="")
    policy_form = Column(String, default="")
    remaining_balance = Column(Float, default=0.0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    agency = relationship("Agency")
