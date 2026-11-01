"""AI 开场预览；默认仅校验，--execute 才调用已核查的套餐接口。"""
import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("request.json")
TTS_URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
IMAGE_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
EXPECTED_TEXT = ["砚儿——借个火。", "哎。", "话一出口，我后背就凉了。我爷爷，是前天夜里死的。"]
SR = 24000


def validate(cfg, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if cfg.get("tts_overage_disabled") is not True or cfg.get("actions_spending_blocked") is not True:
        raise ValueError("零新增费用核查未通过")
    if now >= dt.datetime.fromisoformat(cfg["cost_check_expires_utc"]):
        raise ValueError("成本核查已过期，须重新只读核查后更新")
    if cfg["narrator"] != "zh_male_taocheng_uranus_bigtts" or cfg["speech_rate"] != -5:
        raise ValueError("必须保持用户选定的D旁白参数")
    if [x["text"] for x in cfg["opening"]] != EXPECTED_TEXT:
        raise ValueError("开场实读台词不等于配音稿v3")
    if len(cfg["frames"]) != 3 or len(cfg["reference_ids"]) != 2 or cfg["target_seconds"] != 15:
        raise ValueError("本批次只能生成三帧和约15秒预览")
    if cfg["folder_id"] != "11uMWY64q_tLolJ210NmLhfqnkW1D5fBR":
        raise ValueError("云盘目标不匹配")
    if cfg["opening"][1]["speaker"] != cfg["narrator"] or cfg["opening"][2]["speaker"] != cfg["narrator"]:
        raise ValueError("沈砚必须使用用户选定的D")
    return cfg


def post(url, payload, headers):
    # 固定套餐端点；不自动重试，不回退到按量付费，不记录响应体或密钥。
    if url not in (TTS_URL, IMAGE_URL):
        raise ValueError("禁止其他模型端点")
    import requests
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=(30, 360))
    except requests.RequestException as exc:
        print("套餐网络失败类型：", type(exc).__name__, flush=True)
        raise RuntimeError("套餐网络请求失败；保留已完成素材") from None
    if not response.ok:
        print("套餐HTTP状态：", response.status_code, flush=True)
        raise RuntimeError("套餐请求失败；停止，不切换计费路径")
    return io.BytesIO(response.content)


def download_drive(fid, headers):
    import requests
    response = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}",
                            params={"alt": "media"}, headers=headers, timeout=(30, 90))
    response.raise_for_status()
    return response.content


def restore_audio(cfg, headers, work):
    resume = cfg.get("resume")
    if not resume:
        return None
    blob = download_drive(resume["file_id"], headers)
    if hashlib.sha256(blob).hexdigest() != resume["sha256"]:
        raise ValueError("续跑素材包摘要不匹配")
    allowed = {"grandfather.wav", "shen.wav", "narrator.wav", "opening.wav", "opening.srt", "opening.ass",
               "resume.json", "06-第一集借火-开场配音待验收.mp3"}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if set(archive.namelist()) != allowed or sum(x.file_size for x in archive.infolist()) > 20_000_000:
            raise ValueError("续跑包文件清单异常")
        metadata = json.loads(archive.read("resume.json"))
        fields = {k: cfg[k] for k in ("narrator", "speech_rate", "narrator_style", "opening")}
        signature = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if signature != metadata["voice_signature"]:
            raise ValueError("续跑素材与当前音色或台词不符")
        for name in allowed:
            (work / name).write_bytes(archive.read(name))
    return metadata


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def seconds(path):
    with wave.open(str(path), "rb") as f:
        return f.getnframes() / f.getframerate()


def voice(item, cfg, key, work):
    payload = {"user": {"uid": "yiwenbu"}, "req_params": {
        "text": item["text"], "speaker": item["speaker"],
        "audio_params": {"format": "mp3", "sample_rate": SR, "speech_rate": cfg["speech_rate"]},
        "additions": json.dumps({"context_texts": [item.get("style", cfg["narrator_style"])]}, ensure_ascii=False)}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
               "X-Api-Key": key, "X-Api-Resource-Id": "seed-tts-2.0"}
    data = bytearray()
    with post(TTS_URL, payload, headers) as response:
        for line in response:
            if line.strip():
                part = json.loads(line)
                if part.get("data"):
                    data.extend(base64.b64decode(part["data"], validate=True))
                if part.get("code", 0) not in (0, 20000000):
                    raise RuntimeError("语音服务返回失败；停止，不重试")
    if not data:
        raise RuntimeError("语音没有返回有效音频")
    src = work / (item["id"] + ".mp3")
    src.write_bytes(data)
    dst = src.with_suffix(".wav")
    ff("-i", src, "-ac", 1, "-ar", SR, "-c:a", "pcm_s16le", dst)
    if seconds(dst) < 0.08:
        raise RuntimeError("音频长度异常")
    return dst


