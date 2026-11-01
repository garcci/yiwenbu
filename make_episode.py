#!/usr/bin/env python3
"""《异闻簿》自动出片流水线：选题 → 口播稿 → 配音 → 画面 → 动态与音效 → 合成 → 写进云盘。

风格：民间诡异，八分实二分虚。画面暗调写实，镜头会推拉摇移、灯火闪烁、雾气流动；
配音按句控制语速和音高，垫夜风等环境声，关键处加脚步、心跳、低频重音。
全部默认走免费渠道：
  稿件  GitHub Models（Actions 自带 GITHUB_TOKEN）或 Cloudflare Workers AI
  画面  Cloudflare Workers AI 的 FLUX.1 schnell（免费额度内）
  配音  edge-tts（免费）；环境声和音效用 ffmpeg 现场合成，没有版权问题
  存储  直接写进谷歌云盘（gdrive.py），另留一份 Actions 产物

用法：
  python make_episode.py --next                        # 取 topics.json 下一个选题，全自动出片
  python make_episode.py --episode episodes/ep01.json  # 用现成稿件出片
  本地离线试跑：加 --images placeholder --tts silent
"""
import argparse, asyncio, base64, json, os, re, subprocess, sys, textwrap, time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SERIES = json.loads((ROOT / "series.json").read_text(encoding="utf-8"))
W, H = SERIES["width"], SERIES["height"]          # 竖屏 1080×1920
HW, HH = 1920, 1080                               # 横屏（长合集）
FPS = 30
SR = 44100

# 语气 → edge-tts 语速/音高/音量，以及句后停顿（秒）
TONES = {
    "normal":  ("-6%",  "-2Hz", "+0%",  0.35),
    "slow":    ("-22%", "-5Hz", "+0%",  0.75),
    "whisper": ("-18%", "-8Hz", "-25%", 0.70),
    "tense":   ("+6%",  "+0Hz", "+5%",  0.25),
    "afraid":  ("-5%",  "-2Hz", "-15%", 0.55),
    "cold":    ("-12%", "-4Hz", "+0%",  0.60),
    "old":     ("-20%", "-6Hz", "-20%", 0.70),
}
VIDEO_PROVIDER = os.environ.get("VIDEO_PROVIDER", "none")  # none / minimax / seedance（seedance：每个镜头都生成动态）
MOTIONS = ["push_in", "pan_right", "drift_up", "pull_out", "pan_left", "push_in"]


def run(cmd, timeout=900):
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"ffmpeg 超时（{timeout}秒）：{' '.join(map(str, cmd))[:300]}")
    if p.returncode:
        raise SystemExit(f"ffmpeg 出错：{' '.join(map(str, cmd))[:300]}\n{p.stderr[-1500:]}")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def lines_of(shot):
    """兼容两种写法：["一句", ...] 或 [{"t": "一句", "tone": "slow"}, ...]"""
    return [l if isinstance(l, dict) else {"t": l, "tone": "normal"} for l in shot["lines"]]


# ---------------- 稿件 ----------------
def llm(prompt, provider):
    if provider == "github":
        r = requests.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                     "Content-Type": "application/json"},
            json={"model": os.environ.get("LLM_MODEL", "openai/gpt-4.1"),
                  "messages": [{"role": "user", "content": prompt}], "temperature": 0.8},
            timeout=180)
        if not r.ok:
            raise RuntimeError(f"GitHub Models 返回 {r.status_code}：{r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]
    if provider == "openai":  # 任何 OpenAI 兼容接口：Gemini、智谱 GLM、DeepSeek、MiniMax 等
        # 注意：火山方舟 Agent Plan 套餐的文本模型禁止在 API/脚本里调用（可能封号），这里不能拿 ARK_API_KEY 写稿
        key = os.environ["LLM_API_KEY"].strip()
        base = os.environ["LLM_BASE_URL"].strip().rstrip("/")
        last = ""
        # LLM_MODEL 可以写多个（逗号分隔），前一个不可用（404/403/额度不足）就换下一个
        for model in [m.strip() for m in os.environ["LLM_MODEL"].split(",") if m.strip()]:
            for wait in (0, 30, 60, 90, 120):  # 429 限流：等一会儿再试
                time.sleep(wait)
                try:
                    r = requests.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                                      json={"model": model,
                                            "messages": [{"role": "user", "content": prompt}], "temperature": 0.9},
                                      timeout=600)
                except requests.RequestException as e:
                    print(f"    {model} 网络错误：{e}")
                    continue
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
                print(f"    {model} 返回 {r.status_code}，稍后重试")
            if r.ok:
                print(f"    （{model} 写稿）")
                return r.json()["choices"][0]["message"]["content"]
            last = f"{model} 返回 {r.status_code}：{r.text[:300]}"
            print(f"    {last}")
        raise RuntimeError(last)
    if provider == "cloudflare":
        model = os.environ.get("CF_LLM_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
        r = cf_run(model, {"messages": [{"role": "user", "content": prompt}], "max_tokens": 3000})
        return r.json()["result"]["response"]
    raise SystemExit(f"未知 LLM 提供方：{provider}")


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型没有返回 JSON：\n" + text[:500])
    return json.loads(m.group(0))


def _script_ok(ep):
    chars = sum(len(l["t"]) for s in ep["shots"] for l in lines_of(s))
    return 260 <= chars <= 520 and 7 <= len(ep["shots"]) <= 12, chars


def write_script(topic, provider, rounds=2):
    """一次写 3 稿 → 责编按 8 项打分、挑一稿精修 → 任何一项低于 8 分就带着意见再改，最多 rounds 轮。"""
    tpl = (ROOT / "episode_prompt.txt").read_text(encoding="utf-8")
    prompt = tpl.replace("{source}", topic["source"]).replace("{summary}", topic["summary"])
    drafts = []
    for attempt in range(6):
        if len(drafts) == 3:
            break
        try:
            ep = parse_json(llm(prompt, provider))
            ok, chars = _script_ok(ep)
            if ok:
                drafts.append(ep)
            else:
                print(f"  稿件长度不合格（{chars}字/{len(ep['shots'])}镜），重写")
        except Exception as e:  # noqa: BLE001
            print(f"  第{attempt + 1}次生成失败：{e}")
    if not drafts:
        raise SystemExit("稿件生成失败")
    edit = (ROOT / "editor_prompt.txt").read_text(encoding="utf-8")
    best = drafts[0]
    for r in range(rounds):
        listing = "\n\n".join(f"【第{k + 1}稿】\n{json.dumps(d, ensure_ascii=False)}" for k, d in enumerate(drafts))
        try:
            cand = parse_json(llm(edit.replace("{drafts}", listing), provider))
            if cand.get("shots") and _script_ok(cand)[0]:
                best = cand
        except Exception as e:  # noqa: BLE001
            print(f"  精修失败：{e}")
        scores = best.get("scores", {})
        print(f"  第{r + 1}轮责编打分：{scores}  {best.get('notes', '')}")
        if scores and min(int(v) for v in scores.values()) >= 8:
            break
        drafts = [best]  # 带着意见再精修一轮
    best["source"] = topic["source"]
    return best


# ---------------- 配音 ----------------
async def _edge(text, out, voice, rate, pitch, volume):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume).save(str(out))


