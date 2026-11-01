# 00-交接文档-Claude与Codex

谁接手，先读完本文和文末的「交接日志」再动手。每次交出去或接回来，都在交接日志末尾追加一条：时间、谁、做了什么、改了哪些文件、下一步。交回 Claude 时，只要说“读 HANDOFF.md 和交接日志，继续”。

本文的权威版本是仓库 garcci/yiwenbu 分支 `claude/project-thread-l4wz3r` 根目录的 `HANDOFF.md`。推送后会自动同步成云盘根目录的谷歌文档「00-交接文档-Claude与Codex」，所以改动请改仓库文件，不要直接改云盘文档。

本文由 AI（Claude）生成。

## 一、项目规则（用户定的，必须遵守）

1. **文件规则**：所有交付文件放谷歌云盘，项目根目录是 https://drive.google.com/drive/folders/1AXGu_r0jWQOMKNU9ZTaJZJDeaB2ep2UD ，每条赛道一个子文件夹。聊天里只发云盘链接，不发文件，也不发本机路径。云盘里只留最终版本。文件命名用「序号-内容-用途」。
2. **花钱规则**：免费优先。任何花钱的步骤，先估算费用，等用户同意再做。用户 2026-11-01 已明确说“不要新增费用了”。
3. **对外规则**：发布、对外发消息、删除这类不可撤销的操作，先等用户确认。
4. **标注规则**：AI 生成的内容要标注。视频首帧写“原创虚构｜AI画面与AI配音”。
5. **汇报规则**：每完成一步，或者卡住，立刻用一句话告诉用户。用户纠正过两次，这一条很重要。
6. **分工规则**：起草、扩写、审稿、改稿交给 codex 和 agy（Gemini）。agy 审稿和调研不可靠，关键核对交给 codex。
7. **密钥规则**：密钥只放 GitHub 仓库 secrets，绝不让用户在聊天里贴。
8. **封号风险**：火山方舟套餐（Agent Plan）里的文本模型禁止用脚本调用，否则可能封号。套餐里的 Seedream 出图和豆包语音 2.0 可以用脚本调。
9. **提交署名**：commit 信息末尾按当前助手的要求写署名行。

## 二、仓库与密钥

- **仓库**：garcci/yiwenbu。工作分支 `claude/project-thread-l4wz3r`，讨论和视频相关的东西都在这里。
- **Secrets（只列名字）**：
  - 火山：`ARK_API_KEY`（方舟套餐，地址 `/api/plan/v3`）、`ARK_PAYG_API_KEY`（按量付费，现在不用）。
  - 万相：`DASHSCOPE_API_KEY`（阿里云百炼）。
  - 云盘：`GDRIVE_CLIENT_ID`、`GDRIVE_CLIENT_SECRET`、`GDRIVE_REFRESH_TOKEN`、`GDRIVE_FOLDER_ID`。
  - 其他：`GEMINI_API_KEY`（免费额度常用完）、`LLM_API_KEY`（智谱，兼容 OpenAI 接口）。
- **用户的 Mac**：
  - 讨论用的仓库克隆在 `~/Documents/yiwenbu-discuss`。
  - codex 命令：`codex exec --skip-git-repo-check --ephemeral -s read-only -m gpt-6-astra -c model_reasoning_effort='"ultra"' -o out.md - < prompt.md`
  - agy 命令：在空的临时目录里运行 `agy -p "$(cat prompt.md)" --model gemini-3.8-flash-high --sandbox --print-timeout 1500s > out.md`
  - 以上都通过 `discuss/run_ai.sh` 调用，它带超时，防止 agy 输出完后进程不退出。
  - Mac 只有 8GB 内存，用户还要同时开 Claude 和 Codex，所以**不要在本机跑模型**，模型一律放到 GitHub Actions 上跑。
  - Mac 的自动审核会拦“运行外部代码”和“推送”，需要用户在对话里亲口同意。

## 三、GitHub Actions 流水线（推送对应文件就会触发）

| 工作流 | 触发文件 | 作用 |
|---|---|---|
| docs_to_drive.yml | `discuss/publish.txt`、`HANDOFF.md` | 把 markdown 转成谷歌文档写进云盘，同名的覆盖。publish.txt 每行格式：`本地路径\|云盘文件夹ID\|文档名` |
| wan_i2v.yml | `video/wan_request.json` | 万相图生视频：从云盘取首帧，成片写回云盘。wan3.0 免费额度还剩 20 秒，约 11-05 到期；用户说先别动 |
| stills_sample.yml | `video/stills_request.json`、`video/stills_sample.py` | 低成本静帧成片：Seedream 出连续多帧，加深度视差、快切、雪和灯光特效、合成音效、豆包配音 |
| voice_test.yml | `video/voice_test.py`、`voice_test/**` | 配音盲听拼接，上传云盘。有 `voice_test/passage2.txt` 时跑第二轮（文件名 05-配音盲听2-X） |
| oss_tts.yml | `video/oss_tts/**` | 开源 TTS 用 CPU 合成：CosyVoice2、CosyVoice-SFT、Qwen3-TTS、Kokoro，结果提交回 `voice_test/<套名>_p2/` |
| voxcpm.yml | `video/voxcpm/**` | VoxCPM2 用文字描述设计声音，整段合成。CPU 上前两次被中止过，已关掉 torch.compile，并加了交换区 |
| seedance.yml、daily.yml 等 | — | 旧的流水线，现在不用 |

## 四、重要云盘文档

