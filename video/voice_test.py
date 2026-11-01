"""配音盲听：同一段台词，豆包（套餐内）多种合成方式 + Mac 本地开源模型（voice_test/<套名>/NN.wav），
统一做“逐句匀速”处理后各出一版，随机编号 A/B/C… 上传云盘。编号对照只打印在日志里。"""
import base64, json, os, random, subprocess, sys, time, wave
from pathlib import Path
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gdrive

LINES = ["我赶回村时，爷爷已经死了。", "到后半夜，门外有了敲门声。", "我抬起头。", "隔着门，又听见了爷爷的声音。",
         "火柴被我扣住了。", "门没开，东西也没递出去。", "可那声哎，已经收不回来了。"]
SR = 24000
CPS = 220 / 60            # 目标语速：每秒汉字数
WORK = ROOT / "work/voice"; WORK.mkdir(parents=True, exist_ok=True)
KEY = os.environ.get("ARK_API_KEY", "").strip()
FOLDER = "11uMWY64q_tLolJ210NmLhfqnkW1D5fBR"
STYLE = "一个19岁的年轻男人低声回忆亲身经历，平稳克制，语速始终一致，不夸张"
# 用户标准：真实、有活人感，但不刻意（不加夸张呼吸、笑声、口癖、戏腔），像一个人平静地讲一件真事
REAL = "像一个普通年轻人平静地跟朋友讲一件自己经历过的真事，自然，不表演，不刻意，不加呼吸声和语气词"
VOICES = os.environ.get("DOUBAO_VOICES", "zh_male_m191_uranus_bigtts,zh_male_taocheng_uranus_bigtts,"
                        "zh_male_dayi_uranus_bigtts,zh_male_liufei_uranus_bigtts").split(",")


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


def doubao(text, speaker, out, style=None, rate=-8):
    h = {"X-Api-Key": KEY, "Authorization": f"Bearer {KEY}", "X-Api-Resource-Id": "seed-tts-2.0",
         "Content-Type": "application/json"}
    req = {"text": text, "speaker": speaker, "audio_params": {"format": "mp3", "sample_rate": SR, "speech_rate": rate}}
    if style:
        req["additions"] = json.dumps({"context_texts": [style]}, ensure_ascii=False)
    r = requests.post("https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional", headers=h,
                      json={"user": {"uid": "yiwenbu"}, "req_params": req}, stream=True, timeout=120)
    audio, last = b"", ""
    for raw in r.iter_lines():
        if raw:
            last = raw.decode("utf-8", "ignore"); j = json.loads(raw)
            if j.get("data"):
                audio += base64.b64decode(j["data"])
    if not audio:
        print("   ", speaker, "失败", r.status_code, last[:200]); return None
    mp3 = out.with_suffix(".mp3"); mp3.write_bytes(audio)
    ff("-i", str(mp3), "-ac", "1", "-ar", str(SR), str(out)); return out


def clean(src, dst, text, even=True):
    """去首尾静音；even=True 时把这一句拉到统一语速（限制在 0.85–1.18 倍，避免变声）。"""
    tmp = dst.with_suffix(".t.wav")
    ff("-i", str(src), "-ac", "1", "-ar", str(SR), "-af",
       "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
       "silenceremove=start_periods=1:start_threshold=-45dB,areverse", str(tmp))
    with wave.open(str(tmp)) as w:
        dur = w.getnframes() / SR
    n = sum(1 for c in text if "一" <= c <= "鿿")
    tempo = min(1.18, max(0.85, (n / CPS) and dur / (n / CPS))) if even else 1.0
    ff("-i", str(tmp), "-af", f"atempo={tempo:.3f}", str(dst))
    return tempo


def assemble(wavs, out):
    """句间固定停顿 0.55 秒，整体响度统一到 -16 LUFS。"""
    gap = WORK / "gap.wav"
    ff("-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", "0.55", str(gap))
    seq = []
    for w in wavs:
        seq += [w, gap]
    lst = out.with_suffix(".txt"); lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seq))
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
       "-ar", "44100", "-b:a", "160k", str(out))


def main():
    sets = {}   # 套名 -> 逐句 wav 列表
    if KEY and not os.environ.get("SKIP_DOUBAO"):
        ok = []
        for v in VOICES:
            d = WORK / f"doubao_{v}"; d.mkdir(exist_ok=True)
            files = [doubao(t, v, d / f"{i + 1:02d}.wav") for i, t in enumerate(LINES)]
            if all(files):
                ok.append(v); sets[f"豆包逐句·{v}"] = files
            time.sleep(1)
        for v in ok[:2]:   # 逐句 + “平静讲真事”提示
            d = WORK / f"doubao_real_{v}"; d.mkdir(exist_ok=True)
            files = [doubao(t, v, d / f"{i + 1:02d}.wav", style=REAL) for i, t in enumerate(LINES)]
            if all(files):
                sets[f"豆包逐句+平静讲真事提示·{v}"] = files
        if ok:   # 对照组：现在小样的做法（整段一次合成，带语气提示）
            whole = WORK / "doubao_whole.wav"
            if doubao("".join(LINES), ok[0], whole, style=STYLE):
                sets[f"豆包整段带语气提示（现做法）·{ok[0]}"] = [whole]
    names = list(sets); random.Random(20261101).shuffle(names)
    labels = list(zip("ABCDEFG", names))
    # 本地开源模型的套固定从 H 往后编号，后续推送新套不会打乱豆包那几版的字母
    local = [d for d in sorted((ROOT / "voice_test").glob("*/")) if len(list(d.glob("[0-9][0-9].wav"))) == len(LINES)]
    for label, d in zip("HIJKLMN", local):
        sets[f"本地开源·{d.name}"] = sorted(d.glob("[0-9][0-9].wav")); labels.append((label, f"本地开源·{d.name}"))
    outs = []
    for label, name in labels:
        files = sets[name]; tempos = []
        cleaned = []
        for i, f in enumerate(files):
            dst = WORK / f"{label}_{i:02d}.wav"
            even = len(files) == len(LINES)
            tempos.append(clean(f, dst, LINES[i] if even else "".join(LINES), even))
            cleaned.append(dst)
        out = WORK / f"04-配音盲听-{label}.mp3"
        assemble(cleaned, out); outs.append(out)
        print(f"{label} = {name}  语速修正 {', '.join(f'{t:.2f}' for t in tempos)}")
    if os.environ.get("GDRIVE_REFRESH_TOKEN"):
        h = {"Authorization": f"Bearer {gdrive._token()}"}
        for o in outs:
            print("云盘" + gdrive._put(h, o, FOLDER), o.name)


if __name__ == "__main__":
    main()