# 角色 → 声音。series.json 的 voices 里可以覆盖；edge 是免费音色，minimax 是付费高品质音色
VOICES = SERIES.get("voices", {})
MINIMAX_EMOTION = {"normal": "calm", "slow": "sad", "whisper": "fearful", "tense": "fearful"}
MINIMAX_SPEED = {"normal": 0.95, "slow": 0.82, "whisper": 0.85, "tense": 1.08}
MINIMAX_HOST = os.environ.get("MINIMAX_HOST", "https://api.minimaxi.com")
# 火山方舟套餐（Coding/Agent Plan）走 /api/plan/v3；按量付费账号可把 ARK_BASE 设成 https://ark.cn-beijing.volces.com/api/v3
ARK_BASE = (os.environ.get("ARK_BASE") or "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip("/")


def _minimax_tts(text, out, who, tone):
    """MiniMax T2A v2。……换成 <#秒#> 停顿标记，让模型在句中自然换气。"""
    v = VOICES.get(who, VOICES.get("narrator", {})).get("minimax", "male-qn-jingying")
    t = re.sub(r"……$", "", text).replace("……", "<#0.6#>")
    body = {"model": os.environ.get("MINIMAX_TTS_MODEL", "speech-2.8-hd"), "text": t, "stream": False,
            "voice_setting": {"voice_id": v, "speed": MINIMAX_SPEED.get(tone, 0.95), "vol": 1,
                              "pitch": -2 if who == "ghost" else 0, "emotion": MINIMAX_EMOTION.get(tone, "calm")},
            "audio_setting": {"sample_rate": 44100, "format": "mp3", "channel": 1}}
    h = {"Authorization": f"Bearer {os.environ['MINIMAX_API_KEY'].strip()}"}
    for attempt in range(4):
        try:
            r = requests.post(f"{MINIMAX_HOST}/v1/t2a_v2", headers=h, json=body, timeout=90).json()
            code = r.get("base_resp", {}).get("status_code")
            if code == 0:
                out.write_bytes(bytes.fromhex(r["data"]["audio"]))
                return
            print(f"    MiniMax 配音返回 {code}：{r.get('base_resp')}")
            if code == 2013 and "emotion" in body["voice_setting"]:  # 参数不被支持时去掉情绪再试
                body["voice_setting"].pop("emotion")
                continue
        except requests.RequestException as e:
            print(f"    MiniMax 网络错误：{e}")
        time.sleep(3 * (attempt + 1))
    raise SystemExit(f"MiniMax 配音失败：{text}")


DOUBAO_TTS_URL = os.environ.get("DOUBAO_TTS_URL", "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional")
DOUBAO_STYLE = {"normal": "用低沉、平稳、讲故事的语气", "slow": "放慢语速，压低声音，带一点神秘感",
                "whisper": "压低嗓音，像贴着耳朵小声说，带一点害怕", "tense": "语速加快，声音紧张",
                "afraid": "声音发抖，气息很重，像刚亲眼看到不该看的东西，强压着恐惧小声说",
                "cold": "语气很平、很冷，没有一点情绪，一字一顿",
                "old": "像一个很老的老太太隔着门板说话，很轻，很慢，有点含糊"}


def _doubao_tts(text, out, who, tone):
    """豆包语音合成 2.0（火山方舟 Agent Plan 套餐里的 seed-tts-2.0），HTTP 流式返回分段 base64 音频。"""
    v = VOICES.get(who, VOICES.get("narrator", {})).get("doubao", "zh_female_vv_uranus_bigtts")
    key = os.environ["ARK_API_KEY"].strip()
    h = {"X-Api-Key": key, "Authorization": f"Bearer {key}", "X-Api-Resource-Id": "seed-tts-2.0",
         "Content-Type": "application/json"}
    if os.environ.get("DOUBAO_APPID"):
        h.update({"X-Api-App-Id": os.environ["DOUBAO_APPID"], "X-Api-Access-Key": os.environ.get("DOUBAO_TOKEN", "")})
    speed = {"normal": -10, "slow": -25, "whisper": -20, "tense": 10}.get(tone, -10)
    req = {"text": text.replace("……", "…"), "speaker": v,
           "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": speed},
           "additions": json.dumps({"context_texts": [DOUBAO_STYLE.get(tone, DOUBAO_STYLE["normal"])]}, ensure_ascii=False)}
    for attempt in range(4):
        try:
            r = requests.post(DOUBAO_TTS_URL, headers=h, json={"user": {"uid": "yiwenbu"}, "req_params": req},
                              stream=True, timeout=120)
            if not r.ok:
                print(f"    豆包配音返回 {r.status_code}：{r.text[:300]}")
            else:
                audio, last = b"", ""
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    last = raw.decode("utf-8", "ignore")
                    j = json.loads(raw)
                    if j.get("data"):
                        audio += base64.b64decode(j["data"])
                    if j.get("code", 0) not in (0, 20000000):
                        print(f"    豆包配音出错：{last[:300]}")
                        break
                if audio:
                    out.write_bytes(audio)
                    return
                print(f"    豆包配音没返回音频：{last[:300]}")
                if "additions" in req:   # 不支持语气提示时去掉再试
                    req.pop("additions")
                    continue
        except (requests.RequestException, ValueError) as e:
            print(f"    豆包配音网络错误：{e}")
        time.sleep(3 * (attempt + 1))
    raise SystemExit(f"豆包配音失败：{text}")


