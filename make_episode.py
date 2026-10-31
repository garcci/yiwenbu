#!/usr/bin/env python3
"""《异闻簿》自动出片流水线：选题 → 口播稿 → 配音 → 画面 → 字幕合成 → 上传。

全部默认走免费渠道：
  稿件  GitHub Models（Actions 里自带的 GITHUB_TOKEN 即可调用）或 Cloudflare Workers AI
  画面  Cloudflare Workers AI 的 FLUX.1 schnell（每天免费额度）
  配音  edge-tts（免费）
  存储  直接写进你的谷歌云盘（gdrive.py），同时留一份 GitHub Actions 产物

用法：
  python make_episode.py --next                      # 从 topics.json 取下一个选题，全自动出片
  python make_episode.py --episode episodes/ep01.json  # 用现成稿件出片
  每集同时输出：竖屏成片 epXX.mp4、发布文案 epXX.txt、单集音频 epXX.mp3（开头带AI声明）
  横屏长合集见 compile_long.py
  本地离线试跑：加 --images placeholder --tts silent
"""
import argparse, asyncio, base64, json, os, re, subprocess, sys, textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

ROOT = Path(__file__).resolve().parent
SERIES = json.loads((ROOT / "series.json").read_text(encoding="utf-8"))
W, H = SERIES["width"], SERIES["height"]          # 竖屏 1080×1920
HW, HH = 1920, 1080                               # 横屏（YouTube 合集）
FPS = 30
GAP = 0.25  # 句间停顿（秒）


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


# ---------------- 稿件 ----------------
def llm(prompt, provider):
    if provider == "github":
        r = requests.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                     "Content-Type": "application/json"},
            json={"model": os.environ.get("LLM_MODEL", "openai/gpt-4.1-mini"),
                  "messages": [{"role": "user", "content": prompt}], "temperature": 0.8},
            timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if provider == "cloudflare":
        model = os.environ.get("CF_LLM_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
        r = cf_run(model, {"messages": [{"role": "user", "content": prompt}], "max_tokens": 2048})
        return r.json()["result"]["response"]
    raise SystemExit(f"未知 LLM 提供方：{provider}")


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型没有返回 JSON：\n" + text[:500])
    return json.loads(m.group(0))


def write_script(topic, next_topic, provider):
    tpl = (ROOT / "episode_prompt.txt").read_text(encoding="utf-8")
    prompt = (tpl.replace("{source}", topic["source"]).replace("{summary}", topic["summary"])
                 .replace("{next_topic}", next_topic["hook"] if next_topic else "下一个古籍怪事"))
    for attempt in range(3):
        try:
            ep = parse_json(llm(prompt, provider))
            chars = sum(len(l) for s in ep["shots"] for l in s["lines"])
            if 200 <= chars <= 450 and 5 <= len(ep["shots"]) <= 10:
                return ep
            print(f"  稿件长度不合格（{chars}字/{len(ep['shots'])}镜），重写")
        except Exception as e:  # noqa: BLE001
            print(f"  第{attempt + 1}次生成失败：{e}")
    raise SystemExit("稿件生成失败")


# ---------------- 配音 ----------------
async def _edge(text, out):
    import edge_tts
    await edge_tts.Communicate(text, SERIES["voice"], rate=SERIES["voice_rate"]).save(str(out))


def tts(text, out, provider):
    if provider == "edge":
        asyncio.run(_edge(text, out))
    else:  # silent：离线试跑，按每秒4.5字估时长
        sec = max(1.2, len(text) / 4.5)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{sec:.2f}", str(out)])


# ---------------- 画面 ----------------
def cf_run(model, payload):
    acc, tok = os.environ["CF_ACCOUNT_ID"], os.environ["CF_API_TOKEN"]
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}",
                      headers={"Authorization": f"Bearer {tok}"}, json=payload, timeout=180)
    r.raise_for_status()
    return r


def gen_image(prompt, out, provider, seed):
    full = f"{prompt}, {SERIES['visual_style']}"
    if provider == "cloudflare":
        r = cf_run("@cf/black-forest-labs/flux-1-schnell", {"prompt": full, "steps": 8, "seed": seed})
        out.write_bytes(base64.b64decode(r.json()["result"]["image"]))
    else:  # placeholder：离线试跑用的素色画面
        img = Image.new("RGB", (1024, 1024), (196, 202, 204))
        d = ImageDraw.Draw(img)
        d.rectangle([60, 60, 964, 964], outline=(120, 128, 132), width=3)
        f = ImageFont.truetype(font_path(), 34)
        d.multiline_text((110, 420), "\n".join(textwrap.wrap(prompt, 44)[:6]), font=f, fill=(70, 76, 80))
        img.save(out)


def font_path():
    if SERIES.get("font_file"):
        return SERIES["font_file"]
    for p in ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]:
        if Path(p).exists():
            return p
    raise SystemExit("找不到中文字体，请安装 fonts-noto-cjk 或在 series.json 填 font_file")


