import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

from app.database import init_db, SessionLocal
from app.models import Agency, User
from app.auth import hash_password
from app.routers import auth_router, agencies, leaderboard, deals, payroll, commission_sync, agent_portal, deal_submission, submission_agents


def seed_super_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.role == "super_admin").first()
        if existing:
            return

        admin_email = os.getenv("SUPER_ADMIN_EMAIL", "admin@ap-insurance-app.com")
        admin_password = os.getenv("SUPER_ADMIN_PASSWORD", "apinsurance2026!")

        default_hourly_tiers = json.dumps([
            {"min_policies": 10, "min_avg_premium": 30, "max_avg_premium": 33, "rate": 16.0},
            {"min_policies": 10, "min_avg_premium": 34, "max_avg_premium": 36, "rate": 18.0},
            {"min_policies": 10, "min_avg_premium": 37, "max_avg_premium": 39, "rate": 20.0},
            {"min_policies": 10, "min_avg_premium": 40, "max_avg_premium": 99999, "rate": 22.0},
        ])
        default_chargeback_tiers = json.dumps([
            {"min_premium": 75, "max_premium": 99999, "window_days": 60},
            {"min_premium": 35, "max_premium": 74.99, "window_days": 90},
            {"min_premium": 0, "max_premium": 34.99, "window_days": 120},
        ])

        adv_field = os.getenv("GHL_ADVANCE_STATUS_FIELD_ID", "")

        agency = db.query(Agency).filter(Agency.code == "APINSURANCE").first()
        if not agency:
            agency = Agency(
                code="APINSURANCE",
                name="AP Insurance Partners",
                slug="ap-insurance",
                ghl_api_key=os.getenv("GHL_API_KEY", ""),
                ghl_location_id=os.getenv("GHL_LOCATION_ID", ""),
                ghl_agent_field_id=os.getenv("GHL_AGENT_FIELD_ID", ""),
                ghl_premium_field_id=os.getenv("GHL_PREMIUM_FIELD_ID", ""),
                ghl_advance_status_field_id=adv_field,
                hourly_tiers=default_hourly_tiers,
                chargeback_tiers=default_chargeback_tiers,
            )
            db.add(agency)
            db.commit()
            db.refresh(agency)
        elif adv_field and not agency.ghl_advance_status_field_id:
            agency.ghl_advance_status_field_id = adv_field
            db.commit()
            db.refresh(agency)

        admin_user = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            role="super_admin",
            agency_id=agency.id,
            agent_name="Admin",
        )
        db.add(admin_user)
        db.commit()
        print(f"Super admin seeded: {admin_email}")
    finally:
        db.close()


async def _billable_refresh_loop() -> None:
    """Run the CallTools billable-hours refresh once at startup, then every hour."""
    from app.routers.agent_portal import refresh_billable_cache_for_all_agencies

    # Initial refresh shortly after startup (give DB time to be ready)
    await asyncio.sleep(10)
    logger.info("Background: initial billable cache refresh starting")
    try:
        await refresh_billable_cache_for_all_agencies()
        logger.info("Background: initial billable cache refresh complete")
    except Exception as exc:
        logger.error("Background: initial refresh failed: %s", exc)

    # Then refresh every hour
    while True:
        await asyncio.sleep(3600)
        logger.info("Background: hourly billable cache refresh starting")
        try:
            await refresh_billable_cache_for_all_agencies()
            logger.info("Background: hourly billable cache refresh complete")
        except Exception as exc:
            logger.error("Background: hourly refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    seed_super_admin()
    # Start background task to pre-compute billable hours every hour
    task = asyncio.create_task(_billable_refresh_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="AP Insurance Partners Portal", version="0.1.0", lifespan=lifespan)

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(agencies.router)
app.include_router(leaderboard.router)
app.include_router(deals.router)
app.include_router(payroll.router)
app.include_router(commission_sync.router)
app.include_router(agent_portal.router)
app.include_router(deal_submission.router)
app.include_router(submission_agents.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": "2026-03-20-v2"}
