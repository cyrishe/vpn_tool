"""Private JSON stdin/stdout protocol for the local macOS application."""
import argparse
import json
import subprocess
import sys
import urllib.error
import uuid
from pathlib import Path

from .cli import Client


def main():
    payload = json.load(sys.stdin)
    pilot = Path(payload["pilot_dir"])
    args = argparse.Namespace(control_url=payload["control_url"], ca_cert=payload["ca_cert"],
        state_dir=str(pilot / "client"), credentials=str(pilot / "client.json"),
        region=payload.get("region", "shanghai"), gui=True)
    action = payload["action"]
    if action in ("login", "pilot_login"):
        client = Client(args)
        if action == "pilot_login":
            if Path(args.credentials).stat().st_mode & 0o077:
                raise ValueError("联调凭证权限不正确。")
            account = json.loads(Path(args.credentials).read_text())
        else:
            account = {"email": payload["email"], "password": payload["password"]}
        login = client.request("/v1/auth/login", account)
        client.token = login["access_token"]
        return {"token": client.token, "user": login["user"], "regions": client.request("/v1/regions")}
    if payload["email"] != "poc@example.invalid":
        account_id = str(uuid.UUID(payload["user_id"]))
        args.state_dir = str(Path.home() / "Library/Application Support/Regional VPN" / account_id)
    client = Client(args)
    client.token = payload["token"]
    if action == "regions":
        return {"regions": client.request("/v1/regions")}
    if action == "connect":
        return client.connect()
    if action == "disconnect":
        return client.disconnect()
    raise ValueError("未知操作。")


if __name__ == "__main__":
    try:
        response = {"ok": True, "data": main()}
    except urllib.error.HTTPError as error:
        try:
            message = json.load(error)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = f"服务器请求失败（HTTP {error.code}）。"
        response = {"ok": False, "error": message}
    except urllib.error.URLError:
        response = {"ok": False, "error": "无法连接中心服务器，请检查网络或服务器状态。"}
    except subprocess.CalledProcessError as error:
        details = error.stderr or ""
        response = {"ok": False, "error": "已取消系统授权。" if "(-128)" in details else "系统隧道操作失败，请检查 WireGuard 和管理员授权。"}
    except (ValueError, RuntimeError) as error:
        response = {"ok": False, "error": str(error)}
    except Exception:
        response = {"ok": False, "error": "客户端无法完成操作，请检查安装与本地配置。"}
    print(json.dumps(response, ensure_ascii=False))
