"""审计 collector 骨架：封装已有的 geo-optimizer 本地运行方式，只做路径存在性检查。

已验证的本地跑法（2026-11-02，见 goals/1/hidden_files/geo-p0/audit-2026-11-02/RUN-NOTES.md）：
- 工具副本：~/workspace/geo-optimizer-recon（geo-optimizer-skill 4.18.3）
- venv：~/workspace/geo-p0/venv（pip install -e 副本），CLI 入口 `geo`
- 沙箱坑：DNS 把公网域名解析到 198.18.0.0/15 fake-IP，工具 anti-SSRF 会误判，
  必须经本地 runner ~/workspace/geo-p0/run_geo_local.py 在进程内放行 198.18/15 再调，
  不能直接调 `geo audit`。后续 CI/定时审计都带这个 runner。
- 命令形态：run_geo_local.py --lang en audit --url <site> --format json
"""
import json
import os

PATHS = {
    "tool_repo": os.path.expanduser("~/workspace/geo-optimizer-recon"),
    "venv_geo_cli": os.path.expanduser("~/workspace/geo-p0/venv/bin/geo"),
    "local_runner": os.path.expanduser("~/workspace/geo-p0/run_geo_local.py"),
}


def status():
    checks = {name: os.path.exists(p) for name, p in PATHS.items()}
    return {"source": "audit",
            "status": "ready" if all(checks.values()) else "partial",
            "paths": PATHS, "paths_exist": checks,
            "command_template": "run_geo_local.py --lang en audit --url <site> --format json",
            "note": "审计分是卫生分，不预测引用；结果写入 audits 表"}


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=2))
