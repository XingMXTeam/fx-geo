"""P1 迁移（幂等）：为最小闭环补三样东西——

1. hypotheses 状态流转字段（approved_at / running_at / decided_at / decision /
   decision_note / effect / ci_low / ci_high / window_days / expires_at）
2. changes 表（部署变更登记，闸门 C 与 lifecycle start 写这里）
3. gate_checks 表（闸门判定日志，周报的「闸门拦截记录」从这里取）

只做 ADD COLUMN / CREATE TABLE IF NOT EXISTS，不动既有数据与既有列。
Supabase 侧对应 DDL 在 supabase/schema.sql 末尾「P1 增补」节（人工执行）。
"""
import sqlite3

import db

HYPOTHESES_COLUMNS = [
    ("approved_at", "TEXT"),
    ("running_at", "TEXT"),
    ("decided_at", "TEXT"),
    ("decision", "TEXT"),  # promote | extend_one_window | rollback_or_invalid
    ("decision_note", "TEXT"),
    ("effect", "REAL"),  # 到期实测效果（与主指标同口径，如百分点）
    ("ci_low", "REAL"),
    ("ci_high", "REAL"),
    ("window_days", "INTEGER DEFAULT 28"),
    ("expires_at", "TEXT"),
]

DDL = """
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    hypothesis_id INTEGER REFERENCES hypotheses(id),
    deployed_at TEXT NOT NULL,
    commit_sha TEXT,
    urls TEXT,
    change_type TEXT,
    description TEXT,
    gsc_comparison_started INTEGER NOT NULL DEFAULT 0,
    gsc_comparison_note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS gate_checks (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    gate TEXT NOT NULL,
    subject TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reasons_json TEXT,
    source TEXT
);
"""


def ensure_p1_schema(conn: sqlite3.Connection) -> list[str]:
    """执行迁移，返回本次实际发生的变更说明（已迁移过则返回空列表）。"""
    done = []
    existing = {row[1] for row in conn.execute("PRAGMA table_info(hypotheses)")}
    for name, typ in HYPOTHESES_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE hypotheses ADD COLUMN {name} {typ}")
            done.append(f"hypotheses.+{name}")
    before = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.executescript(DDL)
    after = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in sorted(after - before):
        done.append(f"table:{t}")
    conn.commit()
    return done


def main():
    conn = db.connect()
    done = ensure_p1_schema(conn)
    conn.close()
    print("P1 migration applied:", done if done else "already up to date")


if __name__ == "__main__":
    main()
