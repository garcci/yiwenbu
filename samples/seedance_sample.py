#!/usr/bin/env python3
"""Seedance 图生视频小样：用定妆图当首帧，每段 5 秒 720p，成片写进云盘「小样/<name>」。

  python samples/seedance_sample.py samples/seedance.json

走火山方舟按量付费接口（/api/v3，从账户余额扣钱，不在 Agent Plan 套餐里）。
模型 ID 可用环境变量 SEEDANCE_FAST_MODEL / SEEDANCE_MINI_MODEL 覆盖；没写时按候选列表依次试，
模型不存在或没开通的报错不收费。
"""
import base64, io, json, os, sys, time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gdrive  # noqa: E402

BASE = (os.environ.get("ARK_PAYG_BASE") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
MODELS = {
    "fast": [m for m in [os.environ.get("SEEDANCE_FAST_MODEL"),
                         "doubao-seedance-1-0-pro-fast-251015", "doubao-seedance-1-0-pro-fast"] if m],
    "mini": [m for m in [os.environ.get("SEEDANCE_MINI_MODEL"),
                         "doubao-seedance-2-0-mini-260615", "doubao-seedance-2-0-mini"] if m],
}
PRICE = {"fast": 4.2, "mini": 23.0}  # 元/百万 token（720p、无视频输入，官方刊例价）
H = {"Authorization": f"Bearer {os.environ['ARK_API_KEY'].strip()}", "Content-Type": "application/json"}


def data_url(path):
    img = Image.open(ROOT / path).convert("RGB")
    img.thumbnail((1080, 1920))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def submit(model, prompt, image):
    """先用顶层参数提交；老模型不认顶层参数时改成写在提示词末尾的 --rs/--dur 写法。"""
    content = [{"type": "image_url", "image_url": {"url": image}, "role": "first_frame"}]
    tries = [
        {"model": model, "content": [{"type": "text", "text": prompt}] + content,
         "resolution": "720p", "ratio": "adaptive", "duration": 5, "watermark": False},
        {"model": model, "content": [{"type": "text", "text": prompt + " --rs 720p --rt adaptive --dur 5 --wm false"}]
         + content},
    ]
    last = None
    for body in tries:
        r = requests.post(f"{BASE}/contents/generations/tasks", headers=H, json=body, timeout=120)
        if r.ok:
            return r.json()["id"], None
        last = f"{r.status_code} {r.text[:400]}"
        print(f"    提交返回 {last}")
        if "NotFound" in r.text or "not found" in r.text.lower() or "NotOpen" in r.text \
                or r.status_code in (401, 403, 404):
            break  # 模型 ID 不对 / 没开通 / 欠费：换下一个模型 ID，别再试参数写法
    return None, last


def wait(task):
    for _ in range(90):  # 最多等 15 分钟
        time.sleep(10)
        q = requests.get(f"{BASE}/contents/generations/tasks/{task}", headers=H, timeout=60).json()
        st = q.get("status")
        if st == "succeeded":
            return q
        if st in ("failed", "expired", "cancelled"):
            print(f"    任务失败：{json.dumps(q, ensure_ascii=False)[:400]}")
            return None
    print("    等待超时")
    return None


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = ROOT / "work" / "seedance"
    work.mkdir(parents=True, exist_ok=True)
    outs, total, errors = [], 0.0, []
    for clip in spec["clips"]:
        print(f"== {clip['file']}")
        image = data_url(clip["image"])
        task, used = None, None
        for model in MODELS[clip["tier"]]:
            print(f"  试模型 {model}")
            task, err = submit(model, clip["prompt"], image)
            if task:
                used = model
                break
            errors.append(f"{clip['file']} / {model}: {err}")
        if not task:
            continue
        q = wait(task)
        if not q:
            errors.append(f"{clip['file']} / {used}: 任务失败")
            continue
        out = work / clip["file"]
        try:
            v = requests.get(q["content"]["video_url"], timeout=300)
            v.raise_for_status()
        except requests.RequestException as e:
            errors.append(f"{clip['file']} / {used}: 下载失败 {e}")
            continue
        out.write_bytes(v.content)
        tokens = (q.get("usage") or {}).get("total_tokens") or 0
        cost = tokens / 1e6 * PRICE[clip["tier"]]
        total += cost
        print(f"  完成：{used}，{tokens} token，约 {cost:.2f} 元")
        outs.append(out)
    print(f"合计约 {total:.2f} 元，成功 {len(outs)}/{len(spec['clips'])} 段")
    if outs:
        gdrive.upload(outs, f"小样/{spec['name']}")
    if errors:
        print("出错：\n" + "\n".join(errors))
    if len(outs) < len(spec["clips"]):
        sys.exit(1)


main()