def voice_line(text, tone, wav, tts_provider, who="narrator"):
    """配一句，已有缓存就复用。返回该句后的停顿秒数。"""
    rate, pitch, vol, pause = TONES.get(tone, TONES["normal"])
    if text.endswith(("……", "…")):
        pause += 0.4
    if not wav.exists():
        mp3 = wav.with_suffix(".mp3")
        if tts_provider == "minimax":
            _minimax_tts(text, mp3, who, tone)
        elif tts_provider == "doubao":
            _doubao_tts(text, mp3, who, tone)
        elif tts_provider == "edge":
            ev = VOICES.get(who, {}).get("edge") or SERIES["voice"]
            if who == "ghost":  # 免费音色里让“鬼”更低更虚
                pitch = f"{int(pitch.rstrip('Hz')) - 6:+d}Hz"
            for attempt in range(4):  # edge-tts 是微软免费接口，偶尔断线，重试几次
                try:
                    asyncio.run(asyncio.wait_for(_edge(text, mp3, ev, rate, pitch, vol), 60))
                    if mp3.exists() and mp3.stat().st_size > 1000:
                        break
                except Exception as e:  # noqa: BLE001
                    print(f"    配音第{attempt + 1}次失败：{e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise SystemExit(f"配音失败：{text}")
        if tts_provider in ("minimax", "edge", "doubao"):
            # 轻微的房间混响，让声音像在屋里讲故事；“鬼”的声音再加一层空洞回声
            af = "aecho=0.8:0.6:45|90:0.18|0.10,highpass=f=70"
            if who == "ghost":  # 压低半个调、拖慢一点，再加空洞回声，像隔着门板
                af = ("asetrate=24000*0.9,aresample=24000,atempo=1.0,"
                      "aecho=0.8:0.7:60|140|260:0.35|0.25|0.15,highpass=f=150,lowpass=f=3800")
            run(["ffmpeg", "-y", "-i", str(mp3), "-af", af, "-ar", str(SR), "-ac", "1", str(wav)])
        else:  # silent：离线试跑，按语速估时长
            sec = max(1.2, len(text) / (4.6 if tone in ("normal", "tense") else 3.6))
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{sec:.2f}", str(wav)])
    return pause


# ---------------- 环境声与音效（ffmpeg 现场合成，免版权） ----------------
AMBIENCE = {
    "wind":    "anoisesrc=c=brown:a=0.6:r={sr},lowpass=f=500,tremolo=f=0.12:d=0.7,volume=0.9",
    "night":   "anoisesrc=c=brown:a=0.4:r={sr},lowpass=f=350,tremolo=f=0.1:d=0.5[n];"
               "sine=f=4400:r={sr},tremolo=f=28:d=1,tremolo=f=0.7:d=0.9,volume=0.02[c];[n][c]amix=2",
    "rain":    "anoisesrc=c=pink:a=0.5:r={sr},highpass=f=900,lowpass=f=6000,volume=0.6",
    "drone":   "sine=f=55:r={sr},volume=0.35[a];sine=f=82.4:r={sr},tremolo=f=0.2:d=0.6,volume=0.25[b];"
               "anoisesrc=c=brown:a=0.3:r={sr},lowpass=f=200[c];[a][b][c]amix=3",
}
SFX = {
    "sting":     ("anoisesrc=c=white:a=0.8:r={sr}:d=1.6,highpass=f=1500,afade=t=in:d=1.4,afade=t=out:st=1.4:d=0.2", 1.6),
    "thump":     ("sine=f=48:r={sr}:d=0.9,afade=t=out:st=0.05:d=0.85,volume=3", 0.9),
    "heartbeat": ("sine=f=55:r={sr}:d=0.25,afade=t=out:st=0.02:d=0.22,volume=3,apad=pad_dur=0.18[a];"
                  "sine=f=50:r={sr}:d=0.3,afade=t=out:st=0.02:d=0.27,volume=2.4,apad=pad_dur=0.5[b];"
                  "[a][b]concat=n=2:v=0:a=1,aloop=loop=2:size=55000", 3.6),
    "footsteps": ("anoisesrc=c=brown:a=0.9:r={sr}:d=0.12,lowpass=f=300,afade=t=out:st=0.02:d=0.1,apad=pad_dur=0.55,"
                  "aloop=loop=4:size=30000,volume=2", 3.6),
    "water":     ("anoisesrc=c=pink:a=0.6:r={sr}:d=3,bandpass=f=900:w=600,tremolo=f=3:d=0.8,"
                  "afade=t=in:d=0.4,afade=t=out:st=2.4:d=0.6", 3.0),
    "gust":      ("anoisesrc=c=pink:a=0.9:r={sr}:d=2.5,bandpass=f=700:w=900,afade=t=in:d=1,afade=t=out:st=1.2:d=1.3", 2.5),
    # 敲门三下：木门闷响（低频共振 + 短促闷噪）
    "knock":     ("aevalsrc='(0.9*sin(2*PI*95*t)+0.5*sin(2*PI*210*t))*exp(-t*38)':s={sr}:d=0.42[k];"
                  "anoisesrc=c=brown:a=0.9:r={sr}:d=0.42,lowpass=f=700,afade=t=out:st=0.0:d=0.06[n];"
                  "[k][n]amix=2:normalize=0,volume=1.2,aloop=loop=2:size=18522", 1.3),
    # 老门轴吱呀：频率慢慢漂移的摩擦声
    "creak":     ("aevalsrc='0.35*sin(2*PI*(260+90*sin(2*PI*0.6*t))*t)*(0.55+0.45*sin(2*PI*31*t))':s={sr}:d=2.2,"
                  "bandpass=f=900:w=1400,afade=t=in:d=0.3,afade=t=out:st=1.6:d=0.6,volume=38dB", 2.2),
    # 拖鞋蹭地：一步一步，很慢
    "slipper":   ("anoisesrc=c=pink:a=0.7:r={sr}:d=0.28,bandpass=f=2600:w=2200,afade=t=in:d=0.08,afade=t=out:st=0.12:d=0.16,"
                  "apad=pad_dur=0.75,aloop=loop=3:size=45423,volume=42dB", 4.2),
    # 低频上冲：吓人之前把心提起来
    "riser":     ("aevalsrc='0.35*sin(2*PI*(38+14*t*t)*t)':s={sr}:d=3.2[a];"
                  "anoisesrc=c=white:a=0.5:r={sr}:d=3.2,highpass=f=2500,volume=0.4[b];"
                  "[a][b]amix=2:normalize=0,afade=t=in:d=3.0,afade=t=out:st=3.1:d=0.1,volume=0.8", 3.2),
    # 重击：低频闷响 + 金属刺音
    "hit":       ("aevalsrc='0.95*sin(2*PI*42*t)*exp(-t*3)':s={sr}:d=2.0[a];"
                  "anoisesrc=c=white:a=0.6:r={sr}:d=2.0,highpass=f=3000,afade=t=out:st=0.0:d=0.5[b];"
                  "[a][b]amix=2:normalize=0,volume=0.9", 2.0),
    # 门后的呼吸：很近，很慢
    "breath":    ("anoisesrc=c=pink:a=0.8:r={sr}:d=4,bandpass=f=900:w=900,"
                  "volume='0.15+0.85*pow(sin(PI*t/2),2)':eval=frame,afade=t=in:d=0.5,afade=t=out:st=3.3:d=0.7,volume=36dB", 4.0),
    # 耳鸣：静到发慌
    "tinnitus":  ("sine=f=6800:r={sr}:d=4,volume=0.12,afade=t=in:d=1.2,afade=t=out:st=3:d=1", 4.0),
}


def lavfi_audio(graph, out, dur=None):
    g = graph.format(sr=SR)
    cmd = ["ffmpeg", "-y", "-filter_complex", g + ",aformat=sample_rates=%d:channel_layouts=mono" % SR]
    if dur:
        cmd += ["-t", f"{dur:.2f}"]
    run(cmd + [str(out)])


def mix_audio(workdir, voice_parts, sfx_events, ambience, total):
    """人声按时间排好，垫环境声（人声出现时自动压低），叠加音效，输出 mix.wav。"""
    # 人声轨：每句按起始时间放置
    inputs, filters = [], []
    for k, (wav, start) in enumerate(voice_parts):
        inputs += ["-i", str(wav)]
        filters.append(f"[{k}:a]adelay={int(start * 1000)}:all=1[v{k}]")
    n = len(voice_parts)
    filters.append("".join(f"[v{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0,apad[voice]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[voice]",
         "-t", f"{total:.2f}", "-ar", str(SR), "-ac", "1", str(workdir / "voice.wav")])

    bed = workdir / "bed.wav"
    lavfi_audio(AMBIENCE.get(ambience, AMBIENCE["wind"]), bed, total)

    sfx_inputs, sfx_filters = [], []
    for k, (name, start) in enumerate(sfx_events):
        graph, d = SFX[name]
        f = workdir / f"sfx_{k}_{name}.wav"
        lavfi_audio(graph, f, d)
        sfx_inputs += ["-i", str(f)]
        sfx_filters.append(f"[{k + 2}:a]adelay={int(start * 1000)}:all=1,volume=0.55[s{k}]")

    labels = "".join(f"[s{k}]" for k in range(len(sfx_events)))
    graph = (";".join(sfx_filters) + (";" if sfx_filters else "") +
             "[0:a]asplit=2[vo][key];"
             "[1:a]volume=0.22[bedv];[bedv][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck];"
             f"[vo][duck]{labels}amix=inputs={2 + len(sfx_events)}:normalize=0,alimiter=limit=0.95[out]")
    run(["ffmpeg", "-y", "-i", str(workdir / "voice.wav"), "-i", str(bed), *sfx_inputs,
         "-filter_complex", graph, "-map", "[out]", "-t", f"{total:.2f}", "-ar", str(SR), "-ac", "2",
         str(workdir / "mix.wav")])


# ---------------- 画面 ----------------
class NSFWBlocked(Exception):
    pass


def cf_run(model, payload):
    acc, tok = os.environ["CF_ACCOUNT_ID"].strip(), os.environ["CF_API_TOKEN"].strip()
    for attempt in range(4):  # 网络抖动或 5xx/429 时退避重试
        try:
            r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}",
                              headers={"Authorization": f"Bearer {tok}"}, json=payload, timeout=180)
            if "4006" in r.text or "daily free allocation" in r.text:
                raise SystemExit("Cloudflare 今天的免费额度（每天1万 neurons，北京时间8点重置）已用完，明天再跑")
            if r.status_code < 500 and r.status_code != 429:
                break
            print(f"    Cloudflare 返回 {r.status_code}，稍后重试")
        except requests.RequestException as e:
            print(f"    Cloudflare 网络错误：{e}")
            r = None
        time.sleep(5 * 2 ** attempt)
    if r is None:
        raise SystemExit("Cloudflare 连续网络错误")
    if not r.ok:  # 把 Cloudflare 返回的具体原因打出来，方便排查
        if "NSFW" in r.text:
            raise NSFWBlocked(r.text[:200])
        raise SystemExit(f"Cloudflare {model} 返回 {r.status_code}：{r.text[:500]}")
    return r


