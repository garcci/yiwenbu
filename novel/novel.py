#!/usr/bin/env python3
"""《录异簿》小说流水线：一章正文 → 多声线有声书 + 3 条竖屏短视频，写进云盘「小说/成品/第XX章」。

正文以云盘「小说/正文」里的谷歌文档为准（你在云盘里改过的字会直接生效），每次运行先导出一份到
novel/chapters/chXX.txt 存档。配音、出图、合成、上传全部复用《异闻簿》的 make_episode.py。

做法参考：
  alexandria-audiobook   先把正文拆成「说话人 + 台词 + 语气」，每个角色配不同声音
  Toonflow               主角外貌固定写在 book.json 的 character，每个镜头都带上，保证同一个人

用法：
  python novel/novel.py --chapter 1                  # 有声书 + 短视频
  python novel/novel.py --chapter 1 --only audio     # 只出有声书
  python novel/novel.py --chapter 1 --text novel/chapters/ch01.txt --tts silent --images placeholder   # 离线试跑
"""
import argparse, json, os, re, sys, time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import make_episode as me  # noqa: E402
import gdrive  # noqa: E402

BOOK = json.loads((HERE / "book.json").read_text(encoding="utf-8"))
# 把异闻簿的栏目设定换成小说的：栏目名、画风、声线、片尾和音频声明
me.SERIES.update({k: BOOK[k] for k in ["series_name", "tagline", "visual_style", "accent_color", "voice",
                                       "outro_text", "audio_disclaimer"]})
me.VOICES = me.SERIES["voices"] = BOOK["voices"]
# 敲门声：三下闷响
me.SFX["knock"] = ("anoisesrc=c=brown:a=1:r={sr}:d=0.09,lowpass=f=700,afade=t=out:st=0.01:d=0.08,volume=4,"
                   "apad=pad_dur=0.42,aloop=loop=2:size=22000", 1.6)
CN = "零一二三四五六七八九十"


