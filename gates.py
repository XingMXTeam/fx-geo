"""闸门引擎（P1 自研核心 1/3）· 设计定稿 v3 §4.4

四道闸门全部做成确定性检查：同样的输入永远给同样的 PASS/FAIL + 逐条理由，
不调 LLM、不猜。每次判定写 gate_checks 表，周报从那里取拦截记录。

  A · Retrieval-First   未过 L2–L4 的页面禁开改写工单，只许 L1–L3 结构修复
  B · 证据密度 Linter   发布前查证据单元密度 / 引用 URL 合法性 / 关键词堆砌
  C · 变更冻结窗        近 7 天 URL/重定向/模板级变更清单 + GSC 对比是否已建
  D · 立项门            假设卡 draft → approved 的字段与口径校验（lifecycle 调用）

用法：
  python3 gates.py a [--code H-001] [--demo-rewrite]   # 闸门 A（默认跑全部 draft 卡）
  python3 gates.py b <file.html|file.md> [...]         # 闸门 B
  python3 gates.py c                                   # 闸门 C
  python3 gates.py d [--code H-001]                    # 闸门 D（与 lifecycle check 同源）
  python3 gates.py all                                 # A+B(样本)+C+D 一次跑完
可 import：gate_a(card, evidence) / gate_b(path) / gate_c(conn) / gate_d(card, conn)
"""
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import db
from migrations_p1 import ensure_p1_schema

CST = timezone(timedelta(hours=8))
GSC_PULL = os.path.expanduser(
    "~/workspace/goals/1/hidden_files/geo-p0/gsc-2026-11-02/pull-2026-11-02.json")
# 设计 §3 小流量规则：周曝光 < 约 1000 的站只做 L1–L3
WEEKLY_IMPRESSIONS_FLOOR = 1000

REWRITE_KEYWORDS = ("改写", "重写", "改稿", "润色", "扩写", "内容生成", "正文改")
STRUCTURE_LAYERS = {"L1", "L2", "L3"}
DOWNSTREAM_LAYERS = {"L5", "L6", "L7"}
# 基线「未定量」表述：出现即说明主指标基线还没落数（设计 §4.3 填不出基线值 → 驳回）
FUTURE_BASELINE_PATTERNS = [
    r"基线未建", r"尚无[^。；]*基线", r"待[^。；]*建立", r"待[^。；]*首周建立",
    r"首轮[^。；]*为基线", r"接入后[^。；]*基线", r"未建[^。；]*基线",
]
AUDIT_METRIC_PATTERN = re.compile(r"审计[^，。；]*?(分|score|评分)|audit\s*score", re.I)


def now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M CST")


# ---------------------------------------------------------------- 证据装载
def load_gsc_evidence(path: str = GSC_PULL) -> dict:
    """从 GSC pull JSON 拼闸门用的证据。文件缺失时返回 unknown，不假装有数据。"""
    if not os.path.exists(path):
        return {"available": False, "reason": f"GSC 证据文件不存在：{path}"}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    totals = (d.get("totals") or [{}])[0]
    days = 28  # pull 窗口固定 28 天（start/end 相差 27 天 + 首尾）
    impressions = totals.get("impressions", 0)
    pages = {}
    for row in d.get("by_page", []) + d.get("crossagent_pages", []):
        if row.get("keys"):
            pages[row["keys"][0]] = row.get("impressions", 0)
    return {
        "available": True,
        "site": d.get("site"),
        "window": f"{d.get('start')} → {d.get('end')}",
        "impressions_28d": impressions,
        "clicks_28d": totals.get("clicks", 0),
        "position_avg": totals.get("position"),
        "weekly_impressions": round(impressions / (days / 7), 2),
        "page_impressions": pages,
        "sitemaps_errors": [s.get("errors") for s in d.get("sitemaps", [])],
    }