# 审核误判时逐级换成更"干净"的说法；最后兜底用一张空景
SAFE_WORDS = [(r"\b(feet|foot|legs?|bare\w*|body|bodies|skin|naked|blood\w*|corpse|dead|ghost\w*|shoulders?)\b", "figure"),
              (r"\b(struggling|screaming|scream\w*)\b", "")]
FALLBACK_PROMPT = "an empty misty country road at night in ancient rural China, a faint paper lantern glow in the distance"


REF_IMAGES = [ROOT / p for p in SERIES.get("ref_images", [])]


def _data_url(path):
    import io
    img = Image.open(path).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _seedream(prompt, out, refs=None):
    """火山方舟 Seedream：直接出竖版 9:16，写实质感比 FLUX schnell 好得多。"""
    model = os.environ.get("SEEDREAM_MODEL") or "doubao-seedream-5.0-pro"
    if os.environ.get("SEEDREAM_TIER") == "flash":
        model = os.environ.get("SEEDREAM_FLASH_MODEL") or "doubao-seedream-5.0-flash"
    print(f"    出图：{model}")
    body = {"model": model, "prompt": prompt,
            "size": "1440x2560", "response_format": "b64_json", "watermark": False}
    refs = REF_IMAGES if refs is None else refs
    if refs:  # 定妆参考图：让每个镜头都是同一张脸、同样的妆容和拍摄质感
        body["image"] = [_data_url(p) for p in refs]
    h = {"Authorization": f"Bearer {os.environ['ARK_API_KEY'].strip()}"}
    for attempt in range(4):
        try:
            r = requests.post(f"{ARK_BASE}/images/generations",
                              headers=h, json=body, timeout=180)
            if r.ok:
                out.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
                return
            print(f"    Seedream 返回 {r.status_code}：{r.text[:300]}")
            if r.status_code == 400 and "sensitive" in r.text.lower():
                body["prompt"] = f"{FALLBACK_PROMPT}, {SERIES['visual_style']}"
        except requests.RequestException as e:
            print(f"    Seedream 网络错误：{e}")
        time.sleep(5 * (attempt + 1))
    raise SystemExit("Seedream 出图失败")


