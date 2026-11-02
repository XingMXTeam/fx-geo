"""静态导出：把面板 + 全部 /api/* 数据打包成一份自包含 HTML。

做法（对 panel.html 零改动）：
- 直接 import app 的 API 函数取数据（与运行中服务同源，函数返回值即 JSON 可序列化的 dict/list）；
- 在 <head> 里注入 <meta name="robots" content="noindex,nofollow">（仅静态版，本地版不加）；
- 在 <head> 末尾注入垫片脚本：把数据存入 window.__GEO_DATA__，并覆写 window.fetch——
  对 /api/* 请求直接用内嵌数据返回 Response，其余请求走原生 fetch。
  panel.html 的全部取数调用（fetch('/api/...').then(r => r.json())）因此无改动可用。

用法：
  .venv/bin/python export_static.py [输出路径]   # 默认 ./dist/geo/index.html

可选注入 Supabase 活数据配置（面板取数层双模式，见 panel.html 头部脚本）：
  GEO_SUPABASE_URL=https://<ref>.supabase.co GEO_SUPABASE_ANON_KEY=<anon key> \
    .venv/bin/python export_static.py [输出路径]
  或参数 --supabase-url <url> --anon-key <key>。两者都给齐时，导出页会写入
  window.__GEO_CONFIG__，面板优先直查 Supabase PostgREST，失败自动回退内嵌快照；
  不给（本次上线即如此）则只有快照模式。只许填 anon key，绝不许填 service_role key。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import app as geo_app  # noqa: E402


def collect_data():
    """调用 app 里的 API 函数，键名与 panel 实际 fetch 的路径一一对应。"""
    return {
        "/api/overview": geo_app.overview(),
        "/api/findings": geo_app.findings(),
        "/api/hypotheses": geo_app.hypotheses(),
        "/api/prompts": geo_app.prompts(site=None),  # 直调须显式传 None，绕开 FastAPI 的 Query 默认值
        "/api/sites/1": geo_app.site_detail("1"),
        "/api/sites/2": geo_app.site_detail("2"),
    }


SHIM = """
<script>
/* 静态版垫片：优先读内嵌数据 __GEO_DATA__，没有的 /api 路径才走真 fetch */
window.__GEO_DATA__ = __GEO_DATA_JSON__;
(function () {
  var origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var path = url;
    try { path = new URL(url, window.location.href).pathname; } catch (e) {}
    if (path.indexOf("/api/") === 0 && Object.prototype.hasOwnProperty.call(window.__GEO_DATA__, path)) {
      return Promise.resolve(new Response(JSON.stringify(window.__GEO_DATA__[path]), {
        status: 200, headers: { "Content-Type": "application/json" }
      }));
    }
    return origFetch(input, init);
  };
})();
</script>
"""


def build(out_path, supabase_url=None, anon_key=None):
    data = collect_data()
    with open(os.path.join(BASE, "panel.html"), encoding="utf-8") as f:
        html = f.read()

    # 仅静态版加 noindex（本地 panel.html 不动）
    html = html.replace(
        '<meta charset="utf-8">',
        '<meta charset="utf-8">\n<meta name="robots" content="noindex,nofollow">',
        1,
    )
    head_extra = ""
    if supabase_url and anon_key:
        cfg = json.dumps({"supabaseUrl": supabase_url, "anonKey": anon_key}, ensure_ascii=False)
        head_extra += f"<script>window.__GEO_CONFIG__ = {cfg};</script>\n"
    shim = SHIM.replace("__GEO_DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("</head>", head_extra + shim + "</head>", 1)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    mode = "supabase-config + snapshot" if (supabase_url and anon_key) else "snapshot-only"
    print(f"wrote {out_path} ({len(html)} bytes, {len(data)} api payloads embedded, mode={mode})")


if __name__ == "__main__":
    args = sys.argv[1:]
    url = os.environ.get("GEO_SUPABASE_URL")
    key = os.environ.get("GEO_SUPABASE_ANON_KEY")
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--supabase-url" and i + 1 < len(args):
            url = args[i + 1]; i += 2
        elif args[i] == "--anon-key" and i + 1 < len(args):
            key = args[i + 1]; i += 2
        else:
            positional.append(args[i]); i += 1
    out = positional[0] if positional else os.path.join(BASE, "dist", "geo", "index.html")
    build(out, url, key)
