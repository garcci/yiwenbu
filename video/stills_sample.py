"""第一集低成本小样：火山套餐 Seedream 出连续多帧 → 深度图分层视差 + 快切 + 雪/灯光特效 + 豆包配音 + 合成音效。
不调用任何按量付费的视频模型。读 video/stills_request.json，成片写回云盘。"""
import base64, io, json, math, os, subprocess, sys, time, wave
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gdrive

REQ = json.load(open(ROOT / "video/stills_request.json", encoding="utf-8"))
W, H, FPS, SR = 1080, 1920, 30, 24000
WORK = ROOT / "work/stills"; WORK.mkdir(parents=True, exist_ok=True)
ARK = "https://ark.cn-beijing.volces.com/api/plan/v3"
KEY = os.environ.get("ARK_API_KEY", "").strip()
FONT = next((p for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                         "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"] if os.path.exists(p)), None)


def drive_image(fid):
    out = WORK / f"ref_{fid}.jpg"
    if not out.exists():
        r = requests.get(f"{gdrive.API}/{fid}", headers={"Authorization": f"Bearer {gdrive._token()}"},
                         params={"alt": "media"}, timeout=120)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB"); im.thumbnail((1440, 2560))
        im.save(out, quality=92)
    return out


def data_url(p):
    return "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()


def seedream(prompt, out, refs):
    if out.exists():
        return out
    if not KEY:  # 本地离线试跑：灰色占位图
        Image.new("RGB", (1440, 2560), (60, 64, 70)).save(out); return out
    body = {"model": os.environ.get("SEEDREAM_MODEL", "doubao-seedream-5.0-pro"), "prompt": prompt,
            "size": "1440x2560", "response_format": "b64_json", "watermark": False}
    if refs:
        body["image"] = [data_url(p) for p in refs]
    for attempt in range(4):
        r = requests.post(f"{ARK}/images/generations", json=body, timeout=240,
                          headers={"Authorization": f"Bearer {KEY}"})
        if r.ok:
            Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"]))).convert("RGB").save(out, quality=95)
            print("  出图", out.name); return out
        print("  Seedream", r.status_code, r.text[:300]); time.sleep(6 * (attempt + 1))
    sys.exit("Seedream 出图失败")


def tts(text, out, speaker):
    if out.exists():
        return out
    if not KEY:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
                        "-t", str(len(text) * 0.27), str(out)], check=True); return out
    h = {"X-Api-Key": KEY, "Authorization": f"Bearer {KEY}", "X-Api-Resource-Id": "seed-tts-2.0",
         "Content-Type": "application/json"}
    req = {"text": text, "speaker": speaker, "audio_params": {"format": "mp3", "sample_rate": SR, "speech_rate": -8},
           "additions": json.dumps({"context_texts": [REQ.get("voice_style", "")]}, ensure_ascii=False)}
    for attempt in range(4):
        r = requests.post("https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional", headers=h,
                          json={"user": {"uid": "yiwenbu"}, "req_params": req}, stream=True, timeout=120)
        audio = b""
        for raw in r.iter_lines():
            if raw:
                j = json.loads(raw)
                if j.get("data"):
                    audio += base64.b64decode(j["data"])
        if audio:
            mp3 = out.with_suffix(".mp3"); mp3.write_bytes(audio)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(out)], check=True)
            print("  配音", text); return out
        print("  豆包配音失败", r.status_code, r.text[:200]); req.pop("additions", None); time.sleep(3)
    sys.exit("配音失败")


def read_wav(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


# ---------- 深度图：Depth Anything V2 Small（CPU 免费跑），失败就退回上远下近的渐变 ----------
_depth = None
def depth_map(img_path):
    global _depth
    out = img_path.with_suffix(".depth.npy")
    if out.exists():
        return np.load(out)
    im = Image.open(img_path).convert("RGB")
    try:
        if _depth is None:
            from transformers import pipeline
            _depth = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=-1)
        d = np.array(_depth(im)["depth"], np.float32)
    except Exception as e:
        print("  深度模型不可用，用渐变代替：", e)
        d = np.tile(np.linspace(0, 255, 256, dtype=np.float32)[:, None], (1, 144))
    d = cv2.resize(d, (W, H)); d = (d - d.min()) / (np.ptp(d) + 1e-6)   # 1 = 近
    d = cv2.GaussianBlur(d, (0, 0), 6)
    np.save(out, d); return d


