#!/usr/bin/env python3
"""一次性在你自己电脑上运行，拿到谷歌云盘的刷新令牌（GDRIVE_REFRESH_TOKEN）。

用法：
  pip install google-auth-oauthlib
  python get_drive_token.py client_secret.json
浏览器会弹出谷歌登录，选你的账号并允许访问云盘；终端会打印3个值，分别填进 GitHub Secrets。
"""
import json, sys

from google_auth_oauthlib.flow import InstalledAppFlow

if len(sys.argv) != 2:
    sys.exit("用法：python get_drive_token.py client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=["https://www.googleapis.com/auth/drive"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")
print("\n把下面3行分别填进 GitHub 仓库 Settings → Secrets and variables → Actions：\n")
print("GDRIVE_CLIENT_ID     =", client["client_id"])
print("GDRIVE_CLIENT_SECRET =", client["client_secret"])
print("GDRIVE_REFRESH_TOKEN =", creds.refresh_token)