def gen_image(prompt, out, provider, character="", refs=None):
    # 主角外貌描述写在每集的 character 里，凡是画到人的镜头都带上，保证前后是同一个人
    if character and re.search(r"\b(man|he|his|traveler|figure|person)\b", prompt, re.I):
        prompt = f"{prompt}. The man is {character}"
    full = f"{prompt}, {SERIES['visual_style']}"
    if provider == "seedream":
        return _seedream(full, out, refs)
    if provider == "cloudflare":
        clean = prompt
        for pat, rep in SAFE_WORDS:
            clean = re.sub(pat, rep, clean, flags=re.I)
        for p in [prompt, clean, FALLBACK_PROMPT]:
            try:
                r = cf_run("@cf/black-forest-labs/flux-1-schnell", {"prompt": f"{p}, {SERIES['visual_style']}", "steps": 8})
                out.write_bytes(base64.b64decode(r.json()["result"]["image"]))
                return
            except NSFWBlocked:
                print(f"    画面被平台审核误拦，换一种说法重试：{p[:60]}")
        raise SystemExit("画面连续被审核拦截")
    else:  # placeholder：离线试跑用的暗色画面
        img = Image.new("RGB", (1024, 1024), (38, 44, 48))
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(font_path(), 34)
        d.multiline_text((110, 420), "\n".join(textwrap.wrap(prompt, 44)[:6]), font=f, fill=(150, 160, 165))
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