- 短视频文件夹：https://drive.google.com/drive/folders/11uMWY64q_tLolJ210NmLhfqnkW1D5fBR
- 小说文件夹 ID：`1gnSv8eSD1HPJxncsUgVI40mGJ7e6g1qG`
- 设定集定稿 v3：https://docs.google.com/document/d/1e6MUolkd24tgu-do2arDQUZuC4sevveW0tlt-WsH638/edit
- 第一集制作包 v2（28 镜）：https://docs.google.com/document/d/1qzMwS5NbiRoqxhXkhgSdhcYxzrZm2NvlniVo0TaG6xY/edit
- **第一集配音稿 v3（大改版，最新）**：https://docs.google.com/document/d/1sgVAhlQKWYaghIETQL_in_tQK8MAJvQk0fxbcO29jAE/edit 。这一版带来的连带改动见文末，涉及设定集第 2 到 5 章和分镜重排，等用户拍板。
- 审稿文档：https://docs.google.com/document/d/1HqD1Qd6my2sijR7bFMJfdROkPrbKdGUsXaoH1Rj8b0Y/edit
- 悬疑博主手法拆解：https://docs.google.com/document/d/1SeR1E5sRlB_y6UXX1CaEqdmz3vetCNchYl_33LLLXxk/edit
- 视频模型比价：https://docs.google.com/document/d/1j8yNk5Aq9iArOzFkVFB0oMdPtS7HSRbHi64wE3Vx174/edit
- 已出的样片（都在短视频文件夹）：
  - 02-第一集镜06-万相试用.mp4（wan2.6，用户觉得比 3.0 好）
  - 02-第一集镜06-万相3.0试用.mp4
  - 03-第一集低成本小样-镜02镜20.mp4
  - 04-配音盲听-A~K
  - 05-配音盲听2-A~

## 五、各条工作线：现状和下一步

### 1. 第一集视频（本线程）
- **画面路线已定**：低成本做法，用户说“就这样做”。
  - 画面全部用 Seedream 出连续多帧，靠分层视差、快切、特效做出动感。
  - 不做单张图推拉，用户不喜欢。
  - 新增费用为 0。
- **配音还没定，是现在的卡点**。用户的标准：像人对人讲故事，有起伏、有情绪、有共鸣；不刻意，不要播音腔。
  - **第一批**（04-配音盲听）：A~G 是豆包逐句合成，用户听了全都不行；之后去掉强行拉齐语速重出过。H~K 是开源模型逐句合成。
    - 教训：逐句合成，再强拉统一语速、固定停顿，会把语气起伏抹平。
  - **第二轮**（05-配音盲听2）：用新稿里“天快亮”那一段（`voice_test/passage2.txt`），整段合成。
    - A~E 是豆包加“讲真事”语气提示，五个音色：A=shaonianzixin，B=m191，C=liufei，D=taocheng，E=dayi。
    - F 往后是开源模型，按目录名排序：cosyvoice2_p2、cosyvoice_sft_p2、kokoro_zh_p2、qwen3_tts_p2、voxcpm2_a_p2、voxcpm2_b_p2。
    - 正在跑：oss_tts run 41285165506，VoxCPM2 run 41285038388。
  - 编号对照表不要告诉用户，等用户盲听挑完再揭晓。
  - 写法调研结论见 `voice_test/research_writing.md`，开源模型对比见 `voice_test/research.md`。
  - 许可证：CosyVoice、Qwen3-TTS、Kokoro、VoxCPM2 都是 Apache-2.0，可以商用。F5-TTS、Fish Speech、Spark-TTS 不能商用。
- **下一步**：
  1. 用户选定声音。
  2. 按配音稿 v3 整段配音，配音决定时间轴。
  3. 用最终音频转写出字幕时间轴，字幕单行，放在平台底部按钮之上。
  4. 按新稿重排分镜：参考 `discuss/08-第一集资产表与开头-agy.md`，以及 codex 的核对 `discuss/r08_check.md`（指出开头一和开头三有问题）。
  5. 用 stills_sample 流水线出全集。先给用户 15 秒预览，再渲染全片。
  6. 剩下的 20 秒万相免费额度：改成 4 段×5 秒、固定机位、只写小动作，提示词写明“房间结构与首帧一致”。
- **用户分享过、待吸收的资料**：
  - Codex+Hyperframes 拆爆款工作流：声音决定时间轴；同一集做 3 个开头。
  - sweety-handdraw-video：句尾按“最后一个字之后的第一段静音”裁切再淡出。
  - ArcReel（AGPL）：可借鉴资产库复用、导出剪映草稿。
  - ai-manju-skills。

### 2. 审稿线程（剧本和设定）
- 正在用 codex 改：设定集 v4、故事梗概、第一集制作包 v3、核对报告。该线程会自己在本文追加一节。

### 3. 其他变现线程（等用户选择）
- 拼豆图纸自动生成工具。
- 小红书图文信息差起号。
- 女性情感图文：咨询变现不合规，结论是暂不做。
- 低价心理测评店。
- 以上各自的现状见项目记忆和各线程。

## 六、交接日志（只在末尾追加，不要改前面的）

- 2026-11-01 07:40 Claude：Claude 额度到 90%，交接给 Codex。云端还在跑 oss_tts（41285165506）和 VoxCPM2（41285038388）；跑完会自动出 05-配音盲听2 的 F 往后几版，并上传云盘。接手后：
  1. 确认这两个运行是否成功，失败就看日志修。
  2. 把 F 往后的编号告诉用户去听。
  3. 等用户选声音，再按上面「下一步」继续。
