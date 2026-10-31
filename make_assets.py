#!/usr/bin/env python3
"""生成账号素材和每集封面。设计规范：白底、只用朱红一个强调色、标题写成一句话、不用渐变和装饰。

  python make_assets.py --brand           # 头像、喜马拉雅专辑封面、YouTube/B站频道横幅
  python make_assets.py --episode ep01    # 该集的竖版、横版、方形封面（需先出过片，复用第一张画面）
输出在 output/assets/
"""
import argparse, json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from make_episode import ROOT, SERIES

INK = (26, 26, 26)
GREY = (110, 110, 110)
WHITE = (255, 255, 255)
ACCENT = tuple(int(SERIES["accent_color"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
OUT = ROOT / "output" / "assets"


def font(size, serif=True):
    cands = (["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"] if serif else []) + [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    if SERIES.get("font_file"):
        cands.insert(0, SERIES["font_file"])
    for c in cands:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    raise SystemExit("找不到中文字体")


def wrap(draw, text, f, max_w):
    """优先在逗号处断行，避免最后一行只剩一个字。"""
    if "，" in text and all(draw.textlength(p, font=f) <= max_w for p in text.split("，")):
        parts = text.split("，")
        return [p + "，" for p in parts[:-1]] + [parts[-1]]
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + [cur] if cur else lines


def seal(size):
    """朱红方印，白字"异闻"，用作头像和角标。"""
    img = Image.new("RGB", (size, size), ACCENT)
    d = ImageDraw.Draw(img)
    f = font(int(size * 0.36))
    for i, ch in enumerate("异闻"):
        w = d.textlength(ch, font=f)
        d.text(((size - w) / 2, size * (0.12 + 0.40 * i)), ch, font=f, fill=WHITE)
    return img


def avatar():
    img = Image.new("RGB", (800, 800), WHITE)
    img.paste(seal(520), (140, 140))
    img.save(OUT / "头像_800.png")


def album_cover():
    s = 1400
    img = Image.new("RGB", (s, s), WHITE)
    d = ImageDraw.Draw(img)
    img.paste(seal(180), (110, 110))
    d.text((110, 520), SERIES["series_name"], font=font(220), fill=INK)
    d.text((116, 820), SERIES["tagline"], font=font(64, serif=False), fill=GREY)
    d.text((110, 1215), "聊斋 · 搜神记 · 山海经｜AI辅助创作", font=font(44, serif=False), fill=GREY)
    img.save(OUT / "专辑封面_1400.png")


def banner():
    # YouTube 横幅 2560×1440，安全区居中 1546×423
    img = Image.new("RGB", (2560, 1440), WHITE)
    d = ImageDraw.Draw(img)
    f1, f2 = font(150), font(56, serif=False)
    title_w = d.textlength(SERIES["series_name"], font=f1)
    x = (2560 - (170 + 50 + title_w)) / 2
    img.paste(seal(170), (int(x), 600))
    d.text((x + 220, 585), SERIES["series_name"], font=f1, fill=INK)
    tw = d.textlength(SERIES["tagline"], font=f2)
    d.text(((2560 - tw) / 2, 820), SERIES["tagline"], font=f2, fill=GREY)
    img.save(OUT / "频道横幅_2560x1440.png")
    # B站空间头图 2560×400（实际按平台提示裁切）
    img.crop((0, 520, 2560, 920)).save(OUT / "B站头图_2560x400.png")


def cover(ep_id, w, h, name):
    ep = json.loads((ROOT / "episodes" / f"{ep_id}.json").read_text(encoding="utf-8"))
    src = ROOT / "work" / ep_id / "img00.jpg"
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    num = f"第{int(ep_id[2:])}集"
    if w >= h * 1.3:  # 横版：左图右字
        pic = Image.open(src).convert("RGB").resize((h, h))
        img.paste(pic, (0, 0))
        pad, x0, tw = int(h * 0.08), h + int(h * 0.08), w - h - int(h * 0.16)
        d.text((x0, pad), f"{SERIES['series_name']}  {num}", font=font(int(h * 0.06)), fill=ACCENT)
        f = font(int(h * 0.09))
        y = int(h * 0.26)
        for line in wrap(d, ep["title"], f, tw):
            d.text((x0, y), line, font=f, fill=INK)
            y += int(h * 0.13)
        d.text((x0, h - pad - int(h * 0.05)), f"改编自{ep['source']}", font=font(int(h * 0.04), False), fill=GREY)
    else:  # 竖版/方形：上图下字
        pic_h = int(h * (0.62 if h > w else 0.58))
        pic = Image.open(src).convert("RGB")
        side = max(w, pic_h)
        pic = pic.resize((side, side)).crop(((side - w) // 2, (side - pic_h) // 2, (side - w) // 2 + w, (side - pic_h) // 2 + pic_h))
        img.paste(pic, (0, 0))
        pad = int(w * 0.07)
        y = pic_h + int(w * 0.05)
        d.text((pad, y), f"{SERIES['series_name']}  {num}", font=font(int(w * 0.045)), fill=ACCENT)
        f = font(int(w * 0.085))
        y += int(w * 0.09)
        for line in wrap(d, ep["title"], f, w - 2 * pad)[:3]:
            d.text((pad, y), line, font=f, fill=INK)
            y += int(w * 0.11)
        d.text((pad, h - pad - int(w * 0.035)), f"改编自{ep['source']}", font=font(int(w * 0.032), False), fill=GREY)
    img.save(OUT / f"{ep_id}_{name}.jpg", quality=92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", action="store_true")
    ap.add_argument("--episode")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.brand:
        avatar(); album_cover(); banner()
        import gdrive
        gdrive.upload(sorted(OUT.glob("*.png")), "账号素材")
    if a.episode:
        cover(a.episode, 1080, 1440, "竖版封面_3x4")      # 抖音/快手/视频号/小红书
        cover(a.episode, 1280, 720, "横版封面_16x9")      # B站/YouTube
        cover(a.episode, 1400, 1400, "方形封面_1x1")      # 喜马拉雅单集
    print(f"完成：{OUT}")


if __name__ == "__main__":
    main()
