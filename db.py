"""GEO 闭环系统 MVP · 数据层（SQLite，schema 按 v3 定稿 §6.1 简化，后续可迁 Postgres）"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY,
    domain TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT,
    north_star TEXT
);
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id),
    set_version TEXT NOT NULL,
    category TEXT NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    target_url TEXT
);
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id),
    run_at TEXT,
    score INTEGER,
    band TEXT,
    breakdown_json TEXT,
    priorities_json TEXT,
    failures_json TEXT,
    source_file TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS baseline_snapshots (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id),
    snapshot_date TEXT NOT NULL,
    engine TEXT NOT NULL,
    metric TEXT NOT NULL,
    subject TEXT NOT NULL,
    value REAL,
    unit TEXT,
    caliber TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    site_id INTEGER REFERENCES sites(id),
    scope TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    layer TEXT NOT NULL,
    hypothesis TEXT,
    primary_metric TEXT,
    baseline_value TEXT,
    target TEXT,
    guardrail TEXT,
    threshold TEXT,
    control_group TEXT,
    cost TEXT,
    stop_condition TEXT,
    hygiene_note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    site_id INTEGER REFERENCES sites(id),
    scope TEXT,
    layer TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence TEXT,
    detail TEXT,
    severity TEXT DEFAULT 'normal',
    source TEXT
);
CREATE TABLE IF NOT EXISTS source_status (
    id INTEGER PRIMARY KEY,
    source TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    next_step TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    statement TEXT NOT NULL,
    evidence_level TEXT,
    source TEXT
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("db initialized:", DB_PATH)
