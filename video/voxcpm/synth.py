"""VoxCPM2（OpenBMB，代码和权重 Apache-2.0，可商用）：用文字描述设计声音，整段合成，不逐句拼接。"""
import sys, time
from pathlib import Path
import soundfile as sf
from voxcpm import VoxCPM

TEXT = "我赶回村时，爷爷已经死了。到后半夜，门外有了敲门声。我抬起头。隔着门，又听见了爷爷的声音。火柴被我扣住了。门没开，东西也没递出去。可那声哎，已经收不回来了。"
VOICES = {
    "voxcpm2_a": "一个十九岁的北方年轻男人，嗓音偏低、干净，像对着一个朋友讲一件自己亲身经历过的真事，自然有起伏，有情绪但克制，不表演，不播音腔",
    "voxcpm2_b": "一个二十岁左右的男生，声音有点沙哑，深夜里压低声音跟朋友讲自己遇到的怪事，语速自然，说到关键处会慢下来，带一点后怕，但不夸张",
}
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
for name, desc in VOICES.items():
    t = time.time()
    wav = model.generate(text=f"({desc}){TEXT}", cfg_value=2.0, inference_timesteps=10, seed=42)
    out = Path("voice_test") / name / "full.wav"; out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, wav, model.tts_model.sample_rate)
    dur = len(wav) / model.tts_model.sample_rate
    print(f"{name}: 音频 {dur:.1f}s，耗时 {time.time() - t:.0f}s", flush=True)
