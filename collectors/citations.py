"""AI 采样 collector 骨架：只检查 provider key 环境变量是否存在（只看存在性，永不打印值），
不真调用任何 provider API。

- GEMINI_API_KEY：2026-11-02 冒烟时 generativelanguage.googleapis.com 本 VM 无响应，
  网络层未通，key 未被验证（不记无效）。该 host 2026-10-25 曾在本沙箱直连成功，可择时重试。
- PERPLEXITY_API_KEY：通道已实测可达（无 key 返回 401），待用户配 key。
key 经 .env 或安全录入注入环境变量后，本检查返回 key_present，再接 geo citations 实跑。
"""
import json
import os

PROVIDERS = {
    "gemini": "GEMINI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}


def status():
    out = {}
    for provider, env_name in PROVIDERS.items():
        present = bool(os.environ.get(env_name))
        out[provider] = {
            "env": env_name,
            "key_present": present,
            "status": "key_present" if present else "not_configured",
        }
    out["gemini"]["note"] = "API host 本 VM 当前无响应（2026-11-02 实测），即使 key 存在也需先重试冒烟"
    out["perplexity"]["note"] = "通道已实测可达，配 key 即可跑 geo citations"
    return {"source": "citations", "providers": out}


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=2))
