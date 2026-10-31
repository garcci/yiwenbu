#!/usr/bin/env python3
"""一次性在你自己电脑上运行，拿到谷歌云盘的刷新令牌，并直接用 gh 写进仓库 Secrets。

用法：
  pip install google-auth-oauthlib
  python get_drive_token.py client_secret.json            # 默认写进 garcci/yiwenbu
  python get_drive_token.py client_secret.json owner/repo
浏览器会弹出谷歌登录，选你的账号并允许访问云盘。装了已登录的 gh 时自动设置3个 Secrets，
否则把打印出的3个值手动填进 GitHub 仓库 Settings → Secrets and variables → Actions。
"""
import json, shutil, subprocess, sys

from google_auth_oauthlib.flow import InstalledAppFlow

if len(sys.argv) not in (2, 3):
    sys.exit("用法：python get_drive_token.py client_secret.json [owner/repo]")
repo = sys.argv[2] if len(sys.argv) == 3 else "garcci/yiwenbu"

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=["https://www.googleapis.com/auth/drive"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")
values = {"GDRIVE_CLIENT_ID": client["client_id"],
          "GDRIVE_CLIENT_SECRET": client["client_secret"],
          "GDRIVE_REFRESH_TOKEN": creds.refresh_token}

if shutil.which("gh"):
    for name, val in values.items():
        subprocess.run(["gh", "secret", "set", name, "--repo", repo], input=val, text=True, check=True)
        print(f"已设置 {repo} 的 {name}")
    print("\n完成。可以删掉 client_secret.json 了。")
else:
    print("\n没找到 gh，请把下面3行分别填进 GitHub 仓库 Settings → Secrets and variables → Actions：\n")
    for name, val in values.items():
        print(f"{name} = {val}")