def get_card(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT * FROM hypotheses WHERE code = ?", (code,)).fetchone()
    return dict(row) if row else None


def all_cards(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE status = ? ORDER BY code", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM hypotheses ORDER BY code").fetchall()
    return [dict(r) for r in rows]


def log_check(conn, gate: str, subject: str, verdict: str, reasons: list[str],
              source: str = "gates.py"):
    conn.execute(
        "INSERT INTO gate_checks (checked_at, gate, subject, verdict, reasons_json, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (now_iso(), gate, subject, verdict, json.dumps(reasons, ensure_ascii=False), source))
    conn.commit()


# ---------------------------------------------------------------- 闸门 A
def classify_action(card: dict) -> str:
    """把假设卡的动作确定性分成 structure（结构修复）/ rewrite（内容改写）/ downstream。

    口径：层级 L1–L3 且标题/假设不含改写类动词 → structure；
    含改写类动词，或层级在 L5–L7（引用/点击/转化层动作）→ rewrite/downstream，
    这类动作必须先过检索证据检查。L4 单独归 retrieval（曝光层，同样查证据）。
    """
    text = f"{card.get('title', '')} {card.get('hypothesis', '')}"
    layer = (card.get("layer") or "").upper()
    if any(k in text for k in REWRITE_KEYWORDS):
        return "rewrite"
    if layer in STRUCTURE_LAYERS:
        return "structure"
    if layer in DOWNSTREAM_LAYERS:
        return "downstream"
    if layer == "L4":
        return "retrieval"
    return "downstream"


def gate_a(card: dict, evidence: dict) -> tuple[str, list[str]]:
    """Retrieval-First。返回 (PASS|FAIL, 理由列表)。"""
    action = classify_action(card)
    label = f"{card.get('code', '?')}（{card.get('layer')} · {card.get('title', '')}）"
    if action == "structure":
        return "PASS", [
            f"{label}：动作属 {card.get('layer')} 结构修复（非内容改写），"
            "闸门 A 放行——未收录/未曝光页面只许修结构面，正是本卡情形。"]
    reasons = []
    if not evidence.get("available"):
        return "FAIL", [
            f"{label}：动作属「{action}」类，需先证页面已过 L2–L4；"
            f"但 GSC 证据不可用（{evidence.get('reason', '未知')}）——无证据 = 未知 = 不放行。"]
    weekly = evidence["weekly_impressions"]
    if weekly < WEEKLY_IMPRESSIONS_FLOOR:
        reasons.append(
            f"站级证据：{evidence['site']} 近 28 天曝光 {evidence['impressions_28d']} 次，"
            f"折周约 {weekly}/周 < {WEEKLY_IMPRESSIONS_FLOOR}（设计 §3 小流量规则）"
            "→ 全站只许 L1–L3，本卡层级/动作不在放行范围。")
    pages = evidence.get("page_impressions", {})
    scope_hint = card.get("scope") or ""
    hit = {u: n for u, n in pages.items()
           if scope_hint and scope_hint.split()[0].lower() in u.lower()} if scope_hint else {}
    if not hit:
        reasons.append(
            "页面集证据：GSC by_page 中查不到与本卡范围对应的页面曝光行"
            "（无行 = 未被检索到 / 证据未知），按未过 L4 处理。")
    if reasons:
        return "FAIL", [f"{label}：闸门 A 驳回。"] + reasons
    return "PASS", [f"{label}：页面集已有检索曝光证据且站级周曝光 {weekly} ≥ "
                    f"{WEEKLY_IMPRESSIONS_FLOOR}，改写类动作放行。"]


DEMO_REWRITE_CARD = {
    "code": "DEMO-REWRITE", "layer": "L5", "scope": "CrossAgent Lab",
    "title": "（演示卡）对 CrossAgent 首页与案例页做内容改写冲引用率",
    "hypothesis": "若重写 CrossAgent 首页与案例页正文，则引用率在 28 天内提升；机制：文案更贴近 prompt 语义。",
    "primary_metric": "引用率", "site_id": 2,
}


# ---------------------------------------------------------------- 闸门 B
URL_RE = re.compile(r"https?://[^\s\)\]<>\"'，。；]+")
STAT_RE = re.compile(r"\d+(?:\.\d+)?\s*(%|％|倍|万|亿|次|人|条|个|名|家|元|美元|分钟|小时|天|周|月|年|位|分)")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "has", "have", "not", "but", "you", "your", "our", "their", "its", "can",
    "will", "all", "any", "how", "what", "when", "which", "who", "than", "then",
    "into", "over", "under", "about", "there", "these", "those", "been", "being",
}


def _plain_text(raw: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)          # md 图片
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)        # md 链接留文字
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text