def compose(src, out, w, h):
    """正方形画面放在中间，背景是同一张图的虚化放大。
    竖屏：上方标题区、下方字幕区；横屏：画面居中，字幕压在画面下沿。"""
    img = Image.open(src).convert("RGB")
    side = max(w, h)
    bg = img.resize((side, side)).crop(((side - w) // 2, (side - h) // 2, (side - w) // 2 + w, (side - h) // 2 + h))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(40))).enhance(0.45)
    if h > w:
        bg.paste(img.resize((w, w)), (0, 380))
    else:
        bg.paste(img.resize((h, h)), ((w - h) // 2, 0))
    bg.save(out, quality=95)


# ---------------- 合成 ----------------
def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(title, cues, total, outro_start, outro_text, out, w=W, h=H):
    font = os.environ.get("FONT_NAME") or SERIES.get("font_name", "Noto Sans CJK SC")
    vertical = h > w
    accent = SERIES["accent_color"].lstrip("#")
    accent_ass = f"&H00{accent[4:6]}{accent[2:4]}{accent[0:2]}"
    if vertical:
        styles = f"""Style: Series,{font},44,{accent_ass},&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,8,0,1,0,0,8,60,60,130,1
Style: Title,{font},72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,0,0,8,60,60,200,1
Style: Sub,{font},62,&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,1,0,1,4,0,2,70,70,330,1
Style: Outro,{font},40,&H00E0E0E0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,2,60,60,200,1"""
    else:  # 横屏：栏目名和本集标题放左上角，字幕在底部
        styles = f"""Style: Series,{font},34,{accent_ass},&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,6,0,1,0,0,7,50,50,40,1
Style: Title,{font},44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,1,0,1,3,0,7,50,50,90,1
Style: Sub,{font},56,&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,1,0,1,4,0,2,80,80,70,1
Style: Outro,{font},36,&H00E0E0E0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,3,0,2,60,60,150,1"""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 0,0:00:00.00,{ass_time(total)},Series,,0,0,0,,{SERIES['series_name']}",
          f"Dialogue: 0,0:00:00.00,{ass_time(total)},Title,,0,0,0,,{title}"]
    for start, end, text in cues:
        ev.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{text}")
    ev.append(f"Dialogue: 0,{ass_time(outro_start)},{ass_time(total)},Outro,,0,0,0,,{outro_text}")
    out.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def voice_line(text, wav, tts_provider):
    """配音一句，已有缓存就复用（竖屏、横屏、音频三个出口共用同一份配音）。"""
    if wav.exists():
        return
    if tts_provider == "edge":
        mp3 = wav.with_suffix(".mp3")
        tts(text, mp3, "edge")
        run(["ffmpeg", "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1", str(wav)])
    else:
        tts(text, wav, "silent")


def render(ep, workdir, out_mp4, img_provider, tts_provider, w=W, h=H, caption=True):
    workdir.mkdir(parents=True, exist_ok=True)
    tag = "v" if h > w else "h"
    cues, audio_parts, segments, t = [], [], [], 0.0
    silence = workdir / "gap.wav"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(GAP), str(silence)])

    for i, shot in enumerate(ep["shots"]):
        print(f"  镜头 {i + 1}/{len(ep['shots'])}")
        raw, frame = workdir / f"img{i:02d}.jpg", workdir / f"{tag}frame{i:02d}.jpg"
        if not raw.exists():
            gen_image(shot["image_prompt"], raw, img_provider, seed=1000 + i)
        compose(raw, frame, w, h)
        shot_start = t
        for j, line in enumerate(shot["lines"]):
            a = workdir / f"a{i:02d}_{j}.wav"
            voice_line(line, a, tts_provider)
            d = duration(a)
            cues.append((t, t + d, line))
            audio_parts += [a, silence]
            t += d + GAP
        seg = workdir / f"{tag}seg{i:02d}.mp4"
        dur = t - shot_start
        frames = int(dur * FPS) + 1
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(frame), "-vf",
             f"scale={w * 2}:{h * 2},zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
             f":d={frames}:s={w}x{h}:fps={FPS}",
             "-t", f"{dur:.3f}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(seg)])
        segments.append(seg)

    # 片尾：最后一帧停 2.5 秒，显示出处和 AI 标识
    outro_start, outro_len = t, 2.5
    seg = workdir / f"{tag}seg_outro.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(workdir / f"{tag}frame{len(ep['shots']) - 1:02d}.jpg"),
         "-t", str(outro_len), "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         "-vf", f"scale={w}:{h}", str(seg)])
    segments.append(seg)
    total = t + outro_len

    (workdir / f"{tag}v.txt").write_text("".join(f"file '{s.name}'\n" for s in segments))
    (workdir / "a.txt").write_text("".join(f"file '{a.name}'\n" for a in audio_parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(workdir / f"{tag}v.txt"), "-c", "copy", str(workdir / f"{tag}video.mp4")])
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(workdir / "a.txt"), str(workdir / "voice.wav")])

    outro = SERIES["outro_text"].format(source=ep["source"])
    subs = workdir / f"{tag}subs.ass"
    build_ass(ep["title"], cues, total, outro_start, outro, subs, w, h)
    bgm = ROOT / "assets" / "bgm.mp3"
    cmd = ["ffmpeg", "-y", "-i", str(workdir / f"{tag}video.mp4"), "-i", str(workdir / "voice.wav")]
    if bgm.exists():  # 放一首免版权背景音乐到 assets/bgm.mp3 即可自动混音
        cmd += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                f"[2:a]volume=0.12[b];[1:a][b]amix=inputs=2:duration=first[a];[0:v]ass={subs}[v]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", f"ass={subs}", "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_mp4)]
    run(cmd)
    if not caption:
        return total

    # 发布文案：标题 + 简介 + 话题，人工发布时直接复制
    caption = (f"{ep['title']}\n\n{SERIES['series_name']}｜{SERIES['tagline']}\n"
               f"本集改编自{ep['source']}，内容由AI辅助生成。\n\n#志怪 #聊斋 #古籍 #悬疑 #异闻簿")
    out_mp4.with_suffix(".txt").write_text(caption, encoding="utf-8")
    print(f"完成：{out_mp4}（{total:.1f} 秒）")
    return total