def cover(img_path):
    im = Image.open(img_path).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return np.array(im.crop((x, y, x + W, y + H)), np.float32)


GX, GY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))


def parallax(img, dep, t, move):
    """t∈[0,1]；move=(横移px, 纵移px, 推近比例)。近处位移大、远处小，形成真实景深错位。"""
    mx, my, zoom = move
    k = 1.06 + zoom * t                      # 先放大一点，边缘不露底
    cx, cy = W / 2, H / 2
    near = dep - 0.5
    sx = (GX - cx) / k + cx - mx * t * near * 2
    sy = (GY - cy) / k + cy - my * t * near * 2
    return cv2.remap(img, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


class Snow:
    def __init__(self, n, seed=1):
        r = np.random.default_rng(seed)
        self.x, self.y = r.uniform(0, W, n), r.uniform(-H, H, n)
        self.z = r.uniform(0.3, 1.0, n)        # 越大越近、越大越快
        self.ph = r.uniform(0, 6.28, n)

    def draw(self, frame, t, wind=40):
        layer = np.zeros((H, W), np.float32)
        y = (self.y + t * 260 * self.z) % (H + 40) - 20
        x = (self.x + t * wind * self.z + 18 * np.sin(t * 1.3 + self.ph)) % W
        for xi, yi, zi in zip(x.astype(int), y.astype(int), self.z):
            cv2.circle(layer, (xi, yi), max(1, int(zi * 4)), 0.35 + 0.5 * zi, -1, cv2.LINE_AA)
        layer = cv2.GaussianBlur(layer, (0, 0), 1.6)
        return frame * (1 - layer[..., None] * 0.85) + layer[..., None] * 225


def grade(frame, t, flicker, seed):
    if flicker:   # 煤油灯微弱跳动：低频亮度起伏
        f = 1 + 0.035 * math.sin(t * 7.1 + seed) + 0.02 * math.sin(t * 13.7) + 0.015 * math.sin(t * 23.3 + 1)
        frame = frame * f
    noise = np.random.default_rng(int(t * 1000) + seed).normal(0, 3.2, (H // 2, W // 2)).astype(np.float32)
    frame = frame + cv2.resize(noise, (W, H))[..., None]
    # 暗角
    return frame * VIGNETTE[..., None]


_r = np.sqrt(((GX - W / 2) / (W / 2)) ** 2 + ((GY - H / 2) / (H / 2)) ** 2)
VIGNETTE = np.clip(1.08 - 0.32 * _r ** 2, 0.55, 1).astype(np.float32)


def text_layer(lines):
    """lines: [(文字, 字号, (x, y), 不透明度)] → RGBA numpy"""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for txt, size, (x, y), a in lines:
        f = ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()
        d.text((x + 2, y + 2), txt, font=f, fill=(0, 0, 0, int(160 * a)))
        d.text((x, y), txt, font=f, fill=(235, 230, 220, int(255 * a)))
    return np.array(im, np.float32) / 255


def overlay(frame, layer, alpha=1.0):
    a = layer[..., 3:4] * alpha
    return frame * (1 - a) + layer[..., :3] * 255 * a


# ---------- 音效合成（无版权） ----------
def knock(dur=0.35, seed=0):
    n = int(SR * dur); t = np.arange(n) / SR
    r = np.random.default_rng(seed)
    body = np.sin(2 * np.pi * 95 * t) * np.exp(-t * 28) + 0.5 * np.sin(2 * np.pi * 180 * t) * np.exp(-t * 45)
    click = r.normal(0, 1, n) * np.exp(-t * 160)
    click = np.convolve(click, np.ones(6) / 6, "same")
    return (0.8 * body + 0.35 * click).astype(np.float32)


def brown(n, seed, cut=1.0):
    w = np.random.default_rng(seed).normal(0, 1, n)
    b = np.cumsum(w); b -= np.convolve(b, np.ones(SR) / SR, "same")
    return (b / (np.abs(b).max() + 1e-6) * cut).astype(np.float32)


def wind(n, seed=3):
    b = brown(n, seed)
    t = np.arange(n) / SR
    env = 0.55 + 0.3 * np.sin(2 * np.pi * 0.17 * t) + 0.15 * np.sin(2 * np.pi * 0.41 * t + 1)
    return b * env * 0.5


def place(track, clip, at, gain=1.0):
    i = int(at * SR); j = min(len(track), i + len(clip))
    if i < len(track):
        track[i:j] += clip[: j - i] * gain


# ---------- 主流程 ----------
def build_shot(shot, idx):
    print(f"镜{shot['id']}")
    refs = [drive_image(f) for f in shot.get("ref_file_ids", [])]
    frames = []
    for k, fr in enumerate(shot["frames"]):
        r = list(refs) + ([frames[0]] if k and fr.get("ref_first", True) else [])
        frames.append(seedream(fr["prompt"], WORK / f"s{shot['id']}_{k}.jpg", r))
    imgs = [cover(p) for p in frames]
    deps = [depth_map(p) for p in frames]

    # 配音并排时间轴
    lines = []
    for ln in shot["voice"]:
        wav = tts(ln["text"], WORK / f"v{shot['id']}_{len(lines)}.wav", REQ["speaker"])
        lines.append((ln["at"], read_wav(wav)))
    dur = shot["duration"]
    n = int(dur * SR)
    voice = np.zeros(n, np.float32); sfx = np.zeros(n, np.float32)
    for at, a in lines:
        place(voice, a, at)
    if shot.get("wind"):
        sfx += wind(n) * 0.35
    sfx += brown(n, 11 + idx) * 0.04          # 室内/室外底噪
    for k, at in enumerate(shot.get("knocks", [])):
        place(sfx, knock(seed=k), at, 0.9)
    mix = voice * 1.0 + sfx
    mix = mix / max(1.0, np.abs(mix).max() / 0.95)
    wav_out = WORK / f"a{shot['id']}.wav"
    with wave.open(str(wav_out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())

    texts = [(t["from"], t["to"], text_layer([(t["text"], t["size"], tuple(t["pos"]), 1.0)])) for t in shot.get("texts", [])]
    snow = Snow(260) if shot.get("snow") else None
    shakes = shot.get("knocks", []) if shot.get("shake") else []

    mp4 = WORK / f"m{shot['id']}.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav_out),
                          "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "160k", "-shortest", str(mp4)], stdin=subprocess.PIPE)
    segs = shot["cuts"]   # [{"frame":0,"from":0,"to":3,"move":[mx,my,zoom]}]
    for fi in range(int(dur * FPS)):
        t = fi / FPS
        sg = next(s for s in segs if s["from"] <= t < s["to"] or s is segs[-1])
        u = (t - sg["from"]) / max(0.01, sg["to"] - sg["from"])
        u = u * u * (3 - 2 * u)                       # 缓入缓出
        f = parallax(imgs[sg["frame"]], deps[sg["frame"]], u, sg["move"])
        # 交叉溶解（如设定）
        if sg.get("dissolve_in") and t - sg["from"] < sg["dissolve_in"]:
            prev = segs[segs.index(sg) - 1]
            pf = parallax(imgs[prev["frame"]], deps[prev["frame"]], 1.0, prev["move"])
            a = (t - sg["from"]) / sg["dissolve_in"]
            f = pf * (1 - a) + f * a
        for at in shakes:                              # 敲门时画面极轻一震、压暗一下
            if 0 <= t - at < 0.12:
                M = np.float32([[1, 0, 0], [0, 1, 5 * math.sin((t - at) * 80)]])
                f = cv2.warpAffine(f, M, (W, H), borderMode=cv2.BORDER_REFLECT) * 0.9
        if snow:
            f = snow.draw(f, t)
        f = grade(f, t, shot.get("flicker", False), idx)
        for a, b, lay in texts:
            if a <= t < b:
                fade = min(1, (t - a) / 0.4, (b - t) / 0.4)
                f = overlay(f, lay, fade)
        if shot.get("fade_in") and t < shot["fade_in"]:
            f *= t / shot["fade_in"]
        p.stdin.write(np.clip(f, 0, 255).astype(np.uint8).tobytes())
    p.stdin.close(); p.wait()
    return mp4


def main():
    parts = [build_shot(s, i) for i, s in enumerate(REQ["shots"])]
    lst = WORK / "list.txt"; lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    final = WORK / REQ["out_name"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(final)], check=True, cwd=WORK)
    print("成片", final, f"{final.stat().st_size / 1e6:.1f}MB")
    if KEY and os.environ.get("GDRIVE_REFRESH_TOKEN"):
        print("云盘" + gdrive._put({"Authorization": f"Bearer {gdrive._token()}"}, final, REQ["drive_folder_id"]), final.name)


if __name__ == "__main__":
    main()
