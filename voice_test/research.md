<!-- via: codex, model: gpt-6-astra (reasoning effort: ultra) -->
# 中文民俗悬疑旁白：本地 TTS 技术调研

调研日期：**2026-11-01**。目标设备：**Apple Silicon M1，8GB 统一内存**。用途：可变现短视频的中文第一人称旁白，追求自然、克制、有情绪的讲述感。

本次仅联网读取仓库、许可证、模型卡及实现文档；未修改文件，未安装模型，未进行试听或本机内存测试。

**1. 结论**

1. **优先试听：Qwen3-TTS 1.7B CustomVoice，配合 speech.cpp 的 Q8_0 CPU 路径**——预置音色与文字语气指令兼备，无需参考音频，最贴近本题，但 M1 8GB 的实际峰值和速度未核实。[模型说明](https://github.com/QwenLM/Qwen3-TTS)、[移植说明](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/qwen3-tts.md)
2. **资源保守首选：Kokoro-82M-v1.1-zh**——模型小，官方支持 Mac CPU/MPS，中文编号音色随模型提供；代价是没有明确的情绪指令接口。[模型卡](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)、[Mac 支持](https://github.com/hexgrad/kokoro#macos-apple-silicon-gpu-acceleration)
3. **轻量备选：MOSS-TTS-Nano 100M ONNX**——官方提供 CPU 推理和内置音色，适合低资源试音；情绪控制、预置声源的独立授权说明及 M1 8GB 峰值未核实。[官方说明](https://github.com/OpenMOSS/MOSS-TTS-Nano#onnx-cpu-inference)
4. **以上是试用优先级，不是“全部硬约束已验收通过”的名单。**本次未找到足够证据，能把这三套具体配置都认定为已在 M1 8GB 上稳定完成中文旁白。
5. CosyVoice3、IndexTTS2/2.5、VoxCPM2 有表现力优势，但本机内存或参考声音授权仍有缺口；Spark-TTS、Llasa、F5-TTS 的官方权重存在非商用限制。

**2. 对比口径**

为便于阅读，将对比拆成“版本与许可”和“声音能力与运行条件”两张表。

- **“可商用”仅指所列代码和权重的许可。**参考录音、示例人物声音和素材本身的权利另算。
- 日期优先列模型发布日期、README 明示的重要更新；不能确认的最后更新时间写“未核实”，不把任意代码提交当成新模型发布。
- **8GB NVIDIA 显存不等于 8GB Mac 统一内存。**模型文件大小、权重驻留内存和完整推理峰值也不同。
- 用户限定一手资料，因此“中文自然度口碑”主要能核实官方自评与演示。**CER/WER 是读错率，SIM 是声音相似度，都不能直接证明“活人感”或克制叙事能力。**
- 推荐中的 speech.cpp 是社区维护者发布的实现，其文档属于该实现的一手资料，**不代表 Qwen 官方对 Mac 的认证**。

**2.1 版本、代码许可与权重许可**

| 项目 | 可核实版本及更新日期 | 代码许可证 | 权重许可证 | 商用结论 |
|---|---|---|---|---|
| **Qwen3-TTS** | 12Hz 系列，0.6B/1.7B；**2026-01-22** 发布。推荐具体为 **1.7B-CustomVoice**。[README](https://github.com/QwenLM/Qwen3-TTS) | [Apache-2.0](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE)；speech.cpp 另为 [MIT](https://github.com/nyosegawa/speech.cpp/blob/main/LICENSE) | 官方 [CustomVoice 模型卡：Apache-2.0](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)；所列 [GGUF 转换版同为 Apache-2.0](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF) | **可**，遵守许可与再分发通知要求；使用模型提供的预置音色，不输入真人或商业 TTS 参考。 |
| **Kokoro 中文** | **82M-v1.1-zh，2025-02-26**；推理库当前源码版本 0.9.4，二者不要混淆。[模型卡](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) | [Apache-2.0](https://github.com/hexgrad/kokoro/blob/main/LICENSE) | [Apache-2.0](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) | **可**。模型卡明确中文训练数据由龙猫数据许可提供；不据此推断其原始数据集也已向公众开放。 |
| **CosyVoice2 / CosyVoice3** | 2：0.5B，**2024-12**；3：**Fun-CosyVoice3-0.5B-2512，2025-12** 开放权重。[时间线](https://github.com/QwenAudio/CosyVoice) | [Apache-2.0](https://github.com/QwenAudio/CosyVoice/blob/main/LICENSE) | [2：Apache-2.0](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B)；[3：Apache-2.0](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) | **代码、权重可；参考声音有条件**。官方声明部分演示素材来自互联网，不能直接作为商业参考声音。[免责声明](https://github.com/QwenAudio/CosyVoice#disclaimer) |
| **IndexTTS2 / IndexTTS2.5** | 2：**2025-09-08**；2.5：**2026-08-10**，不能只按旧版比较。[README](https://github.com/index-tts/index-tts) | [bilibili 自定义模型许可](https://github.com/index-tts/index-tts/blob/main/LICENSE) | [2：bilibili Model Use License](https://huggingface.co/IndexTeam/IndexTTS-2/blob/main/LICENSE.txt)；[2.5 卡标同系列许可](https://huggingface.co/IndexTeam/IndexTTS-2.5)，但所链接完整许可文件对应关系有缺口 | **2 有条件**：超过 1 亿月活或上年收入超过人民币 10 亿元需另获许可；还有用途及通知义务。“低于 1 亿月活”不是唯一条件。**2.5 完整许可文本适用关系未核实**，不直接沿用旧版结论。 |
| **Spark-TTS** | 0.5B；2025-03 发布，README 列 **03-12** Triton 更新；后续权重版本未核实。[README](https://github.com/SparkAudio/Spark-TTS) | [Apache-2.0](https://github.com/SparkAudio/Spark-TTS/blob/main/LICENSE) | **[CC-BY-NC-SA-4.0](https://huggingface.co/SparkAudio/Spark-TTS-0.5B)**；模型卡明确从 Apache 改为 NC | **不可用于本次免费商用方案**。旧文章中的“Apache、可商用”已不适用于当前官方权重许可。 |
| **MegaTTS3** | **2025-03-22** 发布；更新权重版本未核实。[README](https://github.com/bytedance/MegaTTS3/blob/main/readme.md) | [Apache-2.0](https://github.com/bytedance/MegaTTS3/blob/main/LICENSE) | [Apache-2.0](https://huggingface.co/ByteDance/MegaTTS3) | **代码、权重可；参考素材有条件**。样例录音的独立商业声音授权未核实。 |
| **Step-Audio-TTS** | **TTS-3B，2025-02-17**；原仓库已停止维护。[README](https://github.com/stepfun-ai/Step-Audio/blob/main/README.md) | [Apache-2.0，仓库声明](https://github.com/stepfun-ai/Step-Audio#license-agreement) | [TTS-3B：Apache-2.0](https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B)；[Tokenizer：Apache-2.0](https://huggingface.co/stepfun-ai/Step-Audio-Tokenizer) | **可**，默认音色录音来源及独立声音授权未核实。 |
| **Step-Audio-EditX** | 后续 3B 模型；GitHub 列 **2026-01-29** 更新，HF 卡仍记 01-23。[README](https://github.com/stepfun-ai/Step-Audio-EditX) | [Apache-2.0，明确指 code](https://github.com/stepfun-ai/Step-Audio-EditX#license-agreement) | **未核实**：本次读取的 [模型卡及目录](https://huggingface.co/stepfun-ai/Step-Audio-EditX/tree/main)未给出明确的权重商用许可 | **未核实，不能放行**；不能继承旧 TTS-3B 的权重授权。 |
| **Higgs Audio 2 / 2.5** | v2 现名 Higgs TTS 2；许可标版本日期 **2025-06-20**。README 宣布 v2.5 1B，但独立官方权重发布及日期未核实。[归档 README](https://github.com/boson-ai/higgs-audio/blob/main/README_V2.md) | [Apache-2.0](https://github.com/boson-ai/higgs-audio/blob/main/LICENSE) | v2：[Boson Higgs Audio 2 Community License](https://huggingface.co/bosonai/higgs-tts-2-3b-base/blob/main/LICENSE)；v2.5 未核实 | **v2 有条件**：前一历年超过 **10 万年活用户**需另获许可，并有署名、上游条款和用途限制；不是“1 亿月活”。v2.5 未核实。 |
| **Higgs Audio 3 / Higgs TTS 3** | 4B；2026 年版本，许可证更新 **2026-07-08**；首次发布日期未核实。[模型卡](https://huggingface.co/bosonai/higgs-tts-3-4b) | [仓库代码 Apache-2.0](https://github.com/boson-ai/higgs-audio/blob/main/LICENSE) | [Research and Non-Commercial License，含 Creator Use Grant](https://huggingface.co/bosonai/higgs-tts-3-4b/blob/main/LICENSE) | **本用途有条件可**：允许在自己控制的频道发布并变现视频、播客等，须显著署名；不等于允许经营 TTS API、转售模型或任意商业产品集成。 |
| **Llasa** | 1B/3B/8B；模型卡可见更新 **2025-05-10**，更新版本未核实。[模型卡](https://huggingface.co/HKUSTAudio/Llasa-1B) | [官方训练代码 CC-BY-NC-4.0](https://github.com/zhenye234/LLaSA_training/blob/main/LICENSE) | [CC-BY-NC-4.0](https://huggingface.co/HKUSTAudio/Llasa-1B) | **不可用于本次免费商用方案**。 |
| **MOSS-TTSD** | **v1.0，2026-02-10**，8B。[README](https://github.com/OpenMOSS/MOSS-TTSD) | [Apache-2.0，仓库声明](https://github.com/OpenMOSS/MOSS-TTSD) | [Apache-2.0](https://huggingface.co/OpenMOSS-Team/MOSS-TTSD-v1.0) | **可**，参考声音另核；体量不适合本机作为主选。 |
| **MOSS-TTS 新系列** | v1.5：**2026-05-26**；Local Transformer v1.5：**2026-06-18**。[时间线](https://github.com/OpenMOSS/MOSS-TTS) | [Apache-2.0，仓库声明](https://github.com/OpenMOSS/MOSS-TTS) | [v1.5](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-v1.5)、[Local v1.5](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5)均 Apache-2.0 | **可**；不能因有 MLX 支持就认定 8GB 足够。 |
| **MOSS-TTS-Nano** | **100M，2026-04-10**；ONNX **04-17**；MLX 支持公告 **05-06**。[README](https://github.com/OpenMOSS/MOSS-TTS-Nano) | [Apache-2.0](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/LICENSE) | [TTS ONNX：Apache-2.0](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX)；[配套 Codec 模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX) | **代码、权重可**。内置音色的声源及独立授权说明未核实，故列轻量备选。 |
| **FireRedTTS / 1S / 2** | 1S：2025 年，**05-26** decoder 更新；2：**2025-09-08**，**09-28** BF16 更新。[1S](https://github.com/FireRedTeam/FireRedTTS/tree/fireredtts-1s)、[2](https://github.com/FireRedTeam/FireRedTTS2) | [原仓库/1S：MPL-2.0](https://github.com/FireRedTeam/FireRedTTS)；[2：Apache-2.0](https://github.com/FireRedTeam/FireRedTTS2) | [1S](https://huggingface.co/FireRedTeam/FireRedTTS-1S)、[2](https://huggingface.co/FireRedTeam/FireRedTTS2)卡标 Apache-2.0 | **有条件、存在声明冲突**：README 对零样本克隆仍有限于学术研究的表述；示例人物音色不能直接用于商业内容。 |
| **FireRedTTS3** | Base **2026-08-05**；Instruct **08-13**。[模型卡](https://huggingface.co/FireRedTeam/FireRedTTS3) | [Apache-2.0](https://github.com/FireRedTeam/FireRedTTS3/blob/main/LICENSE) | [Apache-2.0](https://huggingface.co/FireRedTeam/FireRedTTS3) | **有条件**：同样存在针对零样本克隆的学术用途声明；Instruct 的无参考 Voice Design 不属于该句明确限定的克隆路径。[声明](https://github.com/FireRedTeam/FireRedTTS3#usage-disclaimer) |
| **VoxCPM2** | 2026-04 模型；代码 release **v2.0.3，2026-05-11**。[README](https://github.com/OpenBMB/VoxCPM)、[Releases](https://github.com/OpenBMB/VoxCPM/releases) | [Apache-2.0](https://github.com/OpenBMB/VoxCPM/blob/main/LICENSE) | [Apache-2.0](https://huggingface.co/openbmb/VoxCPM2) | **可**，无参考音色设计路径适合本题；M1 8GB 运行条件未完成核实。 |
| **Chatterbox Multilingual** | 当前 README 为 **V3，0.5B**；源码包 0.1.7，V3 发布日未核实。[README](https://github.com/resemble-ai/chatterbox) | [MIT，官方仓库](https://github.com/resemble-ai/chatterbox) | [MIT，官方模型卡](https://huggingface.co/ResembleAI/chatterbox) | **可**；内置声音的独立声源说明未核实。不要把英语 Turbo/Nano 当成中文 V3。 |
| **Ming-3.0-tts-0.5B** | **2026-10** 发布；[ModelScope 页面](https://www.modelscope.cn/models/inclusionAI/Ming-3.0-tts-0.5B)检索记录显示 10-19 更新，是否为权重更新未核实 | [MIT](https://github.com/inclusionAI/Ming-3.0-tts/blob/main/LICENSE) | [MIT](https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B) | **可**；新模型值得关注，Mac 兼容证据不足。 |

**2.2 情绪控制、参考声音、Mac 与中文自然度**

下表中的“未核实”均保留其原意，不表示一定不能运行或一定不好听。

| 项目 | 情绪或语气控制方式 | 参考音频是否必需 | 是否有预置音色 | Mac 与内存证据 | 中文自然度证据及局限 |
|---|---|---|---|---|---|
| **Qwen3-TTS** | **1.7B-CustomVoice 支持文本指令**；VoiceDesign 可文字设计声音；**0.6B-CustomVoice 当前官方实现忽略 instruct** | CustomVoice、VoiceDesign 不需要；Base 克隆需要 | CustomVoice 有 9 个，包括中文 `Uncle_Fu`、`Serena` 等 | speech.cpp 支持 CPU/Apple Silicon；作者 **M5 Metal 短句**测试：1.7B Q8_0 峰值约 **2.46GB**。**不是 M1 CPU 数据**；长文内存会增长。[运行证据](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/qwen3-tts.md) | 官方展示语义、情绪与韵律控制；其 Base 评测不能直接当成 CustomVoice 量化中文旁白评分。悬疑叙事盲听未核实。[官方评测](https://github.com/QwenLM/Qwen3-TTS#evaluation) |
| **Kokoro v1.1-zh** | 音色、语速、标点及分句；没有已核实的自然语言情绪控制 | 不需要 | 有，模型卡列中英共 103 个音色 | 官方 CPU/MPS；82M 的 FP32 参数裸数据约 **0.33GB，属计算值**，不含框架、前端和中间张量；实际峰值未核实。[实现](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py) | 中文专门版本，但官方明确不是前版的全面升级；样例脚本还处理长音素序列“赶读”。因此适合作稳定基线，不能直接称表现力最佳。[模型卡](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)、[样例说明](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/blob/main/samples/make_zh.py) |
| **CosyVoice2 / 3** | 文本指令、参考风格、特殊标记；3 扩展情绪、速度、音量、方言等 | 官方 2/3 常用推理路径需要 | **不能把旧 300M-SFT 的“中文男/女”套到 2/3**；保存参考 speaker 不等于自带预置 | 官方有 CPU 路径；当前设备逻辑主要 CUDA/CPU，MPS 未自动启用；M1 8GB 峰值、速度未核实。[源码](https://github.com/QwenAudio/CosyVoice/blob/main/cosyvoice/cli/model.py) | 官方中文 CER：2 为 1.45%，3 base 为 1.21%、RL 为 0.81%；这是内容准确度，不是活人感评分。[评测](https://github.com/QwenAudio/CosyVoice#evaluation) |
| **IndexTTS2 / 2.5** | 情绪参考音频、8 维情绪向量、文字情绪描述；2.5 增加时长/语速及发音控制 | **音色参考必需**，情绪参考可选 | 未核实独立可商用预置音色包；examples 不等于授权音色库 | 源码支持 CPU/MPS，但 **MPS 强制 FP32**；2.5 卡称约 6GB NVIDIA 显存，**0.8B 只指 GPT 主干**。M1 8GB 未核实。[源码](https://github.com/index-tts/index-tts/blob/main/indextts/infer_v2_5.py)、[模型卡](https://huggingface.co/IndexTeam/IndexTTS-2.5) | 官方建议降低情绪强度获得更自然效果，符合“克制”的调参方向；本题盲听未核实。[README](https://github.com/index-tts/index-tts) |
| **Spark-TTS** | 性别、音高、语速参数创建虚拟声音；独立情绪指令未核实 | Voice Creation 不需要；克隆需要 | 可创建虚拟音色，不等于固定预置音色库 | 官方主要 Linux/NVIDIA 路径；M1 8GB 未核实 | 官方自述中英自然度好，但没有足以支持本题排名的独立中文口碑；且权重 NC 已阻断商业使用。[模型卡](https://huggingface.co/SparkAudio/Spark-TTS-0.5B) |
| **MegaTTS3** | 参考声音、口音强度；完整情绪控制未核实 | **需要 `.wav` 与对应 `.npy` latent** | 有样例对，独立商业授权未核实 | 官方有 CPU 推理；**WaveVAE encoder 未开放**，不能任意参考音频全程本地编码；M1 8GB 峰值未核实 | 官方强调质量与可控性；其 CPU “约 30 秒”描述缺少可比硬件/音频长度，不能作为本机速度承诺。[README](https://github.com/bytedance/MegaTTS3/blob/main/readme.md) |
| **Step-Audio-TTS-3B** | 情绪、方言、语速等文本控制 | 默认 speaker 不需要；克隆需要 | 有默认 speaker | 官方 CUDA/Linux，TTS 表列最低 8GB **显存**，Tokenizer 另有开销；Mac 8GB 未核实 | 官方展示表达能力；是否自然克制而非表演化，未核实。[README](https://github.com/stepfun-ai/Step-Audio/blob/main/README.md) |
| **Step-Audio-EditX** | 对情绪、风格进行文字编辑，可 serious、whisper 等 | 官方常用示例需要 | 无参考预置路径未核实 | 官方 CUDA；12GB 临界、16GB 更安全；节省配置中的 6–8GB 为 GPU 估算，非 Mac 证据 | 功能适合局部修正情绪，但商业权重许可和本机运行均未核清。[README](https://github.com/stepfun-ai/Step-Audio-EditX) |
| **Higgs 2 / 2.5** | v2 根据语境生成韵律；Smart Voice 自动选择声音；也可参考 | v2 可不提供 | 自动声音不等于可重复选择的固定预置库；样例包权利未核实 | v2 官方建议至少 **24GB GPU 内存**；“3B”不能忽略 audio adapter。2.5 本地权重及内存未核实 | 官方强调对话及表现力；中文克制旁白的独立评价未核实。[归档 README](https://github.com/boson-ai/higgs-audio/blob/main/README_V2.md) |
| **Higgs 3** | 行内情绪/风格/韵律标签，如沉思、低表现力、语速及停顿 | 可无参考纯文本；也可克隆 | 本地预置音色包未核实，不能把付费 API 音色库算进去 | 原始权重文件约 **9.31GB**，尚未计运行时；原始配置不适合作为 8GB 主选，量化 Mac 路径未核实。[文件目录](https://huggingface.co/bosonai/higgs-tts-3-4b/tree/main) | 功能贴合克制叙事，但公开性能主要为 H100；中文旁白独立口碑未核实。[模型卡](https://huggingface.co/bosonai/higgs-tts-3-4b) |
| **Llasa** | 参考音频条件；独立情绪指令未核实 | 可纯文本，也可参考 | 未核实 | 官方示例 CUDA，另需 XCodec2；M1 8GB 未核实 | 官方研究展示中英生成能力；本题自然度未核实，且 NC 排除商用。[模型卡](https://huggingface.co/HKUSTAudio/Llasa-1B) |
| **MOSS-TTSD v1.0** | 多说话人、上下文和参考风格；主要面向对话 | 并非全部模式必需 | 固定预置库未核实 | 8B 主干仅 16 位参数裸数据就约 **16GB，属计算下限**，还需 Codec/cache；M1 8GB 不作为主选 | 官方强调 1–5 人长对话；这不能自动转化成单人第一人称旁白优势。[README](https://github.com/OpenMOSS/MOSS-TTSD) |
| **MOSS-TTS v1.5 / Local v1.5** | 标点、停顿标签；另有 VoiceGenerator 做文字音色设计 | 可选 | 不同模型能力分开；不能把 VoiceGenerator 能力全部算给基础 TTS | 主版 8B、Local 4B；已宣布 MLX 支持，但 M1 8GB 峰值未核实 | 官方多语言评测与演示；中文克制叙事独立口碑未核实。[README](https://github.com/OpenMOSS/MOSS-TTS) |
| **MOSS-TTS-Nano** | 内置声音、文本分句、采样参数；独立情绪指令未核实 | ONNX 内置音色模式不需要外部参考 | 有，CLI 默认 `Junhao` | 官方记录 **M4 Air 单核 CPU**顺畅运行；100M TTS 加约 20M Codec，但无 M1 8GB 峰值。官方 Python 封装仍导入 Torch，不能称完全无 Torch。[README](https://github.com/OpenMOSS/MOSS-TTS-Nano)、[封装代码](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/onnx_tts_runtime.py) | 官方定位为小体积、实时产品够用的质量；不足以认定它比大模型更有活人感。[模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) |
| **FireRedTTS / 1S / 2** | 1S 参考风格；2 多人对话与上下文 | 1S 需要；2 可随机声音或参考 | 固定可商用预置库未核实 | 2 官方 BF16 仍约 **9GB VRAM**，此前约 14GB；不能当成 8GB Mac 可用证据 | 有中英、多说话人演示；中文单人自然克制评价未核实。[2 README](https://github.com/FireRedTeam/FireRedTTS2) |
| **FireRedTTS3** | **Instruct 文字设计声音**，支持情绪、年龄、音色、语速、口音；兼语音编辑 | Instruct Voice Design 不需要 | 可设计新声音，不等于固定预置库 | 官方 main 仍含 CUDA/FlashAttention 依赖；Mac PR 未合并。社区 MLX 文档仅支持 Base，**不支持 Instruct Voice Design**。[PR](https://github.com/FireRedTeam/FireRedTTS3/pull/6)、[MLX 文档](https://github.com/appautomaton/mlx-speech/blob/main/docs/fireredtts3.md) | 官方中文 CER 1.01%、SIM 80.9%；不代表旁白风格已经获验证。[官方评测](https://github.com/FireRedTeam/FireRedTTS3#performance) |
| **VoxCPM2** | **无参考文本音色设计**，可控制年龄、音色、情绪、速度；也可参考 | 不必需 | 可设计声音，固定预置库未核实 | 官方 CPU/MPS，且链接 GGUF 路径；2B，M1 8GB 峰值和速度未核实 | 官方 Seed-TTS 中文 CER 0.97%、SIM 79.5%；作为表现力候选有依据，不能据此宣布中文活人感第一。[README](https://github.com/OpenBMB/VoxCPM) |
| **Chatterbox Multilingual V3** | `exaggeration`、CFG 等参数；不是任意自然语言风格指令 | 有内置条件，可不提供 | 有默认声音条件，声源独立说明未核实 | README 支持 CPU/MPS；Mac 例子主要是旧英语类，不能算中文 V3 的 M1 8GB 实测 | 当前支持中文；官方泛化质量宣传不能代替中文 V3 盲听。须显式选 V3，代码默认仍可能为 V2。[README](https://github.com/resemble-ai/chatterbox)、[实现](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/mtl_tts.py) |
| **Ming-3.0-tts-0.5B** | 无参考 Voice Design/Freeform；情绪、速度、音高、响度及副语言标签，模式有组合限制 | 不必需 | 有中文“灵楷”“灵小柔”等 | 官方验证主要 H800/H20 CUDA；MPS 未核实；约 2.96GB 权重文件不能等同运行内存 | 官方中文 WER 0.800%、SIM 0.758；README 引用的英语榜单不能改写成中文第一。[README](https://github.com/inclusionAI/Ming-3.0-tts) |

**3. 推荐项目的 Mac 本地安装要点**

以下是供后续执行的安装与调用说明，**本次均未执行**。

**3.1 Qwen3-TTS：优先用 1.7B-CustomVoice 的量化 CPU 路径**

推荐具体组合：

- 模型：`Qwen3-TTS-12Hz-1.7B-CustomVoice`。
- 本地运行时：`nyosegawa/speech.cpp`。
- 首选量化：`Q8_0`；内存有压力再比较 `Q6_K`。
- 推理设备：明确使用 `--device cpu`，满足本题允许的 CPU 路径；这里不把 Metal 当作 PyTorch MPS。
- **Python 版本：此路径不需要 Python。**下载 macOS Apple Silicon release；源码构建要求 CMake ≥3.20、C++17。[安装文档](https://github.com/nyosegawa/speech.cpp/blob/main/docs/install.md)

模型地址：

- [官方 Hugging Face 权重](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [官方 ModelScope 镜像](https://modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [speech.cpp 专用 GGUF](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF)

GGUF 已包含该实现所需的 Codec decoder。**这些文件不能因为后缀是 GGUF 就直接交给 Ollama、LM Studio 或普通 llama.cpp**；转换作者明确限定运行时。Q8_0 要求 speech.cpp ≥0.7.0，Q6_K 等要求 ≥0.8.0。[转换模型说明](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF)

安装运行时后，可用以下形式做短句验证：

```bash
speech tts qwen3-tts-1.7b \
  --device cpu \
  --voice uncle_fu \
  --language zh \
  --instructions "像向熟人回忆一件亲身经历的事。口语自然，情绪克制，语速中等，关键处稍作停顿。" \
  -o narration.wav \
  "那天回村，已经快十点了。我刚走到老屋门口，就发现门槛上，多了一双湿鞋。"
```

参数来自该实现的 [CLI](https://github.com/nyosegawa/speech.cpp/blob/main/docs/cli.md) 和 [Qwen3 专页](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/qwen3-tts.md)。这段提示词是本报告的试音建议，效果未试听。

关键依赖与选择坑：

- **不要为了省内存直接改成 0.6B，然后期待同样的情绪指令。**0.6B 模型卡有相关宣传，但官方实现对该型号把 `instruct` 清空；本报告按可执行实现判定。[官方代码](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)
- 如果采用官方 Python 包，README 推荐 **Python 3.12**，当前依赖固定 `transformers==4.57.3`、`accelerate==1.12.0`。官方示例中的 CUDA、BF16、FlashAttention 2 不是可直接复制到 M1 的安装方案。[依赖文件](https://github.com/QwenLM/Qwen3-TTS/blob/main/pyproject.toml)
- M5 Metal 的约 2.46GB 是作者短句进程峰值；**M1 CPU 峰值、实时倍率和长篇稳定性未核实**。初次验证应按短段落逐段生成，不以整篇长文作为第一次测试。

参考音频：**不需要**。只使用 CustomVoice 的模型内置声音，不调用 Base 的克隆接口，不采用网上人物录音或商业 TTS 导出的声音。

**3.2 Kokoro：明确选 v1.1-zh，不混用旧中文音色列表**

推荐 **Python 3.11 或 3.12 的独立环境**。当前包声明支持 `>=3.10,<3.14`；README 中旧 Conda 示例的 Python 3.9 不应作为当前安装依据。[pyproject](https://github.com/hexgrad/kokoro/blob/main/pyproject.toml)

核心依赖：

```bash
python -m pip install "kokoro==0.9.4" "misaki[zh]>=0.9.4" soundfile
```

中文必须安装 `misaki[zh]`；英文混读及回退涉及 `espeak-ng`。官方模型卡中的 `apt-get` 是 Linux 命令，Mac 应使用对应的本机依赖安装方式。[推理库说明](https://github.com/hexgrad/kokoro)

模型与音色地址：

- [完整模型仓库](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)
- [模型文件、配置及 voices 目录](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/tree/main)
- [官方中文样例脚本](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/blob/main/samples/make_zh.py)

调用时明确设置：

```python
from kokoro import KPipeline

pipeline = KPipeline(
    lang_code="z",
    repo_id="hexgrad/Kokoro-82M-v1.1-zh",
    device="cpu",
)

generator = pipeline(
    "那天回村，已经快十点了。我刚走到老屋门口，就发现门槛上，多了一双湿鞋。",
    voice="zm_010",
    speed=1.0,
)
```

这是根据官方 API 整理的调用片段，未执行。`zm_010` 和 `zf_001` 出现在官方 v1.1-zh 样例中；不要照搬旧版 `zm_yunxi` 等名字并假定与新版兼容。

如尝试 MPS，需在启动 Python 前设置：

```bash
PYTORCH_ENABLE_MPS_FALLBACK=1 python your_script.py
```

当前实现会检查 MPS 与 fallback 条件；CPU 是可用的保守路径。[Mac 说明](https://github.com/hexgrad/kokoro#macos-apple-silicon-gpu-acceleration)、[设备选择实现](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py)

参考音频：**不需要**。使用 v1.1-zh 自带的中文音色张量。模型卡说明中文数据来自获许可的专业数据集；本次不使用其额外英语合成音色，也不从外部商业 TTS 制作参考。

适用边界：Kokoro 没有已核实的“用克制、迟疑的语气说”等指令接口。情绪主要靠台词、分句、标点和音色选择；不要把情绪说明直接放进正文，避免被念出来。

**3.3 MOSS-TTS-Nano：使用官方 ONNX CPU 与内置声音**

官方示例采用 **Python 3.12**，包最低要求 Python 3.10。当前依赖包括：

- `torch==2.7.0`
- `torchaudio==2.7.0`
- `transformers==4.57.1`
- `onnxruntime>=1.20.0`
- `WeTextProcessing`、`soundfile`

来源：[pyproject](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/pyproject.toml)、[requirements](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/requirements.txt)。

模型需要成对准备：

- [MOSS-TTS-Nano-100M-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX)
- [MOSS-Audio-Tokenizer-Nano-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX)

官方入口在缺少本地模型时会自动下载。使用内置声音、不传外部参考的调用形式为：

```bash
python infer_onnx.py \
  --execution-provider cpu \
  --cpu-threads 4 \
  --voice Junhao \
  --text "那天回村，已经快十点了。我刚走到老屋门口，就发现门槛上，多了一双湿鞋。"
```

`Junhao` 是当前脚本默认的内置 preset；省略 `--prompt-audio-path`，避免进入外部声音克隆路径。[参数源码](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/infer_onnx.py)

主要坑：

- README 宣称 ONNX 推理移除了 PyTorch 依赖，但当前 Python 封装顶层仍导入 `torch`、`torchaudio`。**不能承诺现成 Python CLI 完全不需要 Torch。**[封装源码](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/onnx_tts_runtime.py)
- `WeTextProcessing/pynini` 安装失败时，官方建议先通过 conda-forge 安装 `pynini=2.1.6.post1`；应使用适配 Apple Silicon 的环境。[安装说明](https://github.com/OpenMOSS/MOSS-TTS-Nano#environment-setup)
- M4 Air 单核结果只是官方对该设备的报告；M1 8GB 的峰值、中文实时倍率未核实。
- **内置 preset 的原始声源和独立声音授权说明未核实。**因此它属于轻量技术备选，不能把代码与权重 Apache 许可扩写为已经查清每位声源的全部权利。

参考音频：此路径**不需要用户提供**。本次没有确认一个可额外推荐、同时满足商业使用与不模仿现实人物要求的参考录音清单。

**4. 参考音频来源的处理结论**

前三个建议均优先使用模型内置音色，避免为本次任务寻找真人录音。

对于必须依赖参考的模型，本次没有把以下内容认定为可直接用于商业旁白的声音来源：

| 来源 | 本次核实结果 |
|---|---|
| CosyVoice 的网页演示、`asset` 示例 | 项目声明部分素材来自互联网、用于学术展示；逐条商业声音授权**未核实**。[免责声明](https://github.com/QwenAudio/CosyVoice#disclaimer) |
| IndexTTS 的 examples | 文件可下载不等于已取得商业模仿该声线的许可；独立授权**未核实**。[仓库](https://github.com/index-tts/index-tts) |
| MegaTTS3 的 `.wav/.npy` 样例对 | 可用于技术演示，但独立商业声音授权**未核实**；且未开放 encoder 限制自选素材流程。[README](https://github.com/bytedance/MegaTTS3/blob/main/readme.md) |
| FireRedTTS2 播客人物示例 | 官方明确提示相关真人声音未经授权不得使用，不作为本项目素材。[README](https://github.com/FireRedTeam/FireRedTTS2) |
| 开源数据集中的录音 | 必须分别确认具体数据集版本、录音许可及声音合成用途；本次没有完成满足上述条件的逐条核实，**不凭数据集名称推荐克隆**。 |

模型卡描述的训练数据许可，也不自动授予下载、重新分发其原始录音的权利。Kokoro 的龙猫数据说明可支持理解模型来源，不能据此提供一个并未公开许可的原始参考音频下载方案。

**5. 排除项及理由**

- **Spark-TTS 当前官方权重**：CC-BY-NC-SA-4.0，模型卡明确说明已从 Apache 改为非商用。不能仅查看代码许可证。[权重卡](https://huggingface.co/SparkAudio/Spark-TTS-0.5B)
- **Llasa 官方权重**：CC-BY-NC-4.0；免费商业旁白不满足许可。[权重卡](https://huggingface.co/HKUSTAudio/Llasa-1B)
- **F5-TTS 官方预训练权重，包括 F5TTS_v1_Base**：代码 [MIT](https://github.com/SWivid/F5-TTS/blob/main/LICENSE)，权重 [CC-BY-NC-4.0](https://huggingface.co/SWivid/F5-TTS)。更换推理前端、转 ONNX/MLX 或量化不会消除原权重的 NC 条件。
- **Fish Audio S2 Pro**：当前权重为 Research License，商业使用需另行许可，不符合本次免费商用目标。[官方模型卡](https://huggingface.co/fishaudio/s2-pro)
- **Fish Audio Drama 3**：不能与 S2 Pro 一概判为禁商用。当前社区许可允许符合条件的小规模商用，门槛为本人及关联方合计过去 12 个月总收入低于 **50 万美元**，并限制对外提供自助语音生成服务；但 35B 总参数及现有本地转换体量明显不适合作为 M1 8GB 主选。[许可](https://github.com/fishaudio/fish-speech/blob/main/LICENSE)、[模型卡](https://huggingface.co/fishaudio/drama-3)
- **Higgs 3 原始配置**：本次不因许可证标题含“Non-Commercial”而错误排除自媒体变现；其 Creator Use Grant 明确提供例外。排除主选的原因是原始模型体量及缺少适用的 M1 8GB 证据。[许可](https://huggingface.co/bosonai/higgs-tts-3-4b/blob/main/LICENSE)
- **Higgs 2、MOSS-TTSD 8B、MOSS-TTS 主版、FireRedTTS2**：现有内存要求或体量不支持把它们列为本机稳妥方案；不将别的平台显存结果改写成 Mac 可运行。
- **Step-Audio-EditX**：权重商用许可未核实；官方部署又以 CUDA 为主。
- **FireRedChat 专用 `fireredtts1s_4_chat` 权重及相关音色**：官方明确非商用，不能与通用 FireRedTTS-1S 的模型卡混淆。[专用服务说明](https://github.com/FireRedTeam/FireRedChat/blob/main/fireredtts-server/README.md)
- **CosyVoice2/3、IndexTTS2/2.5、MegaTTS3**：未作为本次主选，主要因为参考音频流程和素材权利未闭合，另有 M1 8GB 运行证据不足；这不是对其音质的否定。
- **VoxCPM2、FireRedTTS3-Instruct、Ming-3.0-tts-0.5B**：无参考音色设计很契合本题，保留为后续质量候选；当前不能将 Mac 移植、参数量或 CUDA 成功记录说成本机成功。

**6. “活人感”的实际选型标准**

本报告的优先级是基于功能、许可和部署证据的判断，**没有进行听感排名**。后续试听应使用同一段原创中文，比较以下四项：

1. **像在对人讲述**：重音随句意变化，而不是每句话都像标题或解说词。
2. **情绪有变化但收得住**：从平常到疑惑、紧张有过渡，不自动加喘息、笑声、哭腔或戏剧化耳语。
3. **内容准确**：不漏字、重复、错读人名地名及民俗词汇。
4. **连续一致**：相邻段落音色、响度和语速稳定，长一点的句子不突然赶读。

对支持指令的模型，可从这一条开始，而不是堆叠强情绪标签：

> 像向熟人回忆一件亲身经历的事。普通口语，情绪克制，语速中等。平常处自然说，发现异常时稍微放慢，关键句后短暂停顿。

“不要夸张呼吸、笑声、口癖、戏腔、播音腔”应作为试听淘汰标准；不能假定一条负面提示就会被所有模型稳定遵守。