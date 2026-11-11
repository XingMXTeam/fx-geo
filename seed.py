"""GEO 闭环系统 MVP · 种子数据

只灌已实测的真实数据，来源：
- 双站审计 JSON：~/workspace/goals/1/hidden_files/geo-p0/audit-2026-11-02/audit-*.json（geo-optimizer 4.18.3 实跑）
- 冻结 prompt 集：~/workspace/goals/1/files/GEO-P0-prompt集冻结v1-2026-11-02.md
- CrossAgent 基线：~/workspace/goals/1/files/CrossAgent样板报告-GEO可见度-2026-10-29.md
- P0 战报：~/workspace/goals/1/files/GEO-P0-第一天战报-2026-11-02.md
未接入的数据源一律只写状态，不写数字。
可重复运行：先清空各表再灌。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect, init_db
from rubric import CHECK_KEYS as BREAKDOWN_KEY, CHECK_MAX, check_max

GOALS = os.path.expanduser("~/workspace/goals/1")
AUDIT_DIR = os.path.join(GOALS, "hidden_files/geo-p0/audit-2026-11-02")
PROMPT_MD = os.path.join(GOALS, "files/GEO-P0-prompt集冻结v1-2026-11-02.md")
SEED_DATE = "2026-11-02"

CATEGORY_MAP = {"品类通用": "品类", "使用场景": "场景", "竞品对比": "对比", "决策类": "决策", "品牌直查": "品牌"}
# CHECK_MAX is rubric v2 (the live default). These files are geo-optimizer 4.18.3, so they stay v1.
HISTORICAL_AUDIT_SCORE_VERSION = 1
if CHECK_MAX["google_ai"] != 20 or "google_ai" in check_max(HISTORICAL_AUDIT_SCORE_VERSION):
    raise RuntimeError("v2 CHECK_MAX must not be applied to historical v1 audits")


def load_audit(fname):
    raw = open(os.path.join(AUDIT_DIR, fname), encoding="utf-8").read()
    return json.loads(raw[raw.index("{"):])  # 跳过文件首行 preamble


def audit_failures(d):
    """只从审计 JSON 本身派生失败项，派生不出的不写。"""
    out = []
    for key, chk in d.get("checks", {}).items():
        if isinstance(chk, dict) and chk.get("passed") is False:
            out.append(f"{key} 未通过（{chk.get('score')}/{chk.get('max')}）")
    llms = d.get("checks", {}).get("llms_txt", {}).get("details", {})
    if llms.get("links_count") == 0:
        out.append("llms_txt links_count = 0（has_links = false）")
    content = d.get("checks", {}).get("content", {}).get("details", {})
    if content.get("has_h1") is False:
        out.append(f"content has_h1 = false（heading_count = {content.get('heading_count')}）")
    neg = d.get("negative_signals", {})
    if neg.get("has_keyword_stuffing"):
        out.append("negative_signals: has_keyword_stuffing = true")
    return out


def parse_prompts():
    """解析冻结 prompt 集 md，返回 {domain: [(category, seq, text), ...]}"""
    text = open(PROMPT_MD, encoding="utf-8").read()
    result = {}
    site = None
    category = None
    for line in text.splitlines():
        if line.startswith("## A."):
            site = "crossagent.maoxunxing.com"
            result.setdefault(site, [])
        elif line.startswith("## B."):
            site = "maoxunxing.com"
            result.setdefault(site, [])
        elif line.startswith("### ") and site:
            head = line[4:].strip()
            for zh, short in CATEGORY_MAP.items():
                if head.startswith(zh):
                    category = short
        elif re.match(r"^\d+\.\s+", line) and site and category:
            m = re.match(r"^(\d+)\.\s+(.*)$", line.strip())
            result[site].append((category, int(m.group(1)), m.group(2).strip()))
    return result


def main():
    init_db()
    conn = connect()
    cur = conn.cursor()
    for tbl in ["prompts", "audits", "baseline_snapshots", "hypotheses", "findings",
                "source_status", "rules", "sites"]:
        cur.execute(f"DELETE FROM {tbl}")

    # ---- sites ----
    sites = [
        ("maoxunxing.com", "毛毛星（主站）", "主站",
         "邮件订阅 + 三个垂直产品站（CrossAgent / Browserly / Sayo）出站点击 / 周"),
        ("crossagent.maoxunxing.com", "CrossAgent Lab", "垂直产品站",
         "newsletter 订阅 / 周"),
    ]
    site_id = {}
    for domain, name, role, ns in sites:
        cur.execute("INSERT INTO sites(domain,name,role,north_star) VALUES(?,?,?,?)",
                    (domain, name, role, ns))
        site_id[domain] = cur.lastrowid

    # ---- audits（解析真实审计 JSON）----
    audit_note = (
        "score_version=v1 卫生分，不预测引用，也不是 AI 引用率、提及率或发现率"
        "（geo-optimizer 4.18.3；作者预注册校准研究：审计分与实际引用无预测关系）"
    )
    historical_max = check_max(HISTORICAL_AUDIT_SCORE_VERSION)
    for domain, fname in [("maoxunxing.com", "audit-maoxunxing.json"),
                          ("crossagent.maoxunxing.com", "audit-crossagent.json")]:
        d = load_audit(fname)
        breakdown = {}
        for chk_key, short in BREAKDOWN_KEY.items():
            chk = d.get("checks", {}).get(chk_key, {})
            breakdown[short] = {"score": chk.get("score"), "max": historical_max[chk_key]}
        breakdown["negative_penalty"] = d.get("score_breakdown", {}).get("negative_penalty")
        cur.execute(
            "INSERT INTO audits(site_id,run_at,score,score_version,band,breakdown_json,"
            "priorities_json,failures_json,source_file,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (site_id[domain], d.get("timestamp"), d.get("score"), HISTORICAL_AUDIT_SCORE_VERSION,
             d.get("band"),
             json.dumps(breakdown, ensure_ascii=False),
             json.dumps(d.get("recommendations", [])[:5], ensure_ascii=False),
             json.dumps(audit_failures(d), ensure_ascii=False),
             fname, audit_note))

    # ---- prompts（解析冻结集）----
    parsed = parse_prompts()
    n_prompts = 0
    for domain, items in parsed.items():
        for category, seq, text_ in items:
            cur.execute(
                "INSERT INTO prompts(site_id,set_version,category,seq,text,source) VALUES(?,?,?,?,?,?)",
                (site_id[domain], "v1", category, seq, text_, "manual"))
            n_prompts += 1

    # ---- baseline_snapshots（仅 CrossAgent 2026-10-29 样板，主站无）----
    caliber = "2026-10-29 单次快照，浏览器未登录口径"
    src = "CrossAgent样板报告-GEO可见度-2026-10-29.md"
    ca = site_id["crossagent.maoxunxing.com"]
    baselines = [
        ("ChatGPT", "品牌提及率", "CrossAgent Lab", 8.0, "%"),
        ("ChatGPT", "Share of Voice", "CrossAgent Lab", 6.0, "%（约）"),
        ("ChatGPT", "竞品提及率", "Shopify", 64.0, "%"),
        ("ChatGPT", "竞品提及率", "n8n", 40.0, "%"),
        ("ChatGPT", "竞品提及率", "Jungle Scout", 12.0, "%"),
        ("Google AI", "品类题提及率", "CrossAgent Lab", 0.0, "%（核心题品类 8 题 0 次）"),
        ("Perplexity", "品类题提及率", "CrossAgent Lab", 0.0, "%（核心题品类 8 题 0 次）"),
    ]
    for engine, metric, subject, value, unit in baselines:
        cur.execute(
            "INSERT INTO baseline_snapshots(site_id,snapshot_date,engine,metric,subject,value,unit,caliber,source)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (ca, "2026-10-29", engine, metric, subject, value, unit, caliber, src))

    # ---- findings（审计实锤 + 战报的数据缺口）----
    mx = site_id["maoxunxing.com"]
    findings = [
        (mx, None, "L1", "llms.txt 存在但 markdown 链接数 = 0",
         "审计 llms_txt：links_count = 0、has_links = false（链接写成纯文本 URL）",
         "文件等于白写：解析器不认纯文本 URL。", "high", "geo-optimizer 审计 2026-11-02"),
        (ca, None, "L1", "llms.txt 存在但 markdown 链接数 = 0",
         "审计 llms_txt：links_count = 0、has_links = false（链接写成纯文本 URL）",
         "同主站问题。", "high", "geo-optimizer 审计 2026-11-02"),
        (ca, None, "L1", "首页没有 H1",
         "审计 content：has_h1 = false、heading_count = 66",
         "真 bug，不是 GEO 技巧问题。", "high", "geo-optimizer 审计 2026-11-02"),
        (mx, None, "L1", "缺 Organization JSON-LD",
         "审计 recommendations 第 1 条；trust_stack identity：No Organization JSON-LD schema；brand_entity kg_pillar_count = 0",
         "与 10-29 样板「三引擎把品牌认成三个东西」的实体问题同源。", "high", "geo-optimizer 审计 2026-11-02"),
        (ca, None, "L1", "robots 缺 Bingbot / Googlebot / Claude-SearchBot 具名行",
         "robots.txt 原文：具名行只有 OAI-SearchBot / GPTBot / ChatGPT-User / ClaudeBot / PerplexityBot；审计 robots_txt citation_bots_explicit = false",
         "当前靠 User-agent: * Allow: / 兜底，有效但具名化更稳。", "normal", "robots.txt 直抓 2026-11-02"),
        (mx, None, "L1", "ai_discovery 0/6（score_version=v1，低优先级）",
         "审计 ai_discovery：0/6（score_version=v1），缺 /.well-known/ai.txt、/ai/summary.json、/ai/faq.json",
         "工具口径卫生项，价值未证，不当增长项。", "low", "geo-optimizer 审计 2026-11-02"),
        (ca, None, "L1", "ai_discovery 0/6（score_version=v1，低优先级）",
         "审计 ai_discovery：0/6（score_version=v1），缺 /.well-known/ai.txt、/ai/summary.json、/ai/faq.json",
         "工具口径卫生项，价值未证，不当增长项。", "low", "geo-optimizer 审计 2026-11-02"),
        (None, "两站", "L3", "GSC 未接入（数据缺）",
         "token.json 文件不在磁盘上（~/.config/mcp-gsc/ 为空）；client_secrets 尚在",
         "L3 收录层无数据；重授权需一次浏览器登录交互。", "high", "P0 第一天战报 2026-11-02"),
        (None, "两站", "L2", "AI 爬虫日志未接入（数据缺）",
         "Cloudflare / 源站日志尚未拉取",
         "不拿 robots 的「allowed」冒充 bot「来过」。", "normal", "P0 第一天战报 2026-11-02"),
        (None, "两站", "L5", "AI 采样未常态化（数据缺）",
         "CrossAgent 仅有 2026-10-29 单次快照；主站尚无任何一轮采样；geo citations 的 provider key 一个未配、Gemini API host 本 VM 当前无响应",
         "L5 只有单次快照，没有连续基线。", "high", "P0 第一天战报 2026-11-02"),
    ]
    for sid, scope, layer, title, evidence, detail, sev, source in findings:
        cur.execute(
            "INSERT INTO findings(site_id,scope,layer,title,evidence,detail,severity,source) VALUES(?,?,?,?,?,?,?,?)",
            (sid, scope, layer, title, evidence, detail, sev, source))

    # ---- hypotheses（四张 L1 修复 draft 卡）----
    hyps = [
        dict(code="H-001", site_id=None, scope="两站", title="llms.txt 改 markdown 链接（两站）",
             layer="L1",
             hypothesis="若把两站 llms.txt 内的纯文本 URL 全部改为 markdown 链接格式，则判定采样中本站域名被引用的比例在 28 天内不低于基线并有正向变化；机制：llms.txt 解析器只认 markdown 链接，当前 links_count=0 等于关键页清单不存在。",
             primary_metric="冻结 prompt 集判定采样中本站域名的引用率（Citation，≥5 次/引擎、Wilson 区间）",
             baseline_value="llms_txt links_count = 0（两站，2026-11-02 审计实测）；引用率常态化基线未建，采样接入后以首轮判定采样为基线",
             target="llms.txt 链接覆盖两站 sitemap 核心页（主站 415 条叶子 URL 中的核心页、Lab 90 条中的核心页）",
             guardrail="GSC 总曝光跌幅 ≤10%（GSC 接入后生效）；改动只动 llms.txt 一个文件/站",
             threshold="引用率判定采样较基线 +5 个百分点以上且区间不跨 0 才算有效",
             control_group="无同模板对照组：用 CausalImpact 前后对比 + 同口径复测",
             cost="约 1 小时工时，无 API 成本",
             stop_condition="28 天判定采样引用率无变化 → 记无效结论，30 天内不再立同类假设",
             hygiene_note="卫生复核：审计 llms_txt 分类分（score_version=v1，两站均 10/18）只作复核记录，不作主指标"),
        dict(code="H-002", site_id=ca, scope="CrossAgent Lab", title="Lab 首页补 H1",
             layer="L1",
             hypothesis="若给 CrossAgent Lab 首页补上唯一的 H1（明确陈述页面主题），则品牌直查题的实体识别正确率在 28 天内提升；机制：首页无 H1 时引擎缺页面主题锚点，10-29 样板中三引擎对品牌实体无共识。",
             primary_metric="品牌直查题（冻结集 Q23–25）实体识别正确率（判定采样 ≥5 次/引擎）",
             baseline_value="has_h1 = false（2026-11-02 审计实测）；10-29 样板：三引擎品牌题无一全对（ChatGPT 识别失败、Google 认成学术框架、Perplexity 域名直查失败）",
             target="≥2 个引擎品牌直查题识别正确",
             guardrail="首页其余 heading 与内容区块不删减；页面保持 HTTP 200",
             threshold="正确率较基线提升且至少 2 引擎全对品牌题",
             control_group="无对照组：同口径复测 + 前后对比",
             cost="约 0.5 小时工时",
             stop_condition="28 天无改善 → 记无效结论",
             hygiene_note="卫生复核：审计 content 分类 has_h1 变为 true 只作复核记录，不作主指标"),
        dict(code="H-003", site_id=mx, scope="主站", title="主站补 Organization JSON-LD + sameAs",
             layer="L1",
             hypothesis="若给主站补 Organization JSON-LD（name/url/logo）并填真实 sameAs（GitHub 等真实账号页），则品牌直查题对 maoxunxing.com / Felix Mao 的实体识别正确率在 28 天内提升；机制：当前无 Organization schema、KG 支柱为 0，引擎缺实体消歧信号。",
             primary_metric="品牌直查题（主站冻结集 Q23–25）实体识别正确率（判定采样 ≥5 次/引擎）",
             baseline_value="审计 brand_entity 5/10（score_version=v1）、kg_pillar_count = 0、无 Organization JSON-LD（2026-11-02 实测）；主站尚无采样基线，采样接入后首轮为基线",
             target="判定采样品牌题正确率较首轮基线提升",
             guardrail="sameAs 只填真实存在的账号页，不编造（证据密度 Linter 把关）；不改其他模板结构",
             threshold="正确率提升 ≥20 个百分点或品牌题全对",
             control_group="无对照组：同口径复测 + 前后对比",
             cost="约 1 小时工时",
             stop_condition="28 天无改善 → 记无效结论",
             hygiene_note="卫生复核：审计 schema / brand_entity 分类分只作复核记录，不作主指标"),
        dict(code="H-004", site_id=ca, scope="CrossAgent Lab", title="Lab robots 具名补 Bingbot / Googlebot / Claude-SearchBot 行",
             layer="L1",
             hypothesis="若在 Lab robots.txt 为 Bingbot、Googlebot、Claude-SearchBot 补具名 Allow 行，则 INDEX 类 bot 的抓取口径从「靠通配兜底」变为显式放行，日志接入后抓取覆盖可被稳定归因；机制：当前 citation_bots_explicit = false，具名缺失时任何通配改动都会连带影响 INDEX 类 bot。",
             primary_metric="日志接入后 INDEX 类 bot（Bingbot / Googlebot）对 Lab 的抓取覆盖率（已抓 URL ÷ sitemap 90 条）",
             baseline_value="robots 具名行缺失、citation_bots_explicit = false（2026-11-02 实测）；日志未接入，抓取覆盖基线待日志接入后首周建立",
             target="具名行补齐；日志首周 INDEX 类 bot 抓取无异常 4xx 集中爆发",
             guardrail="不得误封任何 INDEX 类 bot；改后必须过审计 robots 分类复核与闸门 C 变更留痕",
             threshold="具名行齐全且日志覆盖率达到首周基线",
             control_group="无对照组：改前/改后 robots 原文留档对比",
             cost="约 0.5 小时工时",
             stop_condition="日志接入后 28 天覆盖率无基线可比 → 关闭并入日志接入事项",
             hygiene_note="卫生复核：审计 robots_txt 分类分（score_version=v1，当前 15/18）只作复核记录，不作主指标"),
    ]
    for h in hyps:
        cur.execute(
            "INSERT INTO hypotheses(code,site_id,scope,title,status,layer,hypothesis,primary_metric,baseline_value,"
            "target,guardrail,threshold,control_group,cost,stop_condition,hygiene_note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h["code"], h["site_id"], h["scope"], h["title"], "draft", h["layer"], h["hypothesis"],
             h["primary_metric"], h["baseline_value"], h["target"], h["guardrail"], h["threshold"],
             h["control_group"], h["cost"], h["stop_condition"], h["hygiene_note"], SEED_DATE))

    # ---- source_status ----
    sources = [
        ("audit", "站点审计（geo-optimizer）", "已接入",
         "2026-11-02 已实跑双站：主站 62 分、Lab 65 分（score_version=v1，卫生分，不预测引用；不是 v2 基线）",
         "下一次复跑用 geo-optimizer 4.19 默认口径（score_version=v2）另记一条，不与 v1 分数比；沙箱仍需本地 runner 放行 fake-IP"),
        ("gsc", "Google Search Console", "未接入",
         "token.json 文件已不在磁盘（目录为空，原因不明）；client_secrets 尚在，重授权不用重建应用；应用 Testing 状态 refresh token 约 7 天失效",
         "用户浏览器重新授权一次；恢复后一周内建每日 cron"),
        ("gemini", "AI 采样 · Gemini API", "未接入",
         "generativelanguage.googleapis.com 本 VM 当前无响应（2026-11-02 冒烟：curl 150s http=000）；key 未被验证，不记无效；该 host 2026-10-25 曾在本沙箱直连成功",
         "择时重试冒烟；或与 Perplexity 口径并行对照"),
        ("perplexity", "AI 采样 · Perplexity API", "未配置",
         "通道已实测可达（无 key 返回 401，1.2s）；尚无 key；价目：基线一轮 <$2、首充 $10 够、日常全量约 $20/月",
         "用户充 $10 并经安全录入提供 key 后跑 citations 判定基线"),
        ("elmo", "Elmo（网页口径采样）", "未部署",
         "沙箱无 Docker，跑不起来；已 clone 至 ~/workspace/geo-p0/elmo 完成评估；用户已有 OpenRouter key 可顶 Jev 判定与 onboarding，只缺抓取 provider",
         "在 Mac / VPS 上 + BrightData（$10 起充，一周试跑约 $11）试跑一周"),
        ("logs", "AI 爬虫日志", "未接入",
         "Cloudflare / 源站日志尚未拉取；L2 层无数据",
         "接入原始日志落库，GEOInflow 只作可替换解析层试点"),
        ("bing", "Bing Webmaster", "未接入",
         "sitemap 未提交，AI Performance 报告 CSV 未导出",
         "提交两站 sitemap，周导 AI Performance CSV 入库"),
    ]
    for source, label, status, detail, nxt in sources:
        cur.execute("INSERT INTO source_status(source,label,status,detail,next_step,updated_at) VALUES(?,?,?,?,?,?)",
                    (source, label, status, detail, nxt, SEED_DATE))

    # ---- rules ----
    rules = [
        ("闸门 A · Retrieval-First",
         "未收录、未被 AI 爬虫抓过、从未进检索候选集的页面，禁止投入改写工时，只许修结构面（L1–L3）。",
         "论文", "C-SEO Bench（arXiv:2506.11097，已核原文）"),
        ("审计分不作效果",
         "审计分只作 CI 卫生门禁（防确定性错误回退），不进假设卡的主指标与护栏；效果只认采样引用率 / GSC / 转化。",
         "工具作者实证", "geo-optimizer 作者 2026-10 预注册校准研究（null result）"),
        ("采样分层",
         "日常监测每 prompt×引擎 1–2 次只看趋势；判定（基线出数 / 实验到期）≥5 次/引擎 + Wilson 区间才下结论；原始回答不可覆盖落库。",
         "定稿口径 + 自有实测", "v3 定稿 §4.7；10-29 样板复跑波动实测"),
        ("闸门 C · 变更冻结窗",
         "URL / 重定向 / 模板级改动上线前必须有重定向映射表；上线后自动建 7 天 GSC 每日对比，老 URL 曝光归零即告警；changes 由部署钩子自动留痕。",
         "自有事故实测", "2026-08 多语言迁移无重定向，184 个老 URL 404，GSC 周曝光约 −94%"),
        ("闸门 D · 立项门",
         "不在周报机会清单、没有假设卡的事，一律不排期、不投钱；假设卡填不出基线值或机制证据直接驳回。",
         "用户立规", "2026-11-01 用户亲口：没有数据依据不再动手开发或投入时间"),
    ]
    for name, statement, level, source in rules:
        cur.execute("INSERT INTO rules(name,statement,evidence_level,source) VALUES(?,?,?,?)",
                    (name, statement, level, source))

    conn.commit()
    counts = {}
    for tbl in ["sites", "prompts", "audits", "baseline_snapshots", "hypotheses", "findings", "source_status", "rules"]:
        counts[tbl] = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    conn.close()
    print("seed done:", counts)
    print("prompts parsed:", parsed.keys(), {k: len(v) for k, v in parsed.items()})


if __name__ == "__main__":
    main()
