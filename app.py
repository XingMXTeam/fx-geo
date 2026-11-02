"""GEO 闭环系统 MVP · FastAPI 面板 + API

启动：.venv/bin/uvicorn app:app --port 8765
数据：geo.db（先跑 python seed.py 灌种子）。未接入的数据源只显示状态，不显示假数字。
"""
import json
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from db import connect, init_db

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="GEO 闭环系统 MVP")

FUNNEL_DEFS = [
    ("L1", "可达", "robots / CDN 放行、404 与重定向、sitemap、llms.txt、Schema 卫生"),
    ("L2", "被抓取", "三类 bot 是否真来过（日志）"),
    ("L3", "被收录", "GSC 已索引数、URL Inspection"),
    ("L4", "被检索 / 曝光", "GSC 曝光与排名、prompt 采样中被 retrieval 到"),
    ("L5", "被引用", "Mention / Citation / Position / SoV（采样）"),
    ("L6", "点击", "GSC 点击 / CTR、AI referral 会话"),
    ("L7", "转化", "北极星（产品埋点）"),
]


def rows(sql, args=()):
    conn = connect()
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return out


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def site_payload(site):
    audit = one("SELECT * FROM audits WHERE site_id=? ORDER BY id DESC", (site["id"],))
    if audit:
        audit["breakdown"] = json.loads(audit.pop("breakdown_json") or "{}")
        audit["priorities"] = json.loads(audit.pop("priorities_json") or "[]")
        audit["failures"] = json.loads(audit.pop("failures_json") or "[]")
    baselines = rows("SELECT * FROM baseline_snapshots WHERE site_id=? ORDER BY engine, metric",
                     (site["id"],))
    return {
        **site,
        "audit": audit,
        "baseline_count": len(baselines),
        "baseline_status": "有快照" if baselines else "尚无采样",
        "findings_count": one("SELECT COUNT(*) c FROM findings WHERE site_id=?",
                              (site["id"],))["c"],
        "unconnected_sources": one(
            "SELECT COUNT(*) c FROM source_status WHERE status != '已接入'")["c"],
    }


def funnel():
    out = []
    status_map = {
        "L1": ("有问题待修", "审计已接入，有实测数据；findings 为审计实锤"),
        "L2": ("未接入", "日志未接入，无 bot 到访数据（不拿 robots allowed 冒充来过）"),
        "L3": ("未接入", "GSC 未接入，无收录数据"),
        "L4": ("未接入", "依赖 GSC + 采样，均未常态化"),
        "L5": ("部分有数据", "仅 CrossAgent 有 2026-10-29 单次快照；采样未常态化"),
        "L6": ("未接入", "依赖 GSC / Analytics，未接入"),
        "L7": ("未接入", "北极星已定义，产品埋点未接入，无转化数据"),
    }
    for layer, name, desc in FUNNEL_DEFS:
        cnt = one("SELECT COUNT(*) c FROM findings WHERE layer=?", (layer,))["c"]
        status, note = status_map[layer]
        out.append({"layer": layer, "name": name, "desc": desc,
                    "status": status, "note": note, "findings_count": cnt})
    return out


@app.get("/api/overview")
def overview():
    sites = [site_payload(s) for s in rows("SELECT * FROM sites ORDER BY id")]
    return {
        "as_of": "2026-11-02",
        "sites": sites,
        "sources": rows("SELECT * FROM source_status ORDER BY id"),
        "funnel": funnel(),
        "counts": {
            "prompts": one("SELECT COUNT(*) c FROM prompts")["c"],
            "findings": one("SELECT COUNT(*) c FROM findings")["c"],
            "hypotheses_draft": one(
                "SELECT COUNT(*) c FROM hypotheses WHERE status='draft'")["c"],
            "baselines": one("SELECT COUNT(*) c FROM baseline_snapshots")["c"],
            "rules": one("SELECT COUNT(*) c FROM rules")["c"],
        },
        "rules": rows("SELECT * FROM rules ORDER BY id"),
    }


@app.get("/api/sites/{site_ref}")
def site_detail(site_ref: str):
    site = one("SELECT * FROM sites WHERE id=? OR domain=?", (site_ref, site_ref)) \
        if not site_ref.isdigit() else one("SELECT * FROM sites WHERE id=?", (int(site_ref),))
    if not site:
        raise HTTPException(404, "site not found")
    payload = site_payload(site)
    payload["baselines"] = rows(
        "SELECT * FROM baseline_snapshots WHERE site_id=? ORDER BY engine, metric", (site["id"],))
    payload["findings"] = rows(
        "SELECT * FROM findings WHERE site_id=? OR site_id IS NULL ORDER BY layer, id", (site["id"],))
    payload["hypotheses"] = rows(
        "SELECT * FROM hypotheses WHERE site_id=? OR site_id IS NULL ORDER BY code", (site["id"],))
    payload["prompts_count"] = one(
        "SELECT COUNT(*) c FROM prompts WHERE site_id=?", (site["id"],))["c"]
    return payload


@app.get("/api/prompts")
def prompts(site: str = Query(None)):
    if site:
        s = one("SELECT * FROM sites WHERE domain=? OR id=?", (site, site))
        if not s:
            raise HTTPException(404, "site not found")
        return {"site": s, "prompts": rows(
            "SELECT * FROM prompts WHERE site_id=? ORDER BY seq", (s["id"],))}
    out = {}
    for s in rows("SELECT * FROM sites ORDER BY id"):
        out[s["domain"]] = rows("SELECT * FROM prompts WHERE site_id=? ORDER BY seq", (s["id"],))
    return out


@app.get("/api/hypotheses")
def hypotheses():
    return rows("SELECT h.*, s.domain AS site_domain FROM hypotheses h "
                "LEFT JOIN sites s ON s.id=h.site_id ORDER BY h.code")


@app.get("/api/findings")
def findings():
    return rows("SELECT f.*, s.domain AS site_domain FROM findings f "
                "LEFT JOIN sites s ON s.id=f.site_id ORDER BY f.layer, f.id")


@app.get("/api/sources")
def sources():
    return rows("SELECT * FROM source_status ORDER BY id")


@app.get("/")
def panel():
    return FileResponse(os.path.join(BASE, "panel.html"), media_type="text/html")


if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