def make_audio(ep, workdir, out_mp3, tts_provider):
    """单集音频（喜马拉雅等）：开头先播AI声明，再接正片配音，可选垫背景音乐。"""
    disclaimer = workdir / "disclaimer.wav"
    text = SERIES["audio_disclaimer"].format(source=ep["source"], title=ep["title"])
    voice_line(text, disclaimer, tts_provider)
    gap = workdir / "gap.wav"
    (workdir / "audio.txt").write_text(
        "".join(f"file '{p.name}'\n" for p in [disclaimer, gap, gap, gap, workdir / "voice.wav"]))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(workdir / "audio.txt"), str(workdir / "audio_raw.wav")])
    bgm = ROOT / "assets" / "bgm.mp3"
    cmd = ["ffmpeg", "-y", "-i", str(workdir / "audio_raw.wav")]
    if bgm.exists():
        cmd += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                "[1:a]volume=0.12[b];[0:a][b]amix=inputs=2:duration=first[a]", "-map", "[a]"]
    cmd += ["-ar", "44100", "-ac", "2", "-b:a", "128k", str(out_mp3)]
    run(cmd)
    print(f"完成：{out_mp3}")


# ---------------- 上传 R2（可选） ----------------
def upload_r2(path):
    if not os.environ.get("R2_BUCKET"):
        return
    import boto3
    s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['CF_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                      aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    for p in [path, path.with_suffix(".txt"), path.with_suffix(".mp3")]:
        s3.upload_file(str(p), os.environ["R2_BUCKET"], f"yiwenbu/{p.name}")
    print("已上传 R2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", action="store_true", help="取 topics.json 里下一个未做的选题")
    ap.add_argument("--episode", help="已有稿件 JSON")
    ap.add_argument("--llm", default=os.environ.get("LLM_PROVIDER", "github"), choices=["github", "cloudflare"])
    ap.add_argument("--images", default=os.environ.get("IMAGE_PROVIDER", "cloudflare"), choices=["cloudflare", "placeholder"])
    ap.add_argument("--tts", default=os.environ.get("TTS_PROVIDER", "edge"), choices=["edge", "silent"])
    args = ap.parse_args()

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    if args.next:
        topics = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
        todo = [t for t in topics if not (ROOT / "episodes" / f"{t['id']}.json").exists()]
        if not todo:
            sys.exit("选题已全部做完，请往 topics.json 里补充")
        topic, nxt = todo[0], (todo[1] if len(todo) > 1 else None)
        print(f"选题：{topic['id']} {topic['source']}")
        ep = write_script(topic, nxt, args.llm)
        ep_path = ROOT / "episodes" / f"{topic['id']}.json"
        ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.episode:
        ep_path = Path(args.episode)
        ep = json.loads(ep_path.read_text(encoding="utf-8"))
    else:
        ap.error("需要 --next 或 --episode")

    mp4 = out_dir / f"{ep_path.stem}.mp4"
    work = ROOT / "work" / ep_path.stem
    render(ep, work, mp4, args.images, args.tts)
    make_audio(ep, work, mp4.with_suffix(".mp3"), args.tts)
    import make_assets  # 每集封面：竖版3:4、横版16:9、方形1:1
    make_assets.OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [((1080, 1440), "竖版封面_3x4"), ((1280, 720), "横版封面_16x9"), ((1400, 1400), "方形封面_1x1")]:
        make_assets.cover(ep_path.stem, *size, name)
    upload_r2(mp4)
    import gdrive  # 配了云盘密钥就把本集全部文件写进云盘“第XX集”文件夹
    gdrive.upload([mp4, mp4.with_suffix(".mp3"), mp4.with_suffix(".txt")] +
                  sorted(make_assets.OUT.glob(f"{ep_path.stem}_*.jpg")), f"第{int(ep_path.stem[2:]):02d}集")


if __name__ == "__main__":
    main()
