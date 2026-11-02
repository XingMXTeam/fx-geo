"""GSC collector 骨架：只检查本地 token 文件是否存在，不调用 Google API。

状态（2026-11-02 实测）：~/.config/mcp-gsc/token.json 不存在（目录为空），
client_secrets 在 ~/.config/gsc-mcp/client_secrets.json。
重授权完成后 token 放回 TOKEN_PATH，本检查即返回 connected_local_file，
届时再接 ~/workspace/gsc-analyze.py 的拉取逻辑做每日 cron。
"""
import json
import os

TOKEN_PATH = os.path.expanduser("~/.config/mcp-gsc/token.json")
CLIENT_SECRETS_PATH = os.path.expanduser("~/.config/gsc-mcp/client_secrets.json")


def status():
    token_exists = os.path.exists(TOKEN_PATH)
    secrets_exists = os.path.exists(CLIENT_SECRETS_PATH)
    if token_exists:
        state, detail = "ready", "token 文件存在，可尝试拉取（Testing 应用 refresh 约 7 天失效，以首次真实调用为准）"
    else:
        state = "not_connected"
        detail = "token.json 不存在，无法拉取"
        if secrets_exists:
            detail += "；client_secrets 尚在，重授权不用重建应用"
    return {"source": "gsc", "status": state,
            "token_file_exists": token_exists,
            "client_secrets_exists": secrets_exists,
            "detail": detail}


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=2))
