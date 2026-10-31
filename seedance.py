#!/usr/bin/env python3
"""火山方舟 Seedance 图生视频（按量付费，从账户余额扣钱，不在 Agent Plan 套餐里）。

- 接口：/api/v3/contents/generations/tasks（不是套餐的 /api/plan/v3）
- Key：方舟「API Key 管理」里建的普通 Key，放在 ARK_PAYG_API_KEY；套餐 Key 调这里会 401
- 模型：SEEDANCE_MODEL，默认 doubao-seedance-1-0-pro-fast-251015（2.x 系列要余额满200元才能开通）
- 价格：1.0 pro fast 4.2 元/百万 token；720p 5 秒约 10.4 万 token ≈ 0.44 元（2026-10-31 实测）
"""
import base64, io, math, os, time

import requests
from PIL import Image

BASE = (os.environ.get("ARK_PAYG_BASE") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
MODEL = os.environ.get("SEEDANCE_MODEL") or "doubao-seedance-1-0-pro-fast-251015"
RES = os.environ.get("SEEDANCE_RES") or "720p"
PRICE = float(os.environ.get("SEEDANCE_PRICE") or 4.2)  # 元/百万 token，只用于打印估算
STYLE = "，镜头稳定，动作缓慢自然，真人实拍质感，不出现文字"
spent = 0.0  # 本次运行累计估算花费


def _key():
    return (os.environ.get("ARK_PAYG_API_KEY") or os.environ["ARK_API_KEY"]).strip()


def _data_url(path):
    img = Image.open(path).convert("RGB")
    img.thumbnail((1080, 1920))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def seconds_for(dur):
    """旁白多长就生成多长（2~12 秒），不用倒放凑时长。"""
    return max(2, min(12, math.ceil(dur)))


def gen(frame, out, prompt, seconds=5, res=None, model=None):
    """以 frame 为首帧生成视频写到 out；成功返回 True，失败返回 False（调用方退回推拉）。"""
    global spent
    h = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    body = {"model": model or MODEL,
            "content": [{"type": "text", "text": prompt + STYLE},
                        {"type": "image_url", "image_url": {"url": _data_url(frame)}, "role": "first_frame"}],
            "resolution": res or RES, "ratio": "adaptive", "duration": int(seconds), "watermark": False}
    task = None
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE}/contents/generations/tasks", headers=h, json=body, timeout=120)
            if r.ok:
                task = r.json()["id"]
                break
            print(f"    Seedance 提交返回 {r.status_code}：{r.text[:300]}")
            if r.status_code in (400, 401, 403, 404):
                return False  # 参数、Key、权限、模型问题，重试也没用
        except requests.RequestException as e:
            print(f"    Seedance 网络错误：{e}")
        time.sleep(5 * (attempt + 1))
    if not task:
        return False
    for _ in range(90):  # 最多等 15 分钟
        time.sleep(10)
        try:
            q = requests.get(f"{BASE}/contents/generations/tasks/{task}", headers=h, timeout=60).json()
        except (requests.RequestException, ValueError) as e:
            print(f"    Seedance 查询出错，继续等：{e}")
            continue
        st = q.get("status")
        if st == "succeeded":
            try:
                v = requests.get(q["content"]["video_url"], timeout=300)
                v.raise_for_status()
            except requests.RequestException as e:
                print(f"    Seedance 下载失败：{e}")
                return False
            out.write_bytes(v.content)
            tokens = (q.get("usage") or {}).get("total_tokens") or 0
            cost = tokens / 1e6 * PRICE
            spent += cost
            print(f"    Seedance {seconds}秒 {res or RES}：{tokens} token，约 {cost:.2f} 元（累计 {spent:.2f} 元）")
            return True
        if st in ("failed", "expired", "cancelled"):
            print(f"    Seedance 任务失败：{str(q)[:300]}")
            return False
    print("    Seedance 等待超时")
    return False
