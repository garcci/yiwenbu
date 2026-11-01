"""把 discuss/publish.txt 里列的 markdown 文件，转成谷歌文档写进指定云盘文件夹。
publish.txt 每行：本地文件路径|云盘文件夹ID|云盘文档名。同名文档覆盖更新，只留最终版。"""
import os, sys, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gdrive import _token, _find

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOC = "application/vnd.google-apps.document"

h = {"Authorization": f"Bearer {_token()}"}
for line in open("discuss/publish.txt", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    path, folder, name = [x.strip() for x in line.split("|")]
    data = open(path, "rb").read()
    existing = _find(h, name, folder, DOC)
    boundary = "xxBOUNDARYxx"
    import json
    meta = {"name": name} if existing else {"name": name, "mimeType": DOC, "parents": [folder]}
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: text/markdown; charset=UTF-8\r\n\r\n").encode() + data + f"\r\n--{boundary}--".encode()
    url = f"{UPLOAD}/{existing}" if existing else UPLOAD
    r = (requests.patch if existing else requests.post)(
        url, headers={**h, "Content-Type": f"multipart/related; boundary={boundary}"},
        params={"uploadType": "multipart", "fields": "id,webViewLink"}, data=body, timeout=120)
    if not r.ok:
        sys.exit(f"{name} 上传失败 {r.status_code} {r.text[:300]}")
    j = r.json()
    print(f"{'更新' if existing else '新建'}：{name} https://docs.google.com/document/d/{j['id']}/edit")
