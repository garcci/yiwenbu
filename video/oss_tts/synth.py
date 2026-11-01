"""开源中文 TTS 盲听素材：在 GitHub Actions CPU runner 上跑，输出 24kHz 单声道 wav。
用法：python synth.py <cosyvoice_sft|cosyvoice2|qwen3_tts|kokoro_zh> <输出根目录>
每个模型两套：<套名>/01..07.wav（原7句逐句）、<套名>_oral/full.wav（口语讲述稿整段，稿子取自
voice_test/research_writing.md 的「## 口语讲述稿」小节，没有就跳过）。耗时、实时倍率、峰值内存写到 timing_<模型>.json。
只用模型自带的预置音色；CosyVoice2 的参考音频是 300M-SFT 预置“中文男”现合成的一句，不克隆任何真人或商业 TTS 声音。"""
import json, os, re, resource, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
LINES = ["我赶回村时，爷爷已经死了。", "到后半夜，门外有了敲门声。", "我抬起头。", "隔着门，又听见了爷爷的声音。",
         "火柴被我扣住了。", "门没开，东西也没递出去。", "可那声哎，已经收不回来了。"]
INSTRUCT = "像对着一个朋友讲一件自己亲身经历过的真事，自然有起伏，有情绪但克制，不表演"
REF_TEXT = "那年冬天特别冷，我从县城坐了一天的车才到家。"
MODELS_DIR = Path(os.environ.get("MODELS_DIR", Path.home() / "models"))


def oral_text():
    p = ROOT / "voice_test/research_writing.md"
    if not p.exists():
        return None
    m = re.search(r"^## 口语讲述稿[^\n]*\n(.*?)(?=^## |\Z)", p.read_text(encoding="utf-8"), re.S | re.M)
    if not m:
        return None
    body = "\n".join(l for l in m.group(1).splitlines() if l.strip() and not l.lstrip().startswith(("#", "<!--", "```", ">", "|")))
    body = re.sub(r"[*_`]", "", body).strip()
    return body or None


def to24k(wav, sr):
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if sr != 24000:
        import librosa
        wav = librosa.resample(wav, orig_sr=sr, target_sr=24000)
    return wav


def make_runner(model):
    """返回 (套名, synth(text) -> (np.ndarray, sr))。"""
    if model in ("cosyvoice_sft", "cosyvoice2"):
        sys.path[:0] = [str(Path.home() / "CosyVoice"), str(Path.home() / "CosyVoice/third_party/Matcha-TTS")]
        import torch
        from cosyvoice.cli.cosyvoice import AutoModel
        cat = lambda gen: (torch.cat([j["tts_speech"] for j in gen], dim=-1).squeeze(0).numpy())
        sft = AutoModel(model_dir=str(MODELS_DIR / "CosyVoice-300M-SFT"))
        if model == "cosyvoice_sft":
            return "cosyvoice_sft_a", lambda t: (cat(sft.inference_sft(t, "中文男", stream=False)), sft.sample_rate)
        ref = MODELS_DIR / "ref_cosyvoice_sft_zhongwennan.wav"
        sf.write(ref, cat(sft.inference_sft(REF_TEXT, "中文男", stream=False)), sft.sample_rate)
        del sft
        cv2 = AutoModel(model_dir=str(MODELS_DIR / "CosyVoice2-0.5B"))
        return "cosyvoice2_a", lambda t: (cat(cv2.inference_instruct2(t, INSTRUCT + "<|endofprompt|>", str(ref), stream=False)), cv2.sample_rate)
    if model == "qwen3_tts":
        import torch
        from qwen_tts import Qwen3TTSModel
        name = os.environ.get("QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        tts = Qwen3TTSModel.from_pretrained(name, device_map="cpu", dtype=torch.float32)
        speaker = os.environ.get("QWEN_SPEAKER", "Dylan")
        tag = "qwen3_tts_a" if "1.7B" in name else "qwen3_tts_06b_a"

        def run(t):
            wavs, sr = tts.generate_custom_voice(text=t, language="Chinese", speaker=speaker, instruct=INSTRUCT)
            return wavs[0], sr
        return tag, run
    if model == "kokoro_zh":
        from kokoro import KModel, KPipeline
        repo = "hexgrad/Kokoro-82M-v1.1-zh"
        km = KModel(repo_id=repo).eval()
        pipe = KPipeline(lang_code="z", repo_id=repo, model=km)
        voice = os.environ.get("KOKORO_VOICE", "zm_010")
        return "kokoro_zh_a", lambda t: (np.concatenate([np.asarray(r.audio) for r in pipe(t, voice=voice, speed=1.0)]), 24000)
    raise SystemExit(f"未知模型：{model}")


def main():
    model, out = sys.argv[1], Path(sys.argv[2])
    t0 = time.time()
    tag, synth = make_runner(model)
    timing = {"model": model, "set": tag, "load_s": round(time.time() - t0, 1), "items": []}

    def one(text, path):
        t = time.time()
        wav, sr = synth(text)
        wav = to24k(wav, sr)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, wav, 24000, subtype="PCM_16")
        gen, dur = time.time() - t, len(wav) / 24000
        item = {"file": f"{path.parent.name}/{path.name}", "chars": len(text), "gen_s": round(gen, 1), "audio_s": round(dur, 2),
                "rtf": round(gen / dur, 2) if dur else None,
                "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 2)}  # Linux 单位是 KB
        timing["items"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    for i, text in enumerate(LINES, 1):
        one(text, out / tag / f"{i:02d}.wav")
    oral = oral_text()
    if oral:
        timing["oral_text"] = oral
        one(oral, out / f"{tag}_oral" / "full.wav")
    else:
        print("research_writing.md 里还没有「## 口语讲述稿」，跳过整段", flush=True)
    items = timing["items"]
    timing["total_gen_s"] = round(sum(x["gen_s"] for x in items), 1)
    timing["total_audio_s"] = round(sum(x["audio_s"] for x in items), 2)
    timing["rtf"] = round(timing["total_gen_s"] / timing["total_audio_s"], 2)
    timing["peak_rss_gb"] = max(x["peak_rss_gb"] for x in items)
    (out / f"timing_{model}.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
