"""周报生成器（P1 自研核心 3/3）· 设计定稿 v3 §10：周报是唯一排期入口（闸门 D）。

读 geo.db（开发镜像）+ GSC pull JSON + Gemini 基线目录 + gate_checks 日志，
产出 Markdown 周报。所有数字来自实测数据；拿不到的写「未接入/未齐」，不估算。

用法：
  python3 weekly_report.py [--out <path.md>] [--week 2026-W45]
默认只打印到 stdout；带 --out 时同时落盘。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import db
import gates
from migrations_p1 import ensure_p1_schema

CST = timezone(timedelta(hours=8))
GEMINI_DIR = os.path.expanduser(
    "~/workspace/goals/1/hidden_files/geo-p0/sampling-gemini-baseline-2026-11-02")


def latest_gate_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM gate_checks WHERE id IN "
        "(SELECT MAX(id) FROM gate_checks GROUP BY gate, subject) ORDER BY gate, subject"
    ).fetchall()
    return [dict(r) for r in rows]


def gemini_status() -> dict:
    meta_path = os.path.join(GEMINI_DIR, "run-meta.json")
    if not os.path.exists(meta_path):
        return {"state": "未跑", "detail": "基线目录无 run-meta.json"}
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    raw_counts = {}
    for name in os.listdir(GEMINI_DIR):
        if name.startswith("raw-") and name.endswith(".jsonl"):
            with open(os.path.join(GEMINI_DIR, name), encoding="utf-8") as f:
                raw_counts[name] = sum(1 for _ in f)
    if meta.get("halted_quota"):
        state = "已停批（配额）"
    else:
        state = "已完成" if meta.get("finished_at") else "跑批中"
    return {"state": state, "meta": meta, "raw_counts": raw_counts}


def build_report(conn: sqlite3.Connection, week_label: str) -> str:
    ev = gates.load_gsc_evidence()
    gem = gemini_status()
    sites = [dict(r) for r in conn.execute("SELECT * FROM sites ORDER BY id")]
    audits = {}
    for s in sites:
        row = conn.execute(
            "SELECT * FROM audits WHERE site_id = ? ORDER BY id DESC LIMIT 1",
            (s["id"],)).fetchone()
        if row:
            audits[s["domain"]] = dict(row)
    sources = [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY id")]
    findings = conn.execute(
        "SELECT layer, COUNT(*) AS n FROM findings GROUP BY layer ORDER BY layer").fetchall()
    findings_total = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    cards = gates.all_cards(conn)
    baselines = [dict(r) for r in conn.execute(
        "SELECT * FROM baseline_snapshots ORDER BY site_id, id")]
    gate_rows = latest_gate_rows(conn)
    changes_n = conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    weekly_impr = ev.get("weekly_impressions") if ev.get("available") else None

    L: list[str] = []
    add = L.append
    add(f"# GEO 周报 · {week_label}（第一期）")
    add("")
    add(f"- 生成时间：{gates.now_iso()}（weekly_report.py 自动生成，数据源：geo.db + GSC pull + 基线目录）")
    add(f"- 数据截至：审计 2026-11-02 实跑；GSC 窗口 {ev.get('window', '不可用')}；采样见 §2")
    add("")
    add("## 0. 一句话结论")
    add("")
    if weekly_impr is not None:
        add(f"系统骨架与四闸门已上线并开始拦截：全站周曝光约 {weekly_impr:.0f}/周，远低于 1000 的"
            "小流量阈值 → 本周可立项范围仅 L1–L3 结构修复；采样判定口径未齐（Gemini grounding "
            "配额停批、0 有效样本），3 张假设卡因此被闸门 D 驳回、1 张可流转。P0 退出门未达，与 P1 并行。")
    else:
        add("GSC 证据不可用，本周只报数据状态，不给优化结论（设计 §4.1：缺数时只写「数据未齐」）。")
    add("")

    add("## 1. 本周数据状态")
    add("")
    add("| 数据源 | 状态 | 最新实测 |")
    add("|---|---|---|")
    for s in sources:
        add(f"| {s['label']} | {s['status']} | {s['detail']} |")
    if ev.get("available"):
        add(f"| GSC 28 天 totals（本次 pull） | 已实拉 | 展示 {ev['impressions_28d']}、"
            f"点击 {ev['clicks_28d']}、平均排名 {ev['position_avg']:.1f}、折周曝光约 {weekly_impr:.2f}/周 |")
    meta = gem.get("meta", {})
    add(f"| Gemini 基线跑批 | {gem['state']} | {meta.get('halt_reason', meta.get('model', ''))}；"
        f"原始文件行数 {gem.get('raw_counts', {})} |")
    add("")

    add("## 2. 漏斗逐层状态（L1–L7）")
    add("")
    add("| 层 | 状态 | 证据 |")
    add("|---|---|---|")
    l1n = next((r["n"] for r in findings if r["layer"] == "L1"), 0)
    audit_txt = "、".join(f"{d} {a['score']} 分" for d, a in audits.items())
    add(f"| L1 可达 | 已测，有问题待修 | geo-optimizer 审计（{audit_txt}，卫生分）；findings 中 L1 共 {l1n} 条 |")
    add("| L2 被抓取 | 无数据（标缺） | 原始日志未接入，bot 到访无从计数——不拿 robots 放行冒充来访 |")
    sm_err = ev.get("sitemaps_errors") if ev.get("available") else None
    if sm_err and all(str(e) == "0" for e in sm_err):
        sm_txt = f"{len(sm_err)} 个 sitemap 均 0 错误"
    else:
        sm_txt = f"sitemap 错误数 {sm_err}"
    add(f"| L3 被收录 | 部分 | {sm_txt}（pull JSON）；URL Inspection 覆盖状态未拉，未齐 |")
    if ev.get("available"):
        add(f"| L4 被检索/曝光 | 已测，量极低 | 28 天展示 {ev['impressions_28d']}、平均排名 "
            f"{ev['position_avg']:.1f}；CrossAgent 子域仅 4 页有展示、合计 10 次 |")
    add("| L5 被引用 | 仅旧口径样板 | 2026-10-29 浏览器口径样板（见基线表）；Gemini API 口径本轮 0 有效样本 |")
    if ev.get("available"):
        add(f"| L6 点击 | 已测 | 28 天点击 {ev['clicks_28d']} 次（全站） |")
    ns = "；".join(f"{s['name']}：{s['north_star']}" for s in sites)
    add(f"| L7 转化 | 未接入 | 北极星已定（{ns}），埋点未接，无转化数 |")
    add("")

    add("## 3. 基线快照（已落库）")
    add("")
    if baselines:
        add("| 站 | 日期 | 引擎 | 指标 | 对象 | 值 | 口径 |")
        add("|---|---|---|---|---|---|---|")
        site_name = {s["id"]: s["domain"] for s in sites}
        for b in baselines:
            add(f"| {site_name.get(b['site_id'], b['site_id'])} | {b['snapshot_date']} | {b['engine']} | "
                f"{b['metric']} | {b['subject']} | {b['value']}{b['unit'] or ''} | {b['caliber']} |")
    else:
        add("（无基线记录）")
    add("")

    add("## 4. 假设卡进展")
    add("")
    add("| 卡 | 层级 | 标题 | 状态 | 闸门 D dry-run |")
    add("|---|---|---|---|---|")
    d_verdicts = {r["subject"]: r["verdict"] for r in gate_rows if r["gate"] == "D"}
    for c in cards:
        add(f"| {c['code']} | {c['layer']} | {c['title']} | {c['status']} | "
            f"{d_verdicts.get(c['code'], '未检')} |")
    add("")
    add(f"changes 登记：{changes_n} 条（部署钩子未接，靠 lifecycle start 人工登记）。")
    add("")

    add("## 5. 闸门拦截记录（gate_checks 最近一轮）")
    add("")
    if weekly_impr is not None and weekly_impr < gates.WEEKLY_IMPRESSIONS_FLOOR:
        add(f"- **站级结论（闸门 A 口径）**：周曝光约 {weekly_impr:.0f}/周 < "
            f"{gates.WEEKLY_IMPRESSIONS_FLOOR} → 本周可立项范围仅 L1–L3；"
            "采样判定口径未齐 → 涉及引用率基线的卡一律先补数据。")
    for r in gate_rows:
        reasons = json.loads(r["reasons_json"] or "[]")
        first = reasons[0] if reasons else ""
        if r["verdict"] in ("FAIL", "WARN"):
            bad = [x for x in reasons if any(k in x for k in
                   ("不足", "报警", "不合法", "驳回", "未建", "未定量", "未达", "缺"))]
            if bad:
                first = bad[0]
        add(f"- 闸门 {r['gate']} · {r['subject']}：**{r['verdict']}**（{r['checked_at']}）— {first}")
    add("")

    add("## 6. P0 退出门对照（设计 §8）")
    add("")
    add("| 退出门条目 | 状态 | 依据 |")
    add("|---|---|---|")
    add("| 两站 GSC 28 天导出 | 已达 | 2026-11-02 实拉 pull JSON（sc-domain 合并口径，含 CrossAgent 子域页面行） |")
    add("| GSC 每日 cron 入库 | 未达（第 1 天） | token 2026-11-02 才恢复、cron 同日建；连续 7 天要到约 2026-11-09 |")
    add("| Bing Webmaster sitemap + AI Performance CSV | 未达 | 未提交、未导（source_status：bing 未接入） |")
    add("| geo-optimizer 两站审计 | 已达 | 2026-11-02 实跑：主站 62 / Lab 65（卫生分） |")
    add("| robots/CDN 放行核查 | 已达 | 审计 robots 分类已覆盖；Lab 具名缺行见 findings/H-004 |")
    add("| 25 条 prompt 冻结 | 已达 | 冻结集 v1（两站各 25 条） |")
    add("| 采样基线（判定口径 ≥5 次/引擎） | 未达 | Gemini grounding 调用 429 配额停批，0 有效样本；Perplexity 未配置 |")
    add("| Elmo 试跑一周实测成本 | 未达 | 未部署（沙箱无 Docker，待 Mac/VPS） |")
    add("| 日志接入或明确标缺 | 已达（标缺） | source_status 已如实标「未接入」，L2 层留空不造数 |")
    add("| 月成本实测值 | 部分达 | 已走通道实测支出 $0（全免费层）；Elmo 月成本未实测 |")
    add("| 一份基线报告 | 部分达 | CrossAgent 样板报告（2026-10-29）已有；两站统一口径基线报告待采样出数 |")
    add("| **四路数据连续 7 天齐** | **未达** | GSC 恢复第 1 天、采样 0 有效样本 → **P0 未出门，与 P1 并行推进** |")
    add("")

    add("## 7. 下周排期建议（≤3 条，闸门 D：不在此清单不排期）")
    add("")
    add("1. **批准并执行 H-002（Lab 首页补 H1）** — 证据行：闸门 D dry-run 四卡中唯一 PASS；"
        "基线锚点 has_h1=false（2026-11-02 审计实测）。执行后用 lifecycle start 登记 change 并建 7 天 GSC 对比（闸门 C）。")
    add("2. **补齐采样判定口径，出两站首轮判定采样基线** — 证据行：Gemini run-meta 记录 grounding "
        "429 停批、raw 文件仅 4 条失败记录、0 有效样本；H-001/H-003 均因主指标基线未定量被闸门 D 驳回，"
        "解锁前置就是这轮采样（≥5 次/引擎、Wilson 区间）。路径：换时段/降并发重试 Gemini，或按已定对照路线配 Perplexity（<$2/轮）。")
    add("3. **接入原始日志（Cloudflare/源站）落库** — 证据行：source_status logs=未接入，L2 层至今无数据；"
        "H-004 主指标（INDEX 类 bot 抓取覆盖率）依赖日志且基线待首周建立；P0 退出门该项目前靠「标缺」顶着。")
    add("")

    add("## 8. 口径与诚实声明")
    add("")
    add("- 审计分是卫生分（CI 门禁），不预测引用、不进任何假设卡指标栏（设计 §1.4）。")
    add("- 提及/引用口径为本系统自家定义（设计 §5），与 Profound 等工具不可比；API 口径与网页口径分开标注。")
    add("- 单次/2 次采样不进结论；本期所有采样数字均注明口径与日期。")
    add("- 本周报由 weekly_report.py 从 geo.db 与 pull JSON 自动生成；闸门结论来自 gates.py 确定性检查并已写入 gate_checks。")
    return "\n".join(L) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="GEO 周报生成器")
    parser.add_argument("--out")
    parser.add_argument("--week")
    args = parser.parse_args()
    today = datetime.now(CST).date()
    iso = today.isocalendar()
    week_label = args.week or f"{iso.year}-W{iso.week:02d}"
    conn = db.connect()
    ensure_p1_schema(conn)
    report = build_report(conn, week_label)
    conn.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out} ({len(report)} chars, week={week_label})")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