def count_chars(text: str) -> int:
    """字数口径：CJK 字符按字计，拉丁词按词计，与设计「每 800–1000 字」对齐。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text))
    return cjk + latin_words


def gate_b(path: str) -> dict:
    """证据密度 Linter。返回结构化结果（verdict + 逐项度量 + 理由）。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    text = _plain_text(raw)
    chars = count_chars(text)
    required_units = max(1, math.ceil(chars / 1000)) if chars else 0

    # 证据单元 = 同一段落内同时出现「带单位的数字统计」与「引用 URL」
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    units = 0
    for p in paragraphs:
        if STAT_RE.search(p) and URL_RE.search(p):
            units += 1
    # 原始 markdown/html 里的链接也算引用（正文被 _plain_text 剥掉 href 时兜底）
    raw_urls = URL_RE.findall(raw)
    valid_urls = [u for u in raw_urls
                  if re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?$", u)]
    invalid_urls = [u for u in raw_urls if u not in valid_urls]

    # 关键词密度：剥 URL 后统计拉丁词（停用词除外），单关键词 >5% 报警
    text_no_url = URL_RE.sub(" ", text)
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text_no_url)]
    content_words = [w for w in words if w not in STOPWORDS]
    top_word, top_share = None, 0.0
    if len(content_words) >= 50:
        from collections import Counter
        top_word, top_n = Counter(content_words).most_common(1)[0]
        top_share = top_n / len(content_words)

    reasons, fails = [], []
    if chars == 0:
        fails.append("文件无可读正文，字数 0。")
    if units < required_units:
        fails.append(
            f"证据密度不足：正文约 {chars} 字，要求 ≥{required_units} 个证据单元"
            f"（每 1000 字 1 个，数字统计+同段引用 URL），实测 {units} 个。")
    else:
        reasons.append(f"证据密度达标：{units} 个证据单元 ≥ 要求 {required_units} 个（约 {chars} 字）。")
    if invalid_urls:
        fails.append(f"引用 URL 格式不合法 {len(invalid_urls)} 条：{invalid_urls[:3]}")
    else:
        reasons.append(f"引用 URL 格式合法：{len(valid_urls)} 条可解析 URL，未发现非法格式。")
    if top_word and top_share > 0.05:
        fails.append(f"关键词堆砌报警：单关键词「{top_word}」占正文词数 {top_share:.1%} > 5%。")
    elif top_word:
        reasons.append(f"关键词密度正常：最高频词「{top_word}」占 {top_share:.1%} ≤ 5%。")
    else:
        reasons.append("正文词量 <50，关键词密度项不适用（N/A）。")

    verdict = "FAIL" if fails else "PASS"
    return {"file": path, "verdict": verdict, "chars": chars,
            "required_units": required_units, "evidence_units": units,
            "valid_urls": len(valid_urls), "invalid_urls": invalid_urls,
            "top_word": top_word, "top_share": round(top_share, 4),
            "reasons": reasons + fails}


