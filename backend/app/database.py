import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ap-insurance.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_column_if_missing(conn, table_name: str, column_name: str, col_type: str, default: str = "''"):
    insp = inspect(conn)
    existing = [c["name"] for c in insp.get_columns(table_name)]
    if column_name not in existing:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col_type} DEFAULT {default}"))
        conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        _add_column_if_missing(conn, "agencies", "ghl_paid_to_agent_field_id", "VARCHAR", "''")
        _add_column_if_missing(conn, "agencies", "ghl_advance_status_field_id", "VARCHAR", "''")
        _add_column_if_missing(conn, "agencies", "ghl_commission_field_ids", "TEXT", "'{}'")
        _add_column_if_missing(conn, "commission_records", "mc_comm_amt", "FLOAT", "0.0")
        _add_column_if_missing(conn, "commission_records", "mc_retained_recovery", "FLOAT", "0.0")
        _add_column_if_missing(conn, "commission_records", "mc_comm_amt_due", "FLOAT", "0.0")
        _add_column_if_missing(conn, "commission_records", "mc_code", "VARCHAR", "''")
        _add_column_if_missing(conn, "commission_records", "mc_trans_type", "VARCHAR", "''")
        _add_column_if_missing(conn, "commission_records", "statement_source", "VARCHAR", "''")
        _add_column_if_missing(conn, "commission_records", "issue_state", "VARCHAR", "''")
        _add_column_if_missing(conn, "commission_records", "policy_form", "VARCHAR", "''")
        _add_column_if_missing(conn, "commission_records", "remaining_balance", "FLOAT", "0.0")
        _add_column_if_missing(conn, "agencies", "calltools_api_key", "VARCHAR", "''")
        _add_column_if_missing(conn, "agencies", "calltools_base_url", "VARCHAR", "'https://west-4.calltools.io/api'")
        _add_column_if_missing(conn, "agencies", "calltools_team_id", "VARCHAR", "''")
        _add_column_if_missing(conn, "users", "must_change_password", "BOOLEAN", "FALSE")