def cn_num(n):
    if n <= 10:
        return CN[n]
    if n < 20:
        return "十" + (CN[n % 10] if n % 10 else "")
    return CN[n // 10] + "十" + (CN[n % 10] if n % 10 else "")


def ask(prompt, provider=None, creative=False):
    """调模型，出错时把返回内容打出来。和异闻簿共用一把钥匙：
    顺序：任意 OpenAI 兼容接口（LLM_API_KEY，如智谱 glm-4-flash 免费）→ Cloudflare。
    GitHub Models 已于 2026-07-30 下线，不再使用。"""
    # 注意：火山方舟订阅套餐的文本模型不允许脚本调用（可能封号），这里不用 ARK_API_KEY
    order = (["openai"] if os.environ.get("LLM_API_KEY") else []) + ["cloudflare"]
    if os.environ.get("GEMINI_API_KEY"):  # 写短视频稿这类创作活优先用 Gemini（免费额度），标注用 GLM
        order.insert(0 if creative else len(order) - 1, "gemini")
    for p in order:
        try:
            if p in ("ark", "openai", "gemini"):
                if p == "gemini":
                    base, key = "https://generativelanguage.googleapis.com/v1beta/openai", os.environ["GEMINI_API_KEY"]
                    model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
                elif p == "ark":  # 火山方舟订阅套餐：必须走 /api/plan/v3，走 /api/v3 会额外计费
                    base = (os.environ.get("ARK_BASE_URL") or "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip("/")
                    key = os.environ["ARK_API_KEY"]
                    model = os.environ.get("ARK_LLM_MODEL") or "doubao-seed-2.1-pro"
                else:
                    base = (os.environ.get("LLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
                    # 小说默认用免费的 glm-4.7-flash，不跟随 LLM_MODEL（避免误用收费的 glm-4.7）
                    key, model = os.environ["LLM_API_KEY"], os.environ.get("NOVEL_LLM_MODEL") or "glm-4.7-flash"
                r = requests.post(f"{base}/chat/completions",
                                  headers={"Authorization": f"Bearer {key.strip()}"},
                                  json={"model": model,
                                        "messages": [{"role": "user", "content": prompt}], "temperature": 0.6},
                                  timeout=300)
                if not r.ok or not r.text.strip().startswith("{"):
                    print(f"    模型接口返回 {r.status_code}：{r.text[:300]!r}")
                    continue
                return r.json()["choices"][0]["message"]["content"]
            if p == "cloudflare" and os.environ.get("CF_API_TOKEN"):
                model = os.environ.get("CF_LLM_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
                r = me.cf_run(model, {"messages": [{"role": "user", "content": prompt}], "max_tokens": 6000})
                res = r.json()["result"]["response"]
                return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
        except (requests.RequestException, KeyError, ValueError, SystemExit) as e:
            print(f"    {p} 调用出错：{e}")
    raise RuntimeError("没有可用的模型（请配置 LLM_API_KEY，或等 Cloudflare 免费额度重置）")


# ---------------- 正文 ----------------
def fetch_chapter(n):
    """从云盘「正文」文件夹导出「第XX章-…」谷歌文档的纯文本。"""
    if not gdrive.enabled():
        raise SystemExit("没配云盘密钥，读不到正文；离线试跑请用 --text")
    h = {"Authorization": f"Bearer {gdrive._token()}"}
    q = (f"name contains '第{n:02d}章' and '{BOOK['gdrive_text_folder']}' in parents and trashed = false "
         "and mimeType = 'application/vnd.google-apps.document'")
    r = requests.get(gdrive.API, headers=h, params={"q": q, "fields": "files(id,name)"}, timeout=30)
    r.raise_for_status()
    files = r.json()["files"]
    if not files:
        raise SystemExit(f"云盘「正文」里没找到第{n:02d}章")
    r = requests.get(f"{gdrive.API}/{files[0]['id']}/export", headers=h,
                     params={"mimeType": "text/plain"}, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def clean(raw):
    """去掉章末的AI声明和分隔线，返回 (标题, 段落列表)。"""
    paras = [p.strip() for p in raw.replace("\r", "").split("\n")]
    paras = [p.lstrip("#").strip() for p in paras if p.strip()]
    body = []
    for p in paras:
        if p.startswith("本章由AI") or re.fullmatch(r"[-_—=*\s]{3,}", p):
            if p.startswith("本章由AI"):
                break
            body.append("§")  # 场景切换，留一段长停顿
            continue
        body.append(p)
    title_line = body.pop(0)
    title = re.sub(r"^第.+?章\s*", "", title_line).strip()
    body = [p for p in body if not re.fullmatch(r"（第.+章完）", p)]
    return title, body


def split_units(paras):
    """拆成可配音的片段：叙述和「」台词分开；叙述太长就在句号处切开（免费配音接口长句不稳）。"""
    units = []
    for p in paras:
        if p == "§":
            units.append({"t": "", "pause": 1.6})
            continue
        # 「录异房」这种短的、不带标点的引号是名称，不是台词，留在叙述里
        p = re.sub(r"「([^」，。！？：]{1,6})」", r"“\1”", p)
        for k, part in enumerate(re.split(r"(「[^」]*」)", p)):
            part = part.strip()
            if not part:
                continue
            if part.startswith("「"):
                units.append({"t": part[1:-1], "kind": "say"})
                continue
            buf = ""
            for s in re.findall(r"[^。！？]*[。！？]?", part):
                if len(buf) + len(s) > 120 and buf:
                    units.append({"t": buf, "kind": "narr"})
                    buf = ""
                buf += s
            if buf.strip("，。 "):
                units.append({"t": buf, "kind": "narr"})
        if units and "pause" not in units[-1]:
            units[-1]["para_end"] = True
    return units


def heuristic_labels(units):
    """没有模型时的兜底：台词按前文最近出现的人名分配。"""
    last = "narrator"
    for u in units:
        if u.get("kind") == "narr":
            u.setdefault("who", "narrator")
            hits = [(u["t"].rfind(n), k) for n, k in BOOK["names"].items() if n in u["t"]]
            if hits:
                last = max(hits)[1]
        elif u.get("kind") == "say":
            u.setdefault("who", last)
        u.setdefault("tone", "normal")


def label(units, provider):
    """让模型标注每段由谁读、什么语气、要不要音效；拆好的原文不交给模型改，只收标注。"""
    cast = "\n".join(f"  {k}：{v}" for k, v in BOOK["cast"].items())
    tpl = (HERE / "label_prompt.txt").read_text(encoding="utf-8").replace("{cast}", cast)
    idx = [i for i, u in enumerate(units) if u["t"]]
    for start in range(0, len(idx), 60):
        chunk = idx[max(0, start - 6): start + 60]  # 带上前几段做上下文
        listing = "\n".join(f"[{i}] {'台词' if units[i]['kind'] == 'say' else '叙述'}：{units[i]['t']}" for i in chunk)
        for attempt in range(3):
            try:
                got = me.parse_json(ask(tpl.replace("{units}", listing), provider))["labels"]
                for g in got:
                    i = int(g["i"])
                    if i not in chunk or (start and i < idx[start]):
                        continue  # 只收本批的标注，前面带上的几段只做上下文
                    if True:
                        u = units[i]
                        u["who"] = g.get("who") if g.get("who") in BOOK["voices"] else "narrator"
                        if u["kind"] == "narr":
                            u["who"] = "narrator"
                        u["tone"] = g.get("tone") if g.get("tone") in me.TONES else "normal"
                        if g.get("sfx") in me.SFX:
                            u["sfx"] = g["sfx"]
                break
            except Exception as e:  # noqa: BLE001
                print(f"  标注第{attempt + 1}次失败：{e}")
    heuristic_labels(units)
    review_speakers(units, cast)


def review_speakers(units, cast):
    """第二遍校对说话人（参考 alexandria-audiobook 的 review 步骤）：只看台词，结合前后文找错配。"""
    says = [i for i, u in enumerate(units) if u.get("kind") == "say"]
    for start in range(0, len(says), 40):
        lines = []
        for i in says[start:start + 40]:
            before = units[i - 1]["t"][-40:] if i and units[i - 1].get("kind") == "narr" else ""
            after = units[i + 1]["t"][:30] if i + 1 < len(units) and units[i + 1].get("kind") == "narr" else ""
            lines.append(f"[{i}] 前文：{before}｜台词（现标 {units[i]['who']}）：{units[i]['t']}｜后文：{after}")
        prompt = ("你是有声书校对。下面是小说台词和当前标注的说话人。两人对话时一般一来一回交替；"
                  "「XX问」「XX说」通常指向紧挨着的台词；自报姓名的台词是那个人自己说的。\n"
                  f"角色：\n{cast}\n\n找出标错的，只输出 JSON：{{\"fix\": [{{\"i\": 编号, \"who\": \"正确角色\"}}]}}，没有错就输出空列表。\n\n"
                  + "\n".join(lines))
        try:
            for f in me.parse_json(ask(prompt))["fix"]:
                i = int(f["i"])
                if i in says and f.get("who") in BOOK["voices"] and f["who"] != units[i]["who"]:
                    print(f"  校对：[{i}] {units[i]['who']} → {f['who']}：{units[i]['t'][:16]}")
                    units[i]["who"] = f["who"]
        except Exception as e:  # noqa: BLE001
            print(f"  说话人校对跳过：{e}")


# ---------------- 有声书 ----------------
def silence(sec, workdir):
    f = workdir / f"sil_{int(sec * 100)}.wav"
    if not f.exists():
        me.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={me.SR}:cl=mono", "-t", f"{sec:.2f}", str(f)])
    return f


def make_audiobook(n, title, units, workdir, out_mp3, tts):
    workdir.mkdir(parents=True, exist_ok=True)
    pieces = []
    intro = workdir / "intro.wav"
    me.voice_line(BOOK["audio_disclaimer"].format(n=cn_num(n), title=title), "normal", intro, tts)
    pieces += [intro, silence(1.5, workdir)]
    for i, u in enumerate(units):
        if not u["t"]:
            pieces.append(silence(u.get("pause", 1.6), workdir))
            continue
        if u.get("sfx"):
            graph, d = me.SFX[u["sfx"]]
            f = workdir / f"sfx_{u['sfx']}.wav"
            if not f.exists():
                me.lavfi_audio(graph, f, d)
            pieces += [f, silence(0.3, workdir)]
        wav = workdir / f"u{i:03d}_{u['who']}.wav"
        pause = me.voice_line(u["t"], u["tone"], wav, tts, u["who"])
        pieces.append(wav)
        pieces.append(silence(pause + (0.45 if u.get("para_end") else 0), workdir))
        if i % 20 == 0:
            print(f"  配音 {i + 1}/{len(units)}")
    lst = workdir / "pieces.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in pieces))
    voice = workdir / "voice.wav"
    me.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-ar", str(me.SR), "-ac", "1", str(voice)])
    total = me.duration(voice) + 2.0
    bed = workdir / "bed.wav"
    me.lavfi_audio(me.AMBIENCE["wind"], bed, total)
    # 环境声垫底，人声出现时自动压低；整体响度统一到 -16 LUFS（播客平台常用）
    me.run(["ffmpeg", "-y", "-i", str(voice), "-i", str(bed), "-filter_complex",
            "[0:a]apad=pad_dur=2,asplit=2[vo][key];[1:a]volume=0.12[b];"
            "[b][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=500[duck];"
            "[vo][duck]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]",
            "-map", "[out]", "-t", f"{total:.2f}", "-ar", str(me.SR), "-ac", "2", "-b:a", "128k", str(out_mp3)],
           timeout=1800)
    print(f"完成：{out_mp3}（{total / 60:.1f} 分钟）")


# ---------------- 短视频 ----------------
def make_shorts(n, title, text, provider):
    path = HERE / "chapters" / f"ch{n:02d}_shorts.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["shorts"]
    tpl = (HERE / "shorts_prompt.txt").read_text(encoding="utf-8")
    prompt = (tpl.replace("{n}", cn_num(n)).replace("{title}", title).replace("{text}", text)
              .replace("{cast_keys}", "、".join(BOOK["voices"])))
    for attempt in range(4):
        try:
            shorts = me.parse_json(ask(prompt, provider, creative=True))["shorts"]
            ok = [s for s in shorts if 6 <= len(s["shots"]) <= 11]
            if len(ok) >= 2:
                path.write_text(json.dumps({"shorts": ok[:3]}, ensure_ascii=False, indent=2), encoding="utf-8")
                return ok[:3]
            print("  短视频稿镜头数不合格，重写")
        except Exception as e:  # noqa: BLE001
            print(f"  短视频稿第{attempt + 1}次失败：{e}")
    raise SystemExit("短视频稿生成失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--only", choices=["audio", "shorts"])
    ap.add_argument("--text", help="本地正文文件（离线试跑用），不给就从云盘读")
    ap.add_argument("--llm", default="auto", choices=["auto", "none"])
    ap.add_argument("--images", default=os.environ.get("IMAGE_PROVIDER", "cloudflare"),
                    choices=["cloudflare", "seedream", "placeholder"])
    ap.add_argument("--tts", default=os.environ.get("TTS_PROVIDER", "edge"), choices=["edge", "minimax", "doubao", "silent"])
    a = ap.parse_args()
    n = a.chapter
    tag = f"ch{n:02d}"

    (HERE / "chapters").mkdir(exist_ok=True)
    raw = Path(a.text).read_text(encoding="utf-8") if a.text else fetch_chapter(n)
    (HERE / "chapters" / f"{tag}.txt").write_text(raw, encoding="utf-8")
    title, paras = clean(raw)
    text = "\n".join(p for p in paras if p != "§")
    print(f"第{n}章《{title}》，{len(text)} 字")

    out = me.ROOT / "output" / tag
    out.mkdir(parents=True, exist_ok=True)
    if a.only in (None, "audio"):
        lab = HERE / "chapters" / f"{tag}_labels.json"
        units = split_units(paras)
        old = json.loads(lab.read_text(encoding="utf-8")) if lab.exists() else []
        if [u["t"] for u in old] == [u["t"] for u in units]:
            units = old  # 正文没改过，沿用上次（可能人工修过）的标注
        elif a.llm != "none":
            label(units, a.llm)
        else:
            heuristic_labels(units)
        lab.write_text(json.dumps(units, ensure_ascii=False, indent=1), encoding="utf-8")
        mp3 = out / f"录异簿-第{n:02d}章-{title}-有声书.mp3"
        make_audiobook(n, title, units, me.ROOT / "work" / "novel" / tag / "audio", mp3, a.tts)
        upload([mp3], n)
    if a.only in (None, "shorts"):
        for k, ep in enumerate(make_shorts(n, title, text, a.llm), 1):
            ep["source"] = f"《录异簿》第{cn_num(n)}章"
            ep["character"] = BOOK["character"]
            mp4 = out / f"录异簿-第{n:02d}章-短视频{k}-{ep['title']}.mp4"
            print(f"短视频 {k}：{ep['title']}")
            me.render(ep, me.ROOT / "work" / "novel" / f"{tag}s{k}", mp4, a.images, a.tts, caption=False)
            mp4.with_suffix(".txt").write_text(
                f"{ep['title']}\n\n原创志怪连载《录异簿》第{cn_num(n)}章《{title}》节选，完整有声书见主页专辑。\n"
                f"本视频由AI辅助创作和配音，故事纯属虚构。\n\n#民间故事 #志怪 #悬疑 #有声小说 #录异簿",
                encoding="utf-8")
            upload([mp4, mp4.with_suffix(".txt")], n)


def upload(files, n):
    if gdrive.enabled():
        os.environ["GDRIVE_FOLDER_ID"] = BOOK["gdrive_output_folder"]
        gdrive.upload(files, f"第{n:02d}章")


if __name__ == "__main__":
    main()
