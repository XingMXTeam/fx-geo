"""假设卡状态机（P1 自研核心 2/3）· 设计定稿 v3 §4.3 / §4.6

流转：draft → approved（必须过闸门 D）→ running（登记 changes）→ decided
decided 的决定规则（§4.6 的确定性版）：
  effect 达阈值且 CI 不跨 0（ci_low > 0）        → promote
  effect > 0 但不显著 / 未达阈值                 → extend_one_window（只许延长一个窗口）
  effect ≤ 0                                     → rollback_or_invalid
decided=rollback_or_invalid 的同类卡（同 layer + 同 scope），30 天内再批准要报警。

用法（默认 check = dry-run，只读不流转）：
  python3 lifecycle.py check [--code H-001]
  python3 lifecycle.py approve --code H-002
  python3 lifecycle.py start --code H-002 --commit <sha> --urls <url,url> \
      --type structure --description "补 H1" [--gsc-comparison]
  python3 lifecycle.py decide --code H-002 --effect 12.5 --ci-low 2.0 --ci-high 23.0 [--note "..."]
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import db
import gates
from migrations_p1 import ensure_p1_schema

CST = timezone(timedelta(hours=8))
COOLING_DAYS = 30


def now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M CST")


def today() -> datetime:
    return datetime.now(CST)


def parse_threshold_number(threshold: str | None) -> float | None:
    """从阈值文本里抽第一个数字（如「+5 个百分点」→ 5.0、「≥20」→ 20.0）。抽不到返回 None。"""
    if not threshold:
        return None
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(个百分点|%|pp)", threshold)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:≥|>=|提升|达到)\s*([+-]?\d+(?:\.\d+)?)", threshold)
    return float(m.group(1)) if m else None


def decide_rule(effect: float, ci_low: float, ci_high: float,
                threshold: str | None) -> tuple[str, str]:
    """到期决定规则。返回 (decision, 理由)。"""
    thr = parse_threshold_number(threshold)
    if effect <= 0:
        return "rollback_or_invalid", f"effect={effect} ≤ 0 → 回滚或记无效结论，30 天冷却（设计 §4.6）。"
    significant = ci_low > 0
    meets = (thr is None) or (effect >= thr)
    if significant and meets:
        return "promote", (f"effect={effect} 达阈值（{thr if thr is not None else '阈值未量化，按显著性判'}）"
                           f"且 CI [{ci_low}, {ci_high}] 不跨 0 → 推广：新开卡、换基线。")
    why = []
    if not significant:
        why.append(f"CI [{ci_low}, {ci_high}] 跨 0，不显著")
    if not meets:
        why.append(f"effect={effect} 未达阈值 {thr}")
    return "extend_one_window", "effect 为正但" + "；".join(why) + " → 只许延长一个窗口。"


def cooling_warnings(conn: sqlite3.Connection, card: dict) -> list[str]:
    """同 layer+scope 在 30 天内有 rollback_or_invalid 的 decided 卡 → 报警。"""
    since = (today() - timedelta(days=COOLING_DAYS)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT code, decided_at FROM hypotheses WHERE layer = ? AND scope IS ? "
        "AND status = 'decided' AND decision = 'rollback_or_invalid' "
        "AND decided_at >= ? AND code != ?",
        (card.get("layer"), card.get("scope"), since, card.get("code"))).fetchall()
    return [f"冷却期报警：同类卡 {r['code']}（{r['decided_at']} 判 rollback_or_invalid）"
            f"在 {COOLING_DAYS} 天内，同 layer+scope 再立项须人工确认。" for r in rows]


def cmd_check(conn: sqlite3.Connection, code: str | None) -> int:
    evidence = gates.load_gsc_evidence()
    cards = [gates.get_card(conn, code)] if code else gates.all_cards(conn, "draft")
    cards = [c for c in cards if c]
    if not cards:
        print("没有待检的 draft 卡。")
        return 0
    print(f"== lifecycle check（dry-run，只读，不流转任何卡）· {now_iso()} ==")
    rc = 0
    for card in cards:
        verdict, reasons = gates.gate_d(card, conn, evidence)
        gates.log_check(conn, "D", card["code"], verdict, reasons, source="lifecycle.py check")
        print(f"\n[{verdict}] {card['code']} · {card['title']}（{card['layer']} / {card.get('scope')}）")
        for r in reasons:
            print(f"    - {r}")
        for w in cooling_warnings(conn, card):
            print(f"    ⚠ {w}")
        missing = []
        if verdict != "PASS":
            fails_only = [r for r in reasons if r.startswith("✗")]
            if any("基线未定量" in r for r in fails_only):
                missing.append("主指标基线定量（先补判定采样/日志数据）")
            if any("时间窗口" in r for r in fails_only):
                missing.append("假设文本补时间窗口（如 28 天）")
            if any("字段不完整" in r for r in fails_only):
                missing.append("补齐缺失字段")
            if any("审计分" in r for r in fails_only):
                missing.append("主指标换成结果类指标（不得用审计分）")
            if any("闸门 A 冲突" in r for r in fails_only):
                missing.append("先过闸门 A（结构层未通前不立下游实验）")
            print(f"    → 结论：留在 draft；缺：{'；'.join(missing) if missing else '见上'}")
            rc = 1
        else:
            print("    → 结论：可流转（本次仅 dry-run，未执行 approve；等 L1 修复线单独登记）。")
    return rc


def cmd_approve(conn: sqlite3.Connection, code: str) -> int:
    card = gates.get_card(conn, code)
    if not card:
        print(f"找不到假设卡 {code}")
        return 2
    if card["status"] != "draft":
        print(f"{code} 当前状态 {card['status']}，只有 draft 可 approve。")
        return 2
    for w in cooling_warnings(conn, card):
        print(f"⚠ {w}（已报警，仍继续走闸门 D；如属同类重立项请人工确认后再执行）")
    verdict, reasons = gates.gate_d(card, conn, gates.load_gsc_evidence())
    gates.log_check(conn, "D", code, verdict, reasons, source="lifecycle.py approve")
    for r in reasons:
        print(f"    - {r}")
    if verdict != "PASS":
        print(f"[{verdict}] {code} 未过闸门 D，保持 draft。")
        return 1
    conn.execute("UPDATE hypotheses SET status = 'approved', approved_at = ? WHERE code = ?",
                 (now_iso(), code))
    conn.commit()
    print(f"[PASS] {code} 已流转 draft → approved（{now_iso()}）。")
    return 0


def cmd_start(conn: sqlite3.Connection, args) -> int:
    card = gates.get_card(conn, args.code)
    if not card:
        print(f"找不到假设卡 {args.code}")
        return 2
    if card["status"] != "approved":
        print(f"{args.code} 当前状态 {card['status']}，只有 approved 可 start。")
        return 2
    deployed = now_iso()
    cur = conn.execute(
        "INSERT INTO changes (hypothesis_id, deployed_at, commit_sha, urls, change_type,"
        " description, gsc_comparison_started, gsc_comparison_note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (card["id"], deployed, args.commit, args.urls, args.type, args.description,
         1 if args.gsc_comparison else 0,
         "已建 GSC 每日对比（冻结窗 7 天）" if args.gsc_comparison else None, deployed))
    window = card.get("window_days") or 28
    expires = (today() + timedelta(days=window)).strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE hypotheses SET status = 'running', running_at = ?, expires_at = ? WHERE code = ?",
        (deployed, expires, args.code))
    conn.commit()
    print(f"{args.code} 已流转 approved → running；changes#{cur.lastrowid} 已登记"
          f"（commit={args.commit}，type={args.type}，GSC 对比={'已建' if args.gsc_comparison else '未建——闸门 C 将提醒'}）；"
          f"实验窗口 {window} 天，到期 {expires}。")
    return 0


def cmd_decide(conn: sqlite3.Connection, args) -> int:
    card = gates.get_card(conn, args.code)
    if not card:
        print(f"找不到假设卡 {args.code}")
        return 2
    if card["status"] != "running":
        print(f"{args.code} 当前状态 {card['status']}，只有 running 可 decide。")
        return 2
    if card.get("expires_at") and today().strftime("%Y-%m-%d") < card["expires_at"] and not args.force:
        print(f"{args.code} 未到期（expires_at={card['expires_at']}），decide 需 --force 才可提前判。")
        return 2
    decision, why = decide_rule(args.effect, args.ci_low, args.ci_high, card.get("threshold"))
    conn.execute(
        "UPDATE hypotheses SET status = 'decided', decided_at = ?, decision = ?,"
        " decision_note = ?, effect = ?, ci_low = ?, ci_high = ? WHERE code = ?",
        (now_iso(), decision, (args.note or "") + " " + why, args.effect,
         args.ci_low, args.ci_high, args.code))
    conn.commit()
    print(f"{args.code} 已判 decided → {decision}：{why}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="假设卡状态机（默认 check 为 dry-run）")
    sub = parser.add_subparsers(dest="cmd")
    p_check = sub.add_parser("check", help="dry-run：逐卡过闸门 D，不流转")
    p_check.add_argument("--code")
    p_app = sub.add_parser("approve", help="过闸门 D 后 draft → approved")
    p_app.add_argument("--code", required=True)
    p_start = sub.add_parser("start", help="登记 change 并 approved → running")
    p_start.add_argument("--code", required=True)
    p_start.add_argument("--commit", required=True)
    p_start.add_argument("--urls", default="")
    p_start.add_argument("--type", default="structure")
    p_start.add_argument("--description", default="")
    p_start.add_argument("--gsc-comparison", action="store_true")
    p_dec = sub.add_parser("decide", help="到期判定 running → decided")
    p_dec.add_argument("--code", required=True)
    p_dec.add_argument("--effect", type=float, required=True)
    p_dec.add_argument("--ci-low", type=float, required=True)
    p_dec.add_argument("--ci-high", type=float, required=True)
    p_dec.add_argument("--note", default="")
    p_dec.add_argument("--force", action="store_true")
    args = parser.parse_args(argv[1:] or ["check"])

    conn = db.connect()
    ensure_p1_schema(conn)
    try:
        if args.cmd in (None, "check"):
            return cmd_check(conn, getattr(args, "code", None))
        if args.cmd == "approve":
            return cmd_approve(conn, args.code)
        if args.cmd == "start":
            return cmd_start(conn, args)
        if args.cmd == "decide":
            return cmd_decide(conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