def mix_audio(cfg, clips, work):
    import numpy as np
    at = 1.4  # 先静后敲：三次轻敲，不用压低变声或回声。
    events = []
    for item, clip in zip(cfg["opening"], clips):
        end = at + seconds(clip)
        events.append({"role": item["role"], "text": item["text"], "start": at, "end": end})
        at = end + item["gap_after"]
    duration = max(float(cfg["target_seconds"]), at)
    if duration > 22:
        raise RuntimeError("自然语速超出22秒，停止并人工调整，不截字不强拉语速")
    track = np.zeros(math.ceil(duration * SR), dtype=np.float64)
    for event, clip in zip(events, clips):
        with wave.open(str(clip), "rb") as f:
            samples = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(float) / 32768
        start = round(event["start"] * SR)
        track[start:start + len(samples)] += samples
    for stamp in (0.25, 0.62, 0.99):
        t = np.arange(int(0.22 * SR)) / SR
        knock = (np.sin(2 * np.pi * 95 * t) * np.exp(-30 * t)
                 + 0.25 * np.sin(2 * np.pi * 180 * t) * np.exp(-45 * t)) * 0.14
        start = round(stamp * SR)
        track[start:start + len(knock)] += knock
    peak = np.abs(track).max()
    if peak > 0.95:
        track *= 0.95 / peak
    out = work / "opening.wav"
    with wave.open(str(out), "wb") as f:
        f.setparams((1, 2, SR, 0, "NONE", "not compressed"))
        f.writeframes((track * 32767).astype("<i2").tobytes())
    audio = work / "06-第一集借火-开场配音待验收.mp3"
    ff("-i", out, "-af", "loudnorm=I=-16:TP=-1.5:LRA=7", "-ar", 44100, "-b:a", "160k", audio)
    return audio, events, duration


