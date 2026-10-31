#!/usr/bin/env python3
"""出质量小样：一段配音（带环境声和音效）、几张图、一段图生视频，写进云盘「小样/名称」。

  python samples/make_sample.py samples/sample.json
档位跟随环境变量 TTS_PROVIDER / IMAGE_PROVIDER / VIDEO_PROVIDER。
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import make_episode as me  # noqa: E402
import gdrive  # noqa: E402

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if spec.get("style"):      # 小样可以覆盖全局画风
    me.SERIES["visual_style"] = spec["style"]
for who, v in spec.get("voices", {}).items():   # 以及各角色的声音
    me.VOICES[who] = v
work = me.ROOT / "work" / "sample"
work.mkdir(parents=True, exist_ok=True)
outs = []

tts = me.os.environ.get("TTS_PROVIDER", "edge")
if tts != "none":  # none：只出画面
    parts, sfx, t = [], [], 0.8
    for k, line in enumerate(spec["lines"]):
        wav = work / f"line{k:02d}.wav"
        pause = me.voice_line(line["t"], line.get("tone", "normal"), wav, tts, line.get("who", "narrator"))
        if line.get("sfx") in me.SFX:
            sfx.append((line["sfx"], max(t - 0.2, 0)))
        parts.append((wav, t))
        t += me.duration(wav) + pause
    me.mix_audio(work, parts, sfx, spec.get("ambience", "wind"), t + 1.5)
    voice = work / f"配音小样_{tts}.mp3"
    me.run(["ffmpeg", "-y", "-i", str(work / "mix.wav"), "-b:a", "192k", str(voice)])
    outs.append(voice)
    print(f"配音 {t:.1f} 秒")


img_p = me.os.environ.get("IMAGE_PROVIDER", "cloudflare")
for k, shot in enumerate(spec["shots"] if img_p != "none" else []):
    img = work / f"画面{k + 1}_{img_p}.jpg"
    me.gen_image(shot["image_prompt"], img, img_p, spec.get("character", ""))
    outs.append(img)
    if shot.get("video_prompt") and me.VIDEO_PROVIDER == "minimax":
        frame = work / f"frame{k}.jpg"
        me.frame_from(img, frame, me.W, me.H)
        vid = work / f"动态{k + 1}_海螺.mp4"
        if me.gen_video(frame, vid, shot["video_prompt"]):
            outs.append(vid)

gdrive.upload(outs, f"小样/{spec['name']}")
for o in outs:
    print("已出：", o.name)
