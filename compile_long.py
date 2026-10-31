#!/usr/bin/env python3
"""把多集《异闻簿》拼成一条横屏长合集（给 YouTube / B站），并生成带章节时间戳的简介。

复用每集已经生成的画面和配音，不会重复花额度。
用法：
  python compile_long.py                         # 用 episodes/ 里的全部稿件
  python compile_long.py --from 1 --to 50        # 指定第1到第50集
  python compile_long.py --target-min 60         # 凑满约60分钟就停
"""
import argparse, json, os
from pathlib import Path

from make_episode import HW, HH, ROOT, SERIES, render, run


def stamp(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=9999)
    ap.add_argument("--target-min", type=float, default=60)
    ap.add_argument("--images", default=os.environ.get("IMAGE_PROVIDER", "cloudflare"), choices=["cloudflare", "seedream", "placeholder"])
    ap.add_argument("--tts", default=os.environ.get("TTS_PROVIDER", "edge"), choices=["edge", "minimax", "silent"])
    args = ap.parse_args()

    eps = sorted((ROOT / "episodes").glob("ep*.json"))
    eps = [p for p in eps if args.start <= int(p.stem[2:]) <= args.end]
    if not eps:
        raise SystemExit("没有可用的稿件")

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    parts, chapters, t = [], [], 0.0
    for p in eps:
        ep = json.loads(p.read_text(encoding="utf-8"))
        work = ROOT / "work" / p.stem
        h_mp4 = work / "horizontal.mp4"
        print(f"横屏：{p.stem} {ep['title']}")
        dur = render(ep, work, h_mp4, args.images, args.tts, w=HW, h=HH, caption=False)
        chapters.append(f"{stamp(t)} 第{int(p.stem[2:])}集 {ep['title']}（{ep['source']}）")
        parts.append(h_mp4)
        t += dur
        if t >= args.target_min * 60:
            break

    name = f"合集_{eps[0].stem}-{parts[-1].parent.name}"
    lst = out_dir / f"{name}.list"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    mp4 = out_dir / f"{name}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(mp4)])
    lst.unlink()

    n = len(parts)
    desc = (f"{SERIES['series_name']}合集｜{n}个古籍怪事，一次听完（约{round(t / 60)}分钟）\n\n"
            f"{SERIES['tagline']}。故事均改编自公版古籍，画面与配音由AI辅助生成，稿件经人工审校。\n\n"
            "章节\n" + "\n".join(chapters) +
            "\n\n#聊斋 #志怪 #古籍 #睡前故事 #中国神话")
    mp4.with_suffix(".txt").write_text(desc, encoding="utf-8")
    if t < args.target_min * 60:
        print(f"注意：现有稿件只够 {t / 60:.1f} 分钟，未满 {args.target_min} 分钟")
    print(f"完成：{mp4}（{n}集，{t / 60:.1f} 分钟）")
    import gdrive
    gdrive.upload([mp4, mp4.with_suffix(".txt")], "长合集")


if __name__ == "__main__":
    main()