def stamp(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def subtitles(audio, work):
    # FFmpeg解码后传numpy数组，避开上一轮PyAV metadata_errors接口错误。
    import numpy as np
    from faster_whisper import WhisperModel
    raw = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"])
    pcm = np.frombuffer(raw, dtype="<f4")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(pcm, language="zh", word_timestamps=True, vad_filter=False,
                                  initial_prompt="沈砚，爷爷，借个火。")
    rows = []
    for seg in segments:
        group, start, end = "", None, None
        for word in seg.words or []:
            if len(word.word) > 18:
                raise RuntimeError("单个转写时间块过长，须人工校对，不猜测字幕时间")
            if group and len(group + word.word) > 18:
                rows.append((start, end, group)); group, start = "", None
            start = word.start if start is None else start
            end = word.end; group += word.word
        if group:
            rows.append((start, end, group))
    if not rows:
        raise RuntimeError("转写为空，停止制作字幕")
    out = work / "opening.srt"
    out.write_text("\n\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{t.strip()}" for i, (a, b, t) in enumerate(rows, 1)) + "\n")
    ass = work / "opening.ass"
    def ass_time(t):
        cs = round(t * 100)
        return f"{cs // 360000:01}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n"
              "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV\n"
              "Style: Default,Noto Sans CJK SC,46,&H00FFFFFF,&H00000000,1,2,0,2,80,80,300\n"
              "[Events]\nFormat: Layer,Start,End,Style,Text\n")
    clean_text = lambda text: text.replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ")
    ass.write_text(header + "".join(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,{clean_text(t.strip())}\n" for a, b, t in rows))
    # 转写字词仍需人工按母稿校正；不把ASR结果宣称为正确台词。
    return ass, "".join(t for _, _, t in rows)


def frames(cfg, key, drive, headers, work):
    from PIL import Image
    def compressed_reference(raw):
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((1080, 1920))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    refs = []
    for fid in cfg["reference_ids"]:
        refs.append(compressed_reference(download_drive(fid, headers)))
    paths = []
    for i, prompt in enumerate(cfg["frames"]):
        saved = cfg.get("reuse_frames", {}).get(str(i))
        if saved:
            raw = download_drive(saved["file_id"], headers)
            if hashlib.sha256(raw).hexdigest() != saved["sha256"]:
                raise ValueError("已验收底图摘要不匹配")
            p = work / f"frame_{i}.png"
            p.write_bytes(raw); paths.append(p)
            print(f"复用已核对画面 {i + 1}/3", flush=True)
            continue
        print(f"生成画面 {i + 1}/3", flush=True)
        prompt = "1999年冀北虚构矿村，冷峻写实、低饱和灰蓝和克制暖灯，竖屏9:16，无可读文字、遗体、血腥、现代设备。" + prompt
        linked = list(refs)
        if paths:
            linked.append(compressed_reference(paths[-1].read_bytes()))
        print("参考图编码总字节数", sum(len(x) for x in linked), flush=True)
        payload = {"model": "doubao-seedream-5.0-pro", "prompt": prompt, "size": "1440x2560",
                   "response_format": "b64_json", "watermark": True, "image": linked}
        with post(IMAGE_URL, payload, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}) as response:
            result = json.load(response)
        p = work / f"frame_{i}.png"
        image = Image.open(io.BytesIO(base64.b64decode(result["data"][0]["b64_json"]))).convert("RGB")
        image.save(p); paths.append(p)
    return paths


def video(images, audio, srt, events, duration, work):
    # 三个连续画面随对白切换，加微弱普通灯光波动；不做单张图推拉。
    cuts = [events[1]["start"], events[2]["start"] + 1, duration]
    chunks = []; start = 0
    for i, (im, end) in enumerate(zip(images, cuts)):
        chunk = work / f"clip{i}.mp4"
        ff("-loop", 1, "-i", im, "-t", end-start, "-vf",
           "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=brightness='0.008*sin(t*5)':eval=frame",
           "-r", 25, "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", chunk)
        chunks.append(chunk); start = end
    manifest = work / "concat.txt"
    manifest.write_text("".join(f"file '{p.name}'\n" for p in chunks))
    base = work / "base.mp4"
    ff("-f", "concat", "-safe", 0, "-i", manifest, "-c", "copy", base)
    label = work / "ai-label.txt"; label.write_text("原创虚构｜AI画面与AI配音")
    font = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    filters = (f"drawtext=fontfile={font}:textfile={label}:fontsize=34:fontcolor=white:x=60:y=100:box=1:boxcolor=black@0.6,"
               f"subtitles={srt}")
    out = work / "06-第一集借火-15秒预览待验收.mp4"
    ff("-i", base, "-i", audio, "-vf", filters, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
       "-preset", "fast", "-crf", 20, "-c:a", "aac", "-b:a", "160k", "-t", duration, out)
    return out


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    cfg = validate(json.loads(CONFIG.read_text()))
    if not args.execute:
        print("校验通过：D旁白、最多3次TTS（续跑复用）、3帧图片、固定套餐端点；未调用接口")
        return
    required = ("ARK_API_KEY", "GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")
    if not all(os.environ.get(k, "").strip() for k in required):
        raise RuntimeError("必要凭据未配置；停止，不输出静音或灰图充数")
    sys.path.insert(0, str(ROOT))
    import gdrive
    key = os.environ["ARK_API_KEY"].strip()
    work = ROOT / "work/ep1-preview"; work.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {gdrive._token()}"}
    recovered = restore_audio(cfg, headers, work)
    print("恢复已生成音频" if recovered else "生成开场音频", flush=True)
    clips = [work / (item["id"] + ".wav") for item in cfg["opening"]] if recovered else [voice(item, cfg, key, work) for item in cfg["opening"]]
    audio, events, duration = mix_audio(cfg, clips, work)
    if recovered:
        srt = work / "opening.ass"
        transcript = recovered["raw_asr_srt"]
    else:
        print("转写实际音轨", flush=True)
        srt, transcript = subtitles(audio, work)
    images = frames(cfg, key, gdrive, headers, work)
    print("渲染预览", flush=True)
    output = video(images, audio, srt, events, duration, work)
    report = work / "06-第一集借火-预览核查.json"
    report.write_text(json.dumps({"ai_generated": True, "status": "待人工音画验收", "selected_sample": cfg["selected_sample"],
        "seconds": duration, "events": events, "asr_text": transcript, "expected_text": "".join(EXPECTED_TEXT),
        "reused_audio": bool(recovered), "subtitle_correction": recovered.get("subtitle_correction") if recovered else None,
        "note": "爷爷为临时配角音色，字幕为实际音轨转写待校对；未通过全季验收、未对外发布。",
        "video_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2))
    for p in (output, audio, report):
        with contextlib.redirect_stdout(io.StringIO()):
            gdrive._put(headers, p, cfg["folder_id"])
        fid = gdrive._find(headers, p.name, cfg["folder_id"])
        if not fid:
            raise RuntimeError("上传后未找到文件")
        print(p.name, f"https://drive.google.com/file/d/{fid}/view")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # 外部库异常可能含请求内容，日志仅输出异常类型；不回显密钥或响应。
        print("预览未完成：", type(exc).__name__, file=sys.stderr)
        sys.exit(1)
