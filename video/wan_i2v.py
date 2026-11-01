"""万相图生视频：读 video/wan_request.json，从云盘取首帧图，调用阿里云百炼，成片写回云盘。
只用免费额度：请在百炼控制台打开“免费额度用完即停”，额度不足时接口报错，脚本直接退出，不重试。"""
import base64, io, json, os, sys, time
from pathlib import Path
import requests
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gdrive

req = json.load(open("video/wan_request.json", encoding="utf-8"))
KEY = os.environ["DASHSCOPE_API_KEY"].strip()
BASE = "https://dashscope.aliyuncs.com/api/v1"

h = {"Authorization": f"Bearer {gdrive._token()}"}
r = requests.get(f"{gdrive.API}/{req['image_file_id']}", headers=h, params={"alt": "media"}, timeout=120)
r.raise_for_status()
im = Image.open(io.BytesIO(r.content)).convert("RGB")
print("首帧原图尺寸", im.size)
im.thumbnail((1080, 1920))
buf = io.BytesIO(); im.save(buf, "JPEG", quality=92)
img = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

task = None
for model in req["models"]:
    params = {"resolution": req.get("resolution", "720P"), "duration": req.get("duration", 5),
              "prompt_extend": False, "audio": False}
    if model.startswith("wan3"):  # 万相3.0：首帧放在 media 里；免费额度30秒（仅北京地域，wan3.0-video 和 -prime 共用）
        body = {"model": model, "input": {"prompt": req["prompt"], "media": [{"type": "first_frame", "url": img}]},
                "parameters": {**params, "ratio": "adaptive"}}
    else:
        body = {"model": model, "input": {"prompt": req["prompt"], "img_url": img}, "parameters": params}
    if req.get("negative_prompt"):
        body["input"]["negative_prompt"] = req["negative_prompt"]
    r = requests.post(f"{BASE}/services/aigc/video-generation/video-synthesis", json=body, timeout=120,
                      headers={"Authorization": f"Bearer {KEY}", "X-DashScope-Async": "enable"})
    print(model, r.status_code, r.text[:300])
    if r.ok and r.json().get("output", {}).get("task_id"):
        task = r.json()["output"]["task_id"]; break
    if "Arrearage" in r.text or "quota" in r.text.lower() or "FreeTier" in r.text:
        sys.exit("免费额度不足或已用完，停止，不产生费用。")
if not task:
    sys.exit("所有模型都没能创建任务")

for _ in range(80):  # 最多20分钟
    time.sleep(15)
    s = requests.get(f"{BASE}/tasks/{task}", headers={"Authorization": f"Bearer {KEY}"}, timeout=60).json()
    st = s.get("output", {}).get("task_status")
    print("状态", st)
    if st == "SUCCEEDED":
        url = s["output"]["video_url"]; break
    if st in ("FAILED", "CANCELED", "UNKNOWN"):
        sys.exit(f"生成失败：{json.dumps(s, ensure_ascii=False)[:500]}")
else:
    sys.exit("超时")
print("用量", json.dumps(s.get("usage", {}), ensure_ascii=False))
out = Path("video") / req["out_name"]
out.write_bytes(requests.get(url, timeout=300).content)
print("视频大小", out.stat().st_size)
print("云盘" + gdrive._put(h, out, req["drive_folder_id"]), out.name)
