"""Mock CRM (SQLite): leads with call summaries, callbacks, escalations (+ optional outbound webhook), DNC list,
and seeded customer accounts for the reminder packs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(os.getenv("CRM_DB", Path(__file__).parent / "data" / "crm.sqlite3"))
_lock = threading.Lock()

SCHEMA = """
create table if not exists leads (id text primary key, call_id text, room text, pack text, grade text, outcome text,
  product text, premium_inr integer, fields text, summary text, created_at real);
create table if not exists callbacks (id text primary key, call_id text, pack text, when_text text, reason text,
  status text, created_at real);
create table if not exists escalations (id text primary key, call_id text, room text, pack text, reason text,
  summary text, status text, webhook_status text, created_at real);
create table if not exists dnc (phone text, call_id text, pack text, created_at real);
create table if not exists customers (id text primary key, pack text, data text);
"""

# Fictional accounts; due dates are relative to today so pre-due reminder demos never go stale.
SEED_CUSTOMERS = [
    ("ph-001", "ph_life", {"name": "Jose Santos", "title": "Sir", "policy_no": "BL-2023-004512",
                           "product": "Bayanihan FamilyCare Life", "face_amount_php": 1000000, "premium_php": 5550,
                           "mode": "quarterly", "due_in_days": 14, "riders": ["Accidental Death Benefit"],
                           "dob": "1989-03-12", "bank": "Kalayaan Savings Bank", "beneficiary": "Maria Santos (spouse)"}),
    ("id-001", "id_multifinance", {"name": "Budi Santoso", "title": "Bapak", "contract_no": "MBF-MTR-2025-11873",
                                   "vehicle": "Honda Beat 2025", "installment_idr": 1250000, "tenor_months": 24,
                                   "paid_installments": 7, "due_in_days": 9, "late_fee_pct_per_day": 0.2, "branch": "Semarang"}),
]


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        for cid, pack, data in SEED_CUSTOMERS:
            c.execute("insert or replace into customers values (?,?,?)", (cid, pack, json.dumps(data)))


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def insert(table: str, row: dict) -> dict:
    row = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
    cols = ",".join(row)
    with _lock, _conn() as c:
        c.execute(f"insert into {table} ({cols}) values ({','.join('?' * len(row))})", list(row.values()))
    return row


def rows(table: str, limit: int = 100) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(f"select * from {table} order by rowid desc limit ?", (limit,))]


def new_lead(data: dict) -> dict:
    return insert("leads", {"id": _id("lead"), "created_at": time.time(), **data})


def new_callback(data: dict) -> dict:
    return insert("callbacks", {"id": _id("cb"), "status": "scheduled", "created_at": time.time(), **data})


def new_escalation(data: dict) -> dict:
    return insert("escalations", {"id": _id("esc"), "status": "open", "created_at": time.time(), **data})


def add_dnc(data: dict) -> dict:
    return insert("dnc", {"created_at": time.time(), **data})


def customer(cid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("select data from customers where id=?", (cid,)).fetchone()
    if not r:
        return None
    data = json.loads(r["data"])
    if "due_in_days" in data:
        data["due_date"] = (date.today() + timedelta(days=int(data["due_in_days"]))).isoformat()
    return data
