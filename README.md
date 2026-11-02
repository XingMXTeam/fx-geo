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
├── panel.html        # 单页中文面板（Tabler 仪表盘布局），由 app.py 在 / 返回
├── vendor/
│   ├── tabler.min.css  # Tabler v1.4.0 CSS（vendored，MIT；出页面时内联，见「UI 模板」）
│   └── NOTICE          # 第三方资产出处与许可
├── db.py             # SQLite schema（按 v3 §6.1 简化；生产版见 supabase/schema.sql）
├── seed.py           # 种子：解析审计 JSON + 冻结 prompt md + 样板基线 + 战报，只灌真实数据
├── supabase/
│   ├── schema.sql    # 生产 DDL（Postgres）：8 表 + 索引 + RLS（anon 只读策略）
│   └── seed.sql      # 与 SQLite 种子逐项一致的 INSERT（由 geo.db 导出核对）
├── geo.db            # SQLite 数据库（seed 生成）
├── collectors/
│   ├── gsc.py        # 骨架：检查 ~/.config/mcp-gsc/token.json 是否存在 → 状态
│   ├── citations.py  # 骨架：检查 GEMINI_API_KEY / PERPLEXITY_API_KEY 是否存在 → 状态
│   └── audit.py      # 骨架：封装已有 geo-optimizer 本地 runner 路径 → 状态
├── .env.example      # 后续接 key 的位置（只列名，不写值）
├── VERIFY.log        # 启动/API 断言验证输出（本地生成，不进仓库；geo.db 同理由 seed.py 再生，不进仓库）
└── panel.png         # 面板截图（headless chromium）

## UI 模板（Tabler）

面板 UI 套用开源仪表盘套件 **Tabler v1.4.0**（MIT，github.com/tabler/tabler）：
深色左侧边栏 + 浅色内容区、KPI 卡、状态徽章、表格与进度条均为 Tabler 组件语言。
CSS 以 vendored 方式存放在 `vendor/tabler.min.css`（未修改，出处见 `vendor/NOTICE`），
不引入 Tabler JS（边栏折叠、导航高亮、顶栏数据模式探测均为少量原生 JS）。
`panel.html` 里以 `/*__TABLER_CSS__*/` 占位标记引用它：本地由 `app.py` 出页面时填入，
静态导出由 `export_static.py` 内联进 HTML，保证部署页仍是单文件自包含。

## 静态导出（部署到主站 /geo/）

```bash
.venv/bin/python export_static.py /path/to/index.html
```

从 app 的数据层直接取全部 API JSON，内嵌为 `window.__GEO_DATA__`，并在页头注入一小段
fetch 垫片（`/api/*` 优先读内嵌数据）。静态版额外带
`<meta name="robots" content="noindex,nofollow">`（内部面板，不进搜索引擎）。

## 生产数据库 = Supabase（本地 SQLite 仅开发镜像）

架构定版：生产数据放 Supabase（Postgres），本地 SQLite 只作开发镜像；面板取数双模式——
有 Supabase 配置时直查 PostgREST 读活数据，没配置或查询失败时回退内嵌快照。

接 Supabase 的步骤：

1. 在 supabase.com 建项目（免费层即可），记下 Project URL 与 anon public key
   （service_role key 只给后台写入脚本用，**绝不进面板/前端**）；
2. 在项目 SQL Editor 里依次跑 `supabase/schema.sql`、`supabase/seed.sql`
   （schema 末尾已开 RLS：anon 只有 select 策略，写不进任何表）；
3. 重新导出面板并注入配置（不用改任何代码）：

   ```bash
   GEO_SUPABASE_URL=https://<ref>.supabase.co GEO_SUPABASE_ANON_KEY=<anon key> \
     .venv/bin/python export_static.py /path/to/index.html
   ```

   导出页会写入 `window.__GEO_CONFIG__`；面板打开时优先按此配置直查
   `/rest/v1/<table>` 拼数渲染，任一查询失败自动回退到同页内嵌的 `__GEO_DATA__` 快照。
   本次主站上线版不带配置（项目还没建），先以快照模式上线，建好后按上面重导即切活数据。
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
