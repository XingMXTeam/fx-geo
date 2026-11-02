# GEO 闭环系统 · MVP

按《GEO 闭环系统设计 v3 定稿》（`~/workspace/goals/1/files/GEO闭环系统设计-v3-定稿-2026-11-02.md`）§6.1 简化落地的最小系统：
先有系统和面板，key 后续再配。**未接入的数据源在面板里只显示状态，不显示任何假数字。**

## 启动

```bash
cd ~/workspace/geo-system
.venv/bin/python seed.py          # 灌种子（可重复运行：先清表再灌，只用已实测数据）
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
# 打开 http://127.0.0.1:8765/
```

## 目录结构

```
geo-system/
├── app.py            # FastAPI：面板 + /api/* JSON
├── export_static.py  # 静态导出：数据内嵌 + fetch 垫片，生成自包含 HTML（见下）
├── panel.html        # 单页中文面板（深色简洁），由 app.py 在 / 返回
├── db.py             # SQLite schema（按 v3 §6.1 简化，后续可迁 Postgres）
├── seed.py           # 种子：解析审计 JSON + 冻结 prompt md + 样板基线 + 战报，只灌真实数据
├── geo.db            # SQLite 数据库（seed 生成）
├── collectors/
│   ├── gsc.py        # 骨架：检查 ~/.config/mcp-gsc/token.json 是否存在 → 状态
│   ├── citations.py  # 骨架：检查 GEMINI_API_KEY / PERPLEXITY_API_KEY 是否存在 → 状态
│   └── audit.py      # 骨架：封装已有 geo-optimizer 本地 runner 路径 → 状态
├── .env.example      # 后续接 key 的位置（只列名，不写值）
├── VERIFY.log        # 启动/API 断言验证输出（本地生成，不进仓库；geo.db 同理由 seed.py 再生，不进仓库）
└── panel.png         # 面板截图（headless chromium）

## 静态导出（部署到主站 /geo/）

```bash
.venv/bin/python export_static.py /path/to/index.html
```

从 app 的数据层直接取全部 API JSON，内嵌为 `window.__GEO_DATA__`，并在页头注入一小段
fetch 垫片（`/api/*` 优先读内嵌数据），panel.html 本体零改动。静态版额外带
`<meta name="robots" content="noindex,nofollow">`（内部面板，不进搜索引擎）。
```

## 数据表与种子行数

sites 2 · prompts 50（两站各 25，冻结 v1）· audits 2（主站 62 / Lab 65，卫生分）
· baseline_snapshots 7（仅 CrossAgent 2026-10-29 单次快照；主站为空 = 尚无采样）
· findings 10 · hypotheses 4（全 draft）· source_status 7（1 已接入 / 6 未接入或未配置）
· rules 5

## API

- `GET /` 面板
- `GET /api/overview` 总览（站点卡 / 数据源 / 漏斗 / 计数 / 规则）
- `GET /api/sites/{id|domain}` 单站详情（审计、基线、findings、假设卡）
- `GET /api/prompts`（可带 `?site=<domain>`）
- `GET /api/hypotheses` / `GET /api/findings` / `GET /api/sources`

## 后续接 key 的位置（.env.example）

- GSC：重授权后 token 放回 `~/.config/mcp-gsc/token.json`（`GSC_TOKEN_PATH`），
  `collectors/gsc.py` 即返回 ready，再接 `~/workspace/gsc-analyze.py` 每日拉取写库。
- AI 采样：`GEMINI_API_KEY` / `PERPLEXITY_API_KEY` 经安全录入注入环境变量，
  `collectors/citations.py` 返回 key_present 后再接 geo citations 实跑写 baseline_snapshots。
- Elmo：部署在 Mac / VPS，`OPENROUTER_API_KEY` + `SCRAPE_TARGETS` / `BRIGHTDATA_API_KEY`。
- Bing：`BING_WEBMASTER_API_KEY`（或先手工导 AI Performance CSV）。

## 口径红线

- 审计分是**卫生分，不预测引用**（工具作者预注册校准研究为 null），不进假设卡指标栏。
- 没有采样基线的站就写「尚无采样」；没有 GSC 就写「未接入」。不许用估算填空。
