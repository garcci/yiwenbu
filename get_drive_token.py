#!/usr/bin/env python3
"""一次性在你自己电脑上运行，拿到谷歌云盘的刷新令牌，并直接用 gh 写进仓库 Secrets。

用法：
  pip install google-auth-oauthlib
  python get_drive_token.py client_secret.json            # 默认写进 garcci/yiwenbu
  python get_drive_token.py client_secret.json owner/repo
浏览器会弹出谷歌登录，选你的账号并允许访问云盘。装了已登录的 gh 时自动设置3个 Secrets，
没设上的会把值打印出来，手动填进 GitHub 仓库 Settings → Secrets and variables → Actions。
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

failed = {}
for name, val in values.items():
    if not val:
        print(f"{name} 是空的：谷歌没有返回这个值。请在谷歌账号的“第三方应用访问权限”里移除“异闻簿”后重跑。")
        failed[name] = val
        continue
    if not shutil.which("gh"):
        failed[name] = val
        continue
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", val], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"已设置 {repo} 的 {name}")
    else:
        print(f"设置 {name} 失败：{(r.stderr or r.stdout).strip()}")
        failed[name] = val

if failed:
    print("\n下面这些没设上，请手动填进 GitHub 仓库 Settings → Secrets and variables → Actions（不用重新授权）：\n")
    for name, val in failed.items():
        print(f"{name} = {val}")
else:
    print("\n完成。可以删掉 client_secret.json 了。")
