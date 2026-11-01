"""开源中文 TTS 盲听素材：在 GitHub Actions CPU runner 上跑，输出 24kHz 单声道 wav。
用法：python synth.py <cosyvoice_sft|cosyvoice2|qwen3_tts|kokoro_zh> <输出根目录>
环境变量 PASSAGE=文本文件 时，整段合成为 <套名><SUFFIX>/full.wav（SUFFIX 默认 _p2）；否则按原 7 句逐句出 <套名>/01..07.wav。
语速目标约每分钟 220 字（只数汉字）：有语速参数的模型先合成一次，偏离 200—240 就按实测比例调 speed 重合成一次。
耗时、实时倍率、峰值内存、实测字速写到 timing_<模型>.json。
只用模型自带的预置音色；CosyVoice2 的参考音频是 300M-SFT 预置“中文男”现合成的一句，不克隆任何真人或商业 TTS 声音。"""
import json, os, re, resource, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
LINES = ["我赶回村时，爷爷已经死了。", "到后半夜，门外有了敲门声。", "我抬起头。", "隔着门，又听见了爷爷的声音。",
         "火柴被我扣住了。", "门没开，东西也没递出去。", "可那声哎，已经收不回来了。"]
INSTRUCT = "像对着一个朋友讲一件自己亲身经历过的真事，自然有起伏，有情绪但克制，不表演"
# CosyVoice2 的长指令疑似被念出或拖长（第一轮 13 字出 8—10 秒），改用短指令
COSY2_INSTRUCT = "用平静克制的语气，像跟朋友讲自己经历过的事<|endofprompt|>"
QWEN_INSTRUCT = INSTRUCT + "。语速偏慢，句与句之间自然停顿"
REF_TEXT = "那年冬天特别冷，我从县城坐了一天的车才到家。"
MODELS_DIR = Path(os.environ.get("MODELS_DIR", Path.home() / "models"))
TARGET_CPM = 220


def hanzi(text):
    return len(re.findall(r"[一-鿿]", text))


def to24k(wav, sr):
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if sr != 24000:
        import librosa
        wav = librosa.resample(wav, orig_sr=sr, target_sr=24000)
    return wav


def make_runner(model):
    """返回 (套名, synth(text, speed) -> (np.ndarray, sr), 初始 speed；speed 为 None 表示模型没有语速参数)。"""
    if model in ("cosyvoice_sft", "cosyvoice2"):
        sys.path[:0] = [str(Path.home() / "CosyVoice"), str(Path.home() / "CosyVoice/third_party/Matcha-TTS")]
        import torch
        from cosyvoice.cli.cosyvoice import AutoModel
        cat = lambda gen: torch.cat([j["tts_speech"] for j in gen], dim=-1).squeeze(0).numpy()
        sft = AutoModel(model_dir=str(MODELS_DIR / "CosyVoice-300M-SFT"))
        if model == "cosyvoice_sft":
            # 第一轮 speed=1.0 实测约每分钟 400 字
            return "cosyvoice_sft_a", lambda t, s: (cat(sft.inference_sft(t, "中文男", stream=False, speed=s)), sft.sample_rate), 0.6
        ref = MODELS_DIR / "ref_cosyvoice_sft_zhongwennan.wav"
        sf.write(ref, cat(sft.inference_sft(REF_TEXT, "中文男", stream=False, speed=0.8)), sft.sample_rate)
        del sft
        cv2 = AutoModel(model_dir=str(MODELS_DIR / "CosyVoice2-0.5B"))
        return "cosyvoice2_a", lambda t, s: (cat(cv2.inference_instruct2(t, COSY2_INSTRUCT, str(ref), stream=False, speed=s)), cv2.sample_rate), 1.0
    if model == "qwen3_tts":
        import torch
        from qwen_tts import Qwen3TTSModel
        name = os.environ.get("QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        tts = Qwen3TTSModel.from_pretrained(name, device_map="cpu", dtype=torch.float32)
        speaker = os.environ.get("QWEN_SPEAKER", "Dylan")
        tag = "qwen3_tts_a" if "1.7B" in name else "qwen3_tts_06b_a"

        def run(t, _):
            # generate_custom_voice 没有语速参数，只能靠指令
            wavs, sr = tts.generate_custom_voice(text=t, language="Chinese", speaker=speaker, instruct=QWEN_INSTRUCT)
            return wavs[0], sr
        return tag, run, None
    if model == "kokoro_zh":
        from kokoro import KModel, KPipeline
        repo = "hexgrad/Kokoro-82M-v1.1-zh"
        km = KModel(repo_id=repo).eval()
        pipe = KPipeline(lang_code="z", repo_id=repo, model=km)
        voice = os.environ.get("KOKORO_VOICE", "zm_010")
        return "kokoro_zh_a", lambda t, s: (np.concatenate([np.asarray(r.audio) for r in pipe(t, voice=voice, speed=s)]), 24000), 1.0
    raise SystemExit(f"未知模型：{model}")


def main():
    model, out = sys.argv[1], Path(sys.argv[2])
    t0 = time.time()
    tag, synth, speed0 = make_runner(model)
    timing = {"model": model, "set": tag, "load_s": round(time.time() - t0, 1), "items": []}

    def one(text, path, calibrate):
        speed, tries = speed0, []
        for attempt in range(2 if calibrate and speed0 is not None else 1):
            t = time.time()
            wav, sr = synth(text, speed)
            wav = to24k(wav, sr)
            gen, dur = time.time() - t, len(wav) / 24000
            cpm = hanzi(text) / dur * 60 if dur else 0
            tries.append({"speed": speed, "gen_s": round(gen, 1), "audio_s": round(dur, 2), "cpm": round(cpm)})
            if speed is None or 200 <= cpm <= 240:
                break
            speed = round(speed * TARGET_CPM / cpm, 2)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, wav, 24000, subtype="PCM_16")
        item = {"file": f"{path.parent.name}/{path.name}", "hanzi": hanzi(text), "tries": tries,
                "gen_s": round(sum(x["gen_s"] for x in tries), 1), "audio_s": round(dur, 2), "cpm": round(cpm),
                "rtf": round(sum(x["gen_s"] for x in tries) / dur, 2) if dur else None,
                "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 2)}  # Linux 单位是 KB
        timing["items"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    passage = os.environ.get("PASSAGE")
    if passage:
        text = (ROOT / passage).read_text(encoding="utf-8").strip()
        timing["text"] = text
        one(text, out / f"{tag}{os.environ.get('SUFFIX', '_p2')}" / "full.wav", calibrate=True)
    else:
        for i, text in enumerate(LINES, 1):
            one(text, out / tag / f"{i:02d}.wav", calibrate=False)
    items = timing["items"]
    timing["total_gen_s"] = round(sum(x["gen_s"] for x in items), 1)
    timing["total_audio_s"] = round(sum(x["audio_s"] for x in items), 2)
    timing["rtf"] = round(timing["total_gen_s"] / timing["total_audio_s"], 2)
    timing["peak_rss_gb"] = max(x["peak_rss_gb"] for x in items)
    name = f"timing_{model}{os.environ.get('SUFFIX', '_p2') if passage else ''}.json"
    (out / name).write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
