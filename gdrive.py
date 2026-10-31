#!/usr/bin/env python3
"""把成片、音频、封面直接写进谷歌云盘（免费，用你自己的云盘空间）。

需要4个环境变量（在 GitHub Secrets 里配置，获取方法见 get_drive_token.py）：
  GDRIVE_CLIENT_ID / GDRIVE_CLIENT_SECRET / GDRIVE_REFRESH_TOKEN / GDRIVE_FOLDER_ID
没配置时自动跳过，不影响出片。

同名文件会被覆盖更新，云盘里永远只有最终版。
"""
import mimetypes, os
from pathlib import Path

import requests

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"


def enabled():
    return all(os.environ.get(k) for k in
               ["GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN", "GDRIVE_FOLDER_ID"])


def _token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["GDRIVE_CLIENT_ID"],
        "client_secret": os.environ["GDRIVE_CLIENT_SECRET"],
        "refresh_token": os.environ["GDRIVE_REFRESH_TOKEN"],
        "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _find(h, name, parent, mime=None):
    q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and '{parent}' in parents and trashed = false"
    if mime:
        q += f" and mimeType = '{mime}'"
    r = requests.get(API, headers=h, params={"q": q, "fields": "files(id)", "pageSize": 1}, timeout=30)
    r.raise_for_status()
    files = r.json()["files"]
    return files[0]["id"] if files else None


def _folder(h, path):
    """按 "a/b/c" 逐级找或建子文件夹，返回最后一级的 id。"""
    parent = os.environ["GDRIVE_FOLDER_ID"]
    for name in [p for p in path.split("/") if p]:
        fid = _find(h, name, parent, FOLDER)
        if not fid:
            r = requests.post(API, headers=h, json={"name": name, "mimeType": FOLDER, "parents": [parent]},
                              params={"fields": "id"}, timeout=30)
            r.raise_for_status()
            fid = r.json()["id"]
        parent = fid
    return parent


def _put(h, path, parent):
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    existing = _find(h, path.name, parent)
    meta = {"name": path.name} if existing else {"name": path.name, "parents": [parent]}
    url = f"{UPLOAD}/{existing}" if existing else UPLOAD
    method = requests.patch if existing else requests.post
    # 断点续传接口：适合几百MB的长合集
    r = method(url, headers={**h, "X-Upload-Content-Type": mime}, json=meta,
               params={"uploadType": "resumable", "fields": "id"}, timeout=60)
    r.raise_for_status()
    with open(path, "rb") as f:
        r2 = requests.put(r.headers["Location"], headers={"Content-Type": mime}, data=f, timeout=3600)
    r2.raise_for_status()
    return "更新" if existing else "新建"


def upload(paths, subfolder):
    """把一组本地文件传到 GDRIVE_FOLDER_ID 下的 subfolder（如 "第01集"）。"""
    if not enabled():
        print("未配置云盘密钥，跳过上传")
        return
    h = {"Authorization": f"Bearer {_token()}"}
    parent = _folder(h, subfolder)
    for p in map(Path, paths):
        if p.exists():
            print(f"  云盘{_put(h, p, parent)}：{subfolder}/{p.name}")