def frame_from(src, out, w, h):
    """把方图裁成目标比例并铺满画面（多留10%余量给镜头运动）。"""
    img = Image.open(src).convert("RGB")
    s = min(img.width / w, img.height / h)
    cw, ch = int(w * s), int(h * s)
    img = img.crop(((img.width - cw) // 2, (img.height - ch) // 2, (img.width + cw) // 2, (img.height + ch) // 2))
    img.resize((int(w * 1.1), int(h * 1.1)), Image.LANCZOS).save(out, quality=95)


def motion_filter(kind, frames, w, h):
    """镜头运动：在放大1.1倍的画面上推、拉、横移、上移。"""
    p = f"(on/{frames})"
    z = {"push_in": f"1+0.10*{p}", "pull_out": f"1.10-0.10*{p}"}.get(kind, "1.06")
    x = {"pan_right": f"(iw-iw/zoom)*{p}", "pan_left": f"(iw-iw/zoom)*(1-{p})"}.get(kind, "(iw-iw/zoom)/2")
    y = {"drift_up": f"(ih-ih/zoom)*(1-{p})"}.get(kind, "(ih-ih/zoom)/2")
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}"


def shot_clip(frame, out, dur, kind, fx, w, h):
    frames = int(dur * FPS) + 1
    chain = [motion_filter(kind, frames, w, h)]
    if "flicker" in fx:  # 灯火忽明忽暗
        chain.append("eq=brightness='0.035*sin(2*PI*t*2.3)+0.02*sin(2*PI*t*6.7)':eval=frame")
    if "shake" in fx:    # 轻微手持晃动
        chain.append(f"crop=w={w - 24}:h={h - 24}:x='12+7*sin(t*1.7)':y='12+6*cos(t*2.3)',scale={w}:{h}")
    g = f"[0:v]{','.join(chain)},format=yuv420p[base]"
    if "fog" in fx:      # 低分辨率噪声放大成缓慢流动的雾
        g += (f";color=c=0x808080:s=135x240:r={FPS}:d={dur:.3f},noise=alls=90:allf=t,gblur=sigma=6,"
              f"scale={w}:{h},format=yuv420p[fog];[base][fog]blend=all_mode=screen:all_opacity=0.10[out]")
    else:
        g += ";[base]null[out]"
    g += f";[out]fade=t=in:st=0:d=0.3,fade=t=out:st={max(dur - 0.3, 0):.3f}:d=0.3[v]"
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(frame), "-filter_complex", g, "-map", "[v]",
         "-t", f"{dur:.3f}", "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(out)])


def gen_video(frame, out, prompt):
    """MiniMax 海螺图生视频：以本镜头画面为首帧，生成 6 秒真实运动（雾流、灯晃、人走）。"""
    h = {"Authorization": f"Bearer {os.environ['MINIMAX_API_KEY'].strip()}"}
    img = Image.open(frame).convert("RGB")
    img.thumbnail((1080, 1920))
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    body = {"model": os.environ.get("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-02"),
            "prompt": prompt + ", slow subtle cinematic motion, static camera, no cuts",
            "first_frame_image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
            "duration": 6, "resolution": os.environ.get("MINIMAX_VIDEO_RES", "768P")}
    r = requests.post(f"{MINIMAX_HOST}/v1/video_generation", headers=h, json=body, timeout=120).json()
    task = r.get("task_id")
    if not task:
        print(f"    图生视频提交失败，这个镜头改用推拉：{r.get('base_resp')}")
        return False
    for _ in range(120):  # 最多等 20 分钟
        time.sleep(10)
        q = requests.get(f"{MINIMAX_HOST}/v1/query/video_generation", headers=h,
                         params={"task_id": task}, timeout=60).json()
        st = q.get("status")
        if st == "Success":
            f = requests.get(f"{MINIMAX_HOST}/v1/files/retrieve", headers=h,
                             params={"file_id": q["file_id"]}, timeout=60).json()
            data = requests.get(f["file"]["download_url"], timeout=300).content
            out.write_bytes(data)
            return True
        if st == "Fail":
            print(f"    图生视频失败，这个镜头改用推拉：{q}")
            return False
    print("    图生视频等待超时，这个镜头改用推拉")
    return False


VIDEO_SLOW = float(os.environ.get("VIDEO_SLOW") or 1.7)  # 省钱：动态片段补帧放慢最多 1.7 倍铺满旁白，生成秒数少四成


def video_clip(src, out, dur, fx, w, h):
    """把图生视频铺满画面；旁白比视频长时先补帧放慢（最多 VIDEO_SLOW 倍），还不够再正放接倒放，不会突然定格。"""
    vd = duration(src)
    slow = min(max(dur / vd, 1.0), VIDEO_SLOW)
    vd2 = vd * slow
    base = f"[0:v]setpts={slow:.4f}*PTS"
    if slow > 1.05:
        base += f",minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"
    base += f",scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1"
    if dur > vd2 + 0.05:
        loops = int(dur // (2 * vd2)) + 1
        base += (f",split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,"
                 f"loop={loops}:size={int(2 * vd2 * FPS)}")
    chain = []
    if "flicker" in fx:
        chain.append("eq=brightness='0.03*sin(2*PI*t*2.3)':eval=frame")
    g = base + ("," + ",".join(chain) if chain else "") + ",format=yuv420p[base]"
    g += f";[base]fade=t=in:st=0:d=0.3,fade=t=out:st={max(dur - 0.3, 0):.3f}:d=0.3[v]"
    run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", g, "-map", "[v]", "-t", f"{dur:.3f}",
         "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(out)])


# ---------------- 字幕 ----------------
def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(title, cues, total, outro_start, outro_text, out, w=W, h=H, hook=""):
    font = os.environ.get("FONT_NAME") or SERIES.get("font_name", "Noto Sans CJK SC")
    accent = SERIES["accent_color"].lstrip("#")
    accent_ass = f"&H00{accent[4:6]}{accent[2:4]}{accent[0:2]}"
    if h > w:
        styles = f"""Style: Series,{font},40,{accent_ass},&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,10,0,1,2,0,8,60,60,120,1
Style: Title,{font},60,&H00F0F0F0,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,2,0,1,3,1,8,60,60,180,1
Style: Sub,{font},64,&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,1,0,0,0,100,100,1,0,1,4,1,2,80,80,420,1
Style: Hook,{font},96,&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,4,0,1,6,2,5,60,60,0,1
Style: Outro,{font},38,&H00D0D0D0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,2,60,60,260,1"""
    else:
        styles = f"""Style: Series,{font},34,{accent_ass},&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,6,0,1,2,0,7,50,50,40,1
Style: Title,{font},44,&H00F0F0F0,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,3,0,7,50,50,90,1
Style: Sub,{font},56,&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,1,0,0,0,100,100,1,0,1,4,1,2,80,80,70,1
Style: Outro,{font},36,&H00D0D0D0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,3,0,2,60,60,150,1"""
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
    if hook and h > w:  # 前 3 秒屏幕大字钩子：静音刷到的人也能被勾住
        ev.append(f"Dialogue: 1,0:00:00.00,0:00:03.00,Hook,,0,0,0,,{{\\fad(0,300)}}{hook}")
    for start, end, text in cues:
        ev.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\fad(120,120)}}{text}")
    ev.append(f"Dialogue: 0,{ass_time(outro_start)},{ass_time(total)},Outro,,0,0,0,,{outro_text}")
    out.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ---------------- 合成 ----------------