# ---------------------------------------------------------------- 闸门 C
def gate_c(conn: sqlite3.Connection, days: int = 7) -> dict:
    """变更冻结窗：近 days 天登记变更清单 + GSC 对比状态 + 到期提醒。"""
    cutoff = (datetime.now(CST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT c.*, h.code AS hyp_code FROM changes c"
        " LEFT JOIN hypotheses h ON h.id = c.hypothesis_id"
        " WHERE c.deployed_at >= ? ORDER BY c.deployed_at", (cutoff,)).fetchall()
    all_rows = conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    items, reminders = [], []
    for r in rows:
        d = dict(r)
        items.append(d)
        if not d["gsc_comparison_started"]:
            reminders.append(
                f"change#{d['id']}（{d['deployed_at']}，{d['change_type']}）已登记但未建 "
                "GSC 每日对比——冻结窗要求上线后自动建 7 天对比，老 URL 曝光归零即告警。")
    old_no_compare = conn.execute(
        "SELECT COUNT(*) FROM changes WHERE deployed_at < ? AND gsc_comparison_started = 0",
        (cutoff,)).fetchone()[0]
    verdict = "PASS"
    reasons = [f"近 {days} 天登记变更 {len(items)} 条（changes 表共 {all_rows} 条）。"]
    if not items:
        reasons.append("窗口内无 URL/重定向/模板级变更登记——无冻结窗义务触发。"
                       "（注：无登记 ≠ 无变更，部署钩子未接前靠人工登记，见 lifecycle start。）")
    if reminders:
        verdict = "WARN"
        reasons += reminders
    if old_no_compare:
        reasons.append(f"另有 {old_no_compare} 条更早变更从未建 GSC 对比，已过冻结窗，列为欠账。")
    return {"verdict": verdict, "items": items, "reasons": reasons}


# ---------------------------------------------------------------- 闸门 D
REQUIRED_FIELDS = [
    ("hypothesis", "假设（页面集×动作×主指标×窗口×基线→目标）"),
    ("layer", "层级"),
    ("primary_metric", "主指标"),
    ("baseline_value", "基线值/基线证据行"),
    ("target", "目标值"),
    ("guardrail", "护栏指标"),
    ("threshold", "成功阈值"),
    ("control_group", "对照组"),
    ("cost", "样本与成本"),
    ("stop_condition", "停止条件"),
]


def gate_d(card: dict, conn: sqlite3.Connection, evidence: dict) -> tuple[str, list[str]]:
    """立项门：draft → approved 的可流转性校验。返回 (PASS|FAIL, 逐条理由)。"""
    code = card.get("code", "?")
    fails, oks = [], []

    missing = [label for field, label in REQUIRED_FIELDS
               if not str(card.get(field) or "").strip()]
    if missing:
        fails.append(f"字段不完整，缺：{'、'.join(missing)}。")
    else:
        oks.append("必填字段齐全（假设/层级/主指标/基线/目标/护栏/阈值/对照/成本/停止条件）。")

    hyp = card.get("hypothesis") or ""
    if "机制" not in hyp:
        fails.append("假设文本缺机制说明（须引一手证据：自有数据/论文/官方文档）。")
    if not re.search(r"\d+\s*天", hyp):
        fails.append("假设文本缺时间窗口（如 28 天）。")

    metric = card.get("primary_metric") or ""
    if AUDIT_METRIC_PATTERN.search(metric):
        fails.append(f"主指标是审计分（{metric}）——设计 §1.4：审计分不进假设卡指标栏，直接 FAIL。")
    else:
        oks.append("主指标非审计分，为结果类指标。")

    baseline = card.get("baseline_value") or ""
    future_hit = [p for p in FUTURE_BASELINE_PATTERNS if re.search(p, baseline)]
    has_anchor = bool(re.search(r"\d", baseline) or "false" in baseline or "true" in baseline)
    if future_hit:
        fails.append(
            "主指标基线未定量：基线字段含未落数表述（命中「" + "、".join(future_hit) +
            "」）——设计 §4.3：填不出基线值 → 驳回：先补数据。")
    elif not has_anchor:
        fails.append("基线字段无可核查的实测锚点（无数字/无实测布尔值），不算基线证据行。")
    else:
        oks.append("基线证据行成立（含已实测锚点，非待建基线）。")

    a_verdict, a_reasons = gate_a(card, evidence)
    if a_verdict == "FAIL":
        fails.append("与闸门 A 冲突：" + " ".join(a_reasons))
    else:
        oks.append("与闸门 A 不冲突（结构修复类放行）。")

    verdict = "FAIL" if fails else "PASS"
    head = f"{code}（{card.get('title', '')}）：闸门 D {'通过——可流转至 approved' if verdict == 'PASS' else '驳回——不可流转'}。"
    return verdict, [head] + [f"✓ {r}" for r in oks] + [f"✗ {r}" for r in fails]


# ---------------------------------------------------------------- CLI
def _print_verdict(subject: str, verdict: str, reasons: list[str]):
    print(f"[{verdict}] {subject}")
    for r in reasons:
        print(f"    - {r}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    conn = db.connect()
    ensure_p1_schema(conn)
    evidence = load_gsc_evidence()
    exit_code = 0

    def run_a(cards, include_demo=False):
        nonlocal exit_code
        for card in cards:
            v, rs = gate_a(card, evidence)
            log_check(conn, "A", card["code"], v, rs)
            _print_verdict(f"闸门 A · {card['code']}", v, rs)
            if v == "FAIL":
                exit_code = 1
        if include_demo:
            v, rs = gate_a(DEMO_REWRITE_CARD, evidence)
            log_check(conn, "A", "DEMO-REWRITE", v, rs, source="gates.py demo（不入库假设卡）")
            _print_verdict("闸门 A · DEMO-REWRITE（演示拦截）", v, rs)
            if v == "FAIL":
                exit_code = 1

    def run_b(files):
        nonlocal exit_code
        for path in files:
            res = gate_b(path)
            log_check(conn, "B", os.path.basename(path), res["verdict"],
                      res["reasons"], source=f"gates.py b {path}")
            _print_verdict(f"闸门 B · {path}", res["verdict"], res["reasons"])
            print(f"    度量：chars={res['chars']} required_units={res['required_units']} "
                  f"evidence_units={res['evidence_units']} valid_urls={res['valid_urls']} "
                  f"invalid={len(res['invalid_urls'])} top_word={res['top_word']} "
                  f"top_share={res['top_share']}")
            if res["verdict"] == "FAIL":
                exit_code = 1

    def run_c():
        res = gate_c(conn)
        log_check(conn, "C", "changes:7d", res["verdict"], res["reasons"])
        _print_verdict("闸门 C · 变更冻结窗", res["verdict"], res["reasons"])

    def run_d(cards):
        nonlocal exit_code
        for card in cards:
            v, rs = gate_d(card, conn, evidence)
            log_check(conn, "D", card["code"], v, rs)
            _print_verdict(f"闸门 D · {card['code']}", v, rs)
            if v == "FAIL":
                exit_code = 1

    code_filter = None
    if "--code" in argv:
        code_filter = argv[argv.index("--code") + 1]
    cards = [get_card(conn, code_filter)] if code_filter else all_cards(conn, "draft")
    cards = [c for c in cards if c]

    if cmd == "a":
        run_a(cards, include_demo="--demo-rewrite" in argv)
    elif cmd == "b":
        files = [a for a in argv[2:] if not a.startswith("--")]
        if not files:
            print("用法：gates.py b <file> [...]")
            return 2
        run_b(files)
    elif cmd == "c":
        run_c()
    elif cmd == "d":
        run_d(cards)
    elif cmd == "all":
        run_a(cards, include_demo=True)
        run_b([
            os.path.expanduser("~/workspace/goals/1/hidden_files/geo-p0/audit-2026-11-02/maoxunxing-llms.txt"),
            os.path.expanduser("~/workspace/maoxunxing-site/content/ai-coding-workflow/fullstack/index.zh-cn.md"),
        ])
        run_c()
        run_d(cards)
    else:
        print(__doc__)
        return 2
    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