def render(ep, workdir, out_mp4, img_provider, tts_provider, w=W, h=H, caption=True):
    workdir.mkdir(parents=True, exist_ok=True)
    tag = "v" if h > w else "h"
    cues, voice_parts, sfx_events, clips, t = [], [], [], [], 0.6  # 开头留0.6秒只有环境声

    for i, shot in enumerate(ep["shots"]):
        print(f"  镜头 {i + 1}/{len(ep['shots'])}")
        # 省钱：reuse 指向前面某个镜头的序号（从1数），直接复用那张图，换个运镜和裁切
        src_i = shot["reuse"] - 1 if isinstance(shot.get("reuse"), int) else i
        raw, frame = workdir / f"img{src_i:02d}.jpg", workdir / f"{tag}frame{i:02d}.jpg"
        if not raw.exists():
            # 省钱：有女主或标了 key 的关键镜头用 pro，其余空镜用便宜的 flash
            key = shot.get("key") or shot.get("cast") in ("heroine", "rabbit")
            os.environ["SEEDREAM_TIER"] = "pro" if key else "flash"
            cast = SERIES.get("cast", {}).get(shot.get("cast", ""))
            refs = [ROOT / cast] if cast else ([] if shot.get("cast") == "none" else None)
            prompt = shot["image_prompt"]
            if cast:
                prompt = "参考图中的这位女子（完全相同的脸、五官、妆容、发饰和衣着），" + prompt
            gen_image(prompt, raw, img_provider, ep.get("character", ""), refs)
        frame_from(raw, frame, w, h)
        shot_start = t if i else 0.0
        if shot.get("sfx") in SFX:
            sfx_events.append((shot["sfx"], max(t - 0.2, 0)))
        for j, line in enumerate(lines_of(shot)):
            a = workdir / f"a{i:02d}_{j}.wav"
            pause = voice_line(line["t"], line.get("tone", "normal"), a, tts_provider, line.get("who", "narrator"))
            d = duration(a)
            cues.append((t, t + d, line["t"]))
            voice_parts.append((a, t))
            if line.get("sfx") in SFX:            # 和这句同时响
                sfx_events.append((line["sfx"], max(t - 0.1, 0)))
            t += d
            if line.get("sfx_after") in SFX:      # 这句说完、静下来之后再响（吓人的点）
                sfx_events.append((line["sfx_after"], t + 0.25 + float(line.get("pause", 0)) * 0.6))
            t += pause + float(line.get("pause", 0))   # pause：额外留白秒数，制造“静”
        clip = workdir / f"{tag}clip{i:02d}.mp4"
        kind = shot.get("motion") or MOTIONS[i % len(MOTIONS)]
        vid = workdir / f"vid{i:02d}.mp4"
        if shot.get("video_prompt") and VIDEO_PROVIDER == "minimax" and not vid.exists():
            gen_video(frame, vid, shot["video_prompt"])
        if VIDEO_PROVIDER == "seedance" and not vid.exists():
            # 用户不要静图推拉：每个镜头都用首帧生成真动态，时长跟旁白走；失败才退回推拉
            import seedance
            vprompt = shot.get("video_prompt") or shot["image_prompt"]
            if not seedance.gen_long(frame, vid, vprompt, (t - shot_start) / VIDEO_SLOW):
                print(f"    镜头 {i + 1} 动态生成失败，这一镜改用推拉")
        if vid.exists():
            video_clip(vid, clip, t - shot_start, shot.get("fx", []), w, h)
        else:
            shot_clip(frame, clip, t - shot_start, kind, shot.get("fx", ["fog"]), w, h)
        clips.append(clip)

    # 片尾：最后一个画面慢慢暗下去，显示出处和 AI 标识
    outro_start, outro_len = t, 3.0
    clip = workdir / f"{tag}clip_outro.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(workdir / f"{tag}frame{len(ep['shots']) - 1:02d}.jpg"),
         "-vf", f"scale={w}:{h},fade=t=out:st=0.5:d=2.5", "-t", str(outro_len), "-r", str(FPS),
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(clip)])
    clips.append(clip)
    total = t + outro_len

    (workdir / f"{tag}v.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(workdir / f"{tag}v.txt"), "-c", "copy",
         str(workdir / f"{tag}video.mp4")])
    if not (workdir / "mix.wav").exists() or tag == "v":
        mix_audio(workdir, voice_parts, sfx_events, ep.get("ambience", "wind"), total)

    outro = SERIES["outro_text"].format(source=ep["source"])
    subs = workdir / f"{tag}subs.ass"
    build_ass(ep["title"], cues, total, outro_start, outro, subs, w, h, ep.get("hook_text", ""))
    # 统一调色：压暗、降饱和、偏冷，加暗角和胶片颗粒
    grade = SERIES.get("grade") or ("eq=contrast=1.08:saturation=0.72:gamma=0.95,colorbalance=bs=0.05:bm=0.03:rh=-0.02,"
                                    "vignette=PI/4.5,noise=alls=5:allf=t")
    run(["ffmpeg", "-y", "-i", str(workdir / f"{tag}video.mp4"), "-i", str(workdir / "mix.wav"),
         "-vf", f"{grade},ass={subs}", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "6M", "-bufsize", "12M",
         "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_mp4)])
    if not caption:
        return total

    caption_txt = (f"{ep['title']}\n\n{SERIES['series_name']}｜{SERIES['tagline']}\n"
                   f"{SERIES['outro_text']}\n\n#诡异故事 #悬疑 #真实经历 #细思极恐 #异闻簿")
    out_mp4.with_suffix(".txt").write_text(caption_txt, encoding="utf-8")
    print(f"完成：{out_mp4}（{total:.1f} 秒）")
    return total


def make_audio(ep, workdir, out_mp3, tts_provider):
    """单集音频（喜马拉雅等）：开头先播AI声明，再接带环境声和音效的正片。"""
    disclaimer = workdir / "disclaimer.wav"
    text = SERIES["audio_disclaimer"].format(source=ep["source"], title=ep["title"])
    voice_line(text, "normal", disclaimer, tts_provider)
    run(["ffmpeg", "-y", "-i", str(disclaimer), "-i", str(workdir / "mix.wav"), "-filter_complex",
         "[0:a]aformat=channel_layouts=stereo,apad=pad_dur=1[d];[d][1:a]concat=n=2:v=0:a=1[a]",
         "-map", "[a]", "-ar", str(SR), "-b:a", "160k", str(out_mp3)])
    print(f"完成：{out_mp3}")


def readable(ep):
    """给人看的剧本：台词按镜头排，附悬念/线索/反转和责编打分。"""
    who = {"narrator": "阿绾", "man": "男", "ghost": "怪"}
    out = [f"《{ep['title']}》  改编自{ep.get('source', '')}", f"屏幕大字：{ep.get('hook_text', '')}",
           f"悬念：{ep.get('question', '')}", f"线索：{ep.get('clue', '')}", f"反转：{ep.get('twist', '')}",
           f"责编打分：{ep.get('scores', '')}  {ep.get('notes', '')}", ""]
    for i, sh in enumerate(ep["shots"], 1):
        out.append(f"【镜头{i}｜{ {'heroine': '阿绾', 'rabbit': '小白'}.get(sh.get('cast'), '无女主')}】{sh.get('image_prompt', '')}")
        for l in lines_of(sh):
            out.append(f"    {who.get(l.get('who', 'narrator'), '阿绾')}（{l.get('tone', 'normal')}）：{l['t']}")
    chars = sum(len(l["t"]) for s in ep["shots"] for l in lines_of(s))
    out.append(f"\n共 {chars} 字，约 {chars / 4.2:.0f} 秒")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", action="store_true", help="取 topics.json 里下一个未做的选题")
    ap.add_argument("--episode", help="已有稿件 JSON")
    ap.add_argument("--drafts", help="只写剧本不出片：逗号分隔的选题 id（如 ep01,ep02），稿件放 episodes/drafts/ 并把可读版传云盘“剧本待审”")
    ap.add_argument("--llm", default=os.environ.get("LLM_PROVIDER", "openai" if os.environ.get("LLM_API_KEY") else "cloudflare"), choices=["openai", "github", "cloudflare"])
    ap.add_argument("--images", default=os.environ.get("IMAGE_PROVIDER", "cloudflare"), choices=["cloudflare", "seedream", "placeholder"])
    ap.add_argument("--tts", default=os.environ.get("TTS_PROVIDER", "edge"), choices=["edge", "minimax", "doubao", "silent"])
    args = ap.parse_args()

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    if args.drafts:
        topics = {t["id"]: t for t in json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))}
        dd = ROOT / "episodes" / "drafts"
        dd.mkdir(parents=True, exist_ok=True)
        outs = []
        for tid in args.drafts.split(","):
            topic = topics[tid.strip()]
            print(f"写剧本：{topic['id']} {topic['source']}")
            ep = write_script(topic, args.llm)
            tag = os.environ.get("DRAFT_TAG", "")
            stem = f"{topic['id']}_{tag}" if tag else topic["id"]
            (dd / f"{stem}.json").write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
            txt = dd / f"{stem}_{ep['title']}.txt"
            txt.write_text(readable(ep), encoding="utf-8")
            outs.append(txt)
        import gdrive
        gdrive.upload(outs, "剧本待审")
        return
    if args.next:
        topics = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
        todo = [t for t in topics if not (ROOT / "episodes" / f"{t['id']}.json").exists()]
        if not todo:
            sys.exit("选题已全部做完，请往 topics.json 里补充")
        topic = todo[0]
        print(f"选题：{topic['id']} {topic['source']}")
        ep = write_script(topic, args.llm)
        ep_path = ROOT / "episodes" / f"{topic['id']}.json"
        ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.episode:
        ep_path = Path(args.episode)
        ep = json.loads(ep_path.read_text(encoding="utf-8"))
    else:
        ap.error("需要 --next 或 --episode")

    mp4 = out_dir / f"{ep_path.stem}.mp4"
    work = ROOT / "work" / ep_path.stem
    t0 = time.time()
    render(ep, work, mp4, args.images, args.tts)
    print(f"视频耗时 {time.time() - t0:.0f} 秒，文件 {mp4.stat().st_size / 1e6:.1f} MB")
    make_audio(ep, work, mp4.with_suffix(".mp3"), args.tts)
    import make_assets  # 每集封面：竖版3:4、横版16:9、方形1:1
    make_assets.OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [((1080, 1440), "竖版封面_3x4"), ((1280, 720), "横版封面_16x9"), ((1400, 1400), "方形封面_1x1")]:
        make_assets.cover(ep_path.stem, *size, name)
    import gdrive  # 配了云盘密钥就把本集全部文件写进云盘“第XX集”文件夹
    gdrive.upload([mp4, mp4.with_suffix(".mp3"), mp4.with_suffix(".txt")] +
                  sorted(make_assets.OUT.glob(f"{ep_path.stem}_*.jpg")), f"第{int(ep_path.stem[2:]):02d}集")


if __name__ == "__main__":
    main()
