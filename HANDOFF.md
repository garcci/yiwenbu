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


## 2026-11-02｜Codex当前文字修订与备份交接（追加，不替换以上历史）

本次用户较新的AGENTS.md及明确授权优先于以上较早规则；已授权任务内的读取、编辑、验证与本任务分支普通非强制推送无需逐步重复审批。公开发布、生产写入/部署、费用、购买、签名认证、权限变更等仍按最新用户授权边界执行。零新增费用；不上传凭据、登录态或私钥。

持续交接source of truth：[Google交接原件](https://docs.google.com/document/d/1S8MJ-5hafqAAKbRImdjcQP24ftSiGt0zRIcKkSP_jXA/edit)。本仓库HANDOFF是fallback入口。当前任务目录：`discuss/novel_rebuild_20261101/`。

- [最新小说v3云原件](https://docs.google.com/document/d/1nApEHgezhPfpC9CDAy6DiPWUE61qy6C_g0kyvzxgJxM/edit?tab=t.2n1oox91uiw0)
- [最新首集v4云原件](https://docs.google.com/document/d/1nu552mG0HWaH00-zmQr9oXVN6J4ydGvMeprpszUVEAM/edit?tab=t.nktou8fv2nec)
- [最新全季结构v3云原件](https://docs.google.com/document/d/1nu552mG0HWaH00-zmQr9oXVN6J4ydGvMeprpszUVEAM/edit?tab=t.5takfst62596)

本地对应`novel_complete_v3.md`、`episode01_candidate_v4.md`、`season_outline_candidate_v3.md`，与`review_round03/`冻结三源逐字节相同；input_hash=`d4ff7bf95b35150a1cb9f61d7ee691a18bc4dbb4dd356434e1ecd886bfdee57f`。首集29发声行691汉字、12场311秒；六集文字规划311/320/290/360/295/315秒，合1891秒（31:31），不是实读/成片时长。来源与变更见相邻manifest/coordination_record；Gemini为主要创作基础，小说五六节及本轮六七局部、首集衔接含Sol辅助，不能冒称全部Gemini。未采用有事实错误的Flash-Lite八补丁。

门槛仍是十个独立AI模拟视角×十维×三作品，300格每格≥9.5；**目前未达，无本版新媒体**，新文件不继承旧评分。旧首轮完整Sol记录最低7.5、282格低于9.5；[评分表19](https://docs.google.com/spreadsheets/d/1jvdfFOQWyOaLUyXdtHqNtS6yGU0X9x-JNS038xoWR78/edit)仅旧首轮。round02只有08/09两个同源部分辅助原评，各最低8.5，不当十位齐备。Flash-Lite整本评审的有关依据在澄清中撤回，原件保留作审计，不作为有效正式终评；改稿者不评该稿。

主要下一步：先取得高级Gemini真实可用后的独立终评，实质修稿并满足文字门槛，再确认免费/已有额度后生成音画与本地合成。上次高级模型页面显示用量100%、每周11%，提示11月2日08:20重置，页面时区未标；这些是历史状态，使用前重查，不能只因到点宣称恢复。不使用Astra，不换地区、账号或网络规避限制。

`Result-4.wav`仅音色参考，不当最终配音；“未命名.m4a”及六个29秒片段只留本地、禁云盘。用户已认可参考图人物与质感，不等于当前成片通过。`video/local_renderer/`仅有历史编译与dry-run，当前导出/混音/同步未验证；不启动费用不明CI、不把编译成功当成片。

备份精确payload及只读检查见`discuss/novel_rebuild_20261101/handoff_backup_allowlist.json`与`handoff_backup_preflight.md`。本次准备基于远端最新树，保留以上HANDOFF原字节，后续普通fast-forward更新必须用expected_sha防并发；本地落后18个提交与其他工作不被重置、变基或整体stage。本段只记录本地准备，不能当作已经提交或推送成功。


### 同次备份追加：仍有效的制作约束与renderer边界

- 用户“不在本机跑模型”的要求仍有效，包含tiny ASR，未被解除。不能因设备上能运行或体积小自行启动模型。
- 生图后来改走GPT；连续多帧、分层视差、快切、局部动效的路线仍有效，“不做单张图推拉”仍有效。字幕单行。
- 配音按整段自然表达，不逐句强拉统一语速、不强加固定停顿；最终实际音频决定时间线，文本秒数只是计划。
- 据另一Sol本次返回，新版`Renderer.swift`刚扩展并编译到`/tmp/yiwenbu-local-renderer-check`，纯数据检查与dry-run通过；生产测试因只有1张旧PNG而正确拒绝。以上不代表真实视觉、导出、混音或同步成功。仓库旧binary未更新，正式执行须从新版源码重编；代码不在此次文字payload。当前不得生成素材。
- 主代理已完成最新三件云端逐段回读：小说345、首集145、全季226个非空段分别相等；这仅验证云端文字同步，不是十视角通过。当前这版暂无十视角评分、无音画放行。高级模型08:20是历史页面重置计划，尚未复核恢复。


2026-11-02 08:42（Asia/Shanghai）｜第三轮Gemini 3.1 Pro四个独立新会话01—04已实际完整返回，每份三件各10维，原件/JSON/状态均保存；120个原始评分最低8，66项低于9.5，不能当完成300格或通过。94条引文逐字相符，12条只差空白/Markdown装饰，余14条未由该规范化解释（含拼接/改字/跨内容，须逐条核）；04声称complete=true但阅读字符数填8254/2223/5914，与18273/5114/16439不符，原值保留，既不能据此证明全读，也不擅称已证实漏读。01的独立同会话补充明确称五项9分没有具体不足、属常规保留，补充引文/元数据亦原样保存，没有改分。
四份reason普遍只有赞语，个别以排时表/规格当节奏表现；这不能形成可靠改稿意见。基于证据可靠性而非分数高低，暂缓05—10的同类批量请求，授权一个新Argon短文本诊断会话：仅完整首集、最多三处可定位问题、不打分、不代替终评，未传旧分或目标分。04后官方用量页显示当前14%、每周12%，下次重置13:20/11月6日11:20（未标时区），无额外付费。
新增/更新：review_round03/browser_raw、browser_responses、browser_statuses、browser_attempts、01补充及状态、provisional_diagnostics_01_04.json；gemini_ep01_diagnostic_argon_brief/submission（5788字符），13总控。原小说/首集/全季封版未变，尚无音画。下一步收独立Argon诊断，按实际问题改善正文/改编或修正评审取证方式，保留真实低分，不靠抬分和重抽好看的结果放行。


2026-11-02 09:11（Asia/Shanghai）｜Gemini Argon独立首集诊断给出联想连接、重复镜头及主角可见推理三项可讨论方向；原诊断“单身铁匠铺”“15秒旧画面复刻”并无来源，未采纳。Argon随后重写4/5/11/12场，再精修12场，纠正初稿对管先问红单、柳叶无动作跑到桌边、直接去沈家后屋等新问题；原件和失败/修订均保留。首集v5合成：5224字符/715发声汉字/29条对白与旁白；12场估算8/45/22/33/35/24/22/22/40/14/22/35秒=322秒。协调4项小校正：南坝回南边、复用“中的约2秒”非最后2秒、两场35秒为自然表演预留（非实读结果）；其他8场逐字未改。SHA256 4e687474dae80d06c7278e8bc5aff7d62cfa945e59fc3b6048dc3ec5c6371e2c。
独立Argon小说诊断仅提动作视角小修，但误记第八节；原稿实际七节，“见她转身”也不必然全知心理，不当硬伤。只采它随后给出的一个old/new句首：“许绾往门边走去。温素琴猛地伸手按住门板，急促地喘息道：”，供述原样保留。小说v4为18270字符/15387汉字，SHA c36052bb04f4f1c2b5e14676aaa392064bb7b3ee665e2d05ff1ed4ffb2a5fb49。全季v4以16项可回放协调对齐首集，第二集至附表逐字未改；16593字符，六集共1902秒仅文字估算，SHA 6a3538b1a2931285431addcd8adaa45b79ca0371d628577b657a0faf702bb42f。
云16/18新增当前页签，旧版本与旧制作准备保留并标历史：小说344、首集151、全季227个非空段落完整读回相符。小说：https://docs.google.com/document/d/1nApEHgezhPfpC9CDAy6DiPWUE61qy6C_g0kyvzxgJxM/edit?tab=t.xwyilndp1h16 ；首集：https://docs.google.com/document/d/1nu552mG0HWaH00-zmQr9oXVN6J4ydGvMeprpszUVEAM/edit?tab=t.2odmjcfsl6wp ；全季：https://docs.google.com/document/d/1nu552mG0HWaH00-zmQr9oXVN6J4ydGvMeprpszUVEAM/edit?tab=t.eyuulp1pt0m0 。
review_round04冻结父hash ef1e3adc2597999fe25906d2a70c32cee895d0efc44dc08af33859c847cfe91f。沿用十视角十维量尺，改为每视角每作品各新独立会话，先证据/具体判断后分数，不给旧分或目标，原R03四份低分全留。离线单篇生成器原先只取01—07，已修为manifest全部10位；生成30份单篇提示及submission，7个现有合成校验通过只是工具验证。首集01在新Argon会话https://gemini.google.com/app/ef7af32044bbe82a实际返回10项，10条维度引文逐字相符，最低8.5、8项<9.5；开头元数据仅Markdown差异，未成片限制是范围声明，原始评分未改。此刻其余29件已授权继续但尚未完成，不得标通过。
修改/新增：novel_complete_v4及manifest、episode01_candidate_v5及协调记录、season_outline_candidate_v4及16项patch/manifest、Gemini诊断/修稿brief、web原件/status、review_round04全部冻结源/输入/首件实际raw与status、review_tools/piecewise_review.py与既有测试/README、云16/18及13总控。当前Gemini用量页显示无法读取，4 Argon可选，按既有订阅继续且不购买/升级；当前百分比未知。下一步收齐29个独立单篇评审，核依据与实际问题再改；待逐格门槛满足才直接免费制片。尚无新音画、无本机模型、无新增费用或公开发布。


### 2026-11-02｜第一集实际粗剪 v2 已导出并云盘交付，尚未最终验收

本次主代理转达用户已授权零新增费用完成首集并音画云盘交付；该授权不等于公开发布。此前“尚无媒体/不得渲染”等历史段落只反映当时状态。现用已获准AI图片、AI配音与系统程序音效实际完成粗剪，未安装或运行本地模型；原始图片/音频与v1保留。男声为Result-24，第六场旁白为独立盲听文字一致的Result-26，旧Result-19和失败候选25未用于v2。声线听感仍待人耳。

- 实际文件：`work/ep01_assembly_20261102_v2/三点零九分_第一集_粗剪v2.mp4`；239.88秒，720×1280/25fps，78,589,593字节（74.95MiB），小于云盘连接器100MiB限制。
- 主代理已上传并核对元数据的云盘粗剪链接：https://drive.google.com/file/d/1wSjkOM5ddQhUHaNpEF-ngaQGBMqxe84q/view 。此处云盘核对由主代理执行，组装代理未自行声称复验云端视频解码。
- 可回溯文件同目录：`manifest.json`（最终实际清单）、`v2_changes.json`、`source_assets.json`（所有引用素材SHA256）、`subtitles_rough.srt`、`media_qc.json`、`Renderer.swift`（独立副本仅改2.4Mbps及最后0.8秒隐藏角标）、`render.log`、13张零时间容差导出检查帧。
- v2修正：第4场加入手部图、第5场换楼梯间双人图、第6场补母亲餐桌近景；旧留言新增“三号柜”及“十二月九日，城南水闸捞出”底部字幕，新增2.4秒；集尾203.56–229.56秒为女主脸/听筒紧裁，不提前露母亲、抵门掌或门影，警告源区间229.54秒结束后229.56敲门/切门影、230.36后才出母女抵门。239.08–239.88秒纯黑无角标。第6场新旁白字幕匹配新文案。
- 实测结构QC：5997视频帧和全部音轨完整解码至末尾、无无效时戳/倒退；唯一黑帧候选239.08–239.88秒正是有意片尾；PCM无非有限值和数字削波候选，峰值-0.221dBFS、全片RMS-24.795dBFS。音轨末尾约236.272秒，尾部3.608秒无声。没有LUFS/true-peak测量。
- 抽帧实际观察：人物/线索字幕和AI粗剪角标可读，单行无显见截字，纯黑片尾已观察；低码率未见抽样画面出现明显破坏文字可读性的压缩，但不是全片画质验收。独立审阅也确认新增柜号/日期字幕及电话→抵门顺序改善。
- 仍有明确限制：簿页在画面中仍为空白，线索只以底部字幕带出，未实现红笔日期及1991年七行记录的道具跟踪文字；第5场周凤喊话配楼梯双人反应，周凤本人及大厅未拍出；全片以现有静帧剪接，非连续人物动作或口型动画，部分长停留仍存在；句内字幕多为按字数估计，单行和时间结构合规不证明发声同步；Result-26与6有独立模型主观音色跳变意见，未获用户听感验收；开场女声年龄/质感、原创无歌词哼唱、整体混音及目标平台控件安全区仍待完善。程序敲门/铃声等为合成候选，不是现场录音。

下一步：收独立v2集尾听审结果并做全片实际收听/字幕对齐，完善簿页跟踪文字、角色反应和连续动作，核对第六场声线、整体混音与平台安全区。不能将“实际导出+结构QC+云盘已上传”写成“最终成片/用户验收通过”。


### 2026-11-02｜最新用户反馈：声音AI味及尾部嘟声，暂停成品判断

用户亲耳反馈当前配音“好有AI味”，且试听导出的源音频尾部有嘟声。当前整套声音仅试制，v2/v3不得视作最终成品。PCM检测已在多源末尾约0.84秒起找到相同700Hz脉冲；v2保留了各源完整尾部，确实存在提示音入片风险。全部22对白插段及16个实际配音源的尾1秒成片位置见同目录voice_tail_exposure.json，已交audio_repair；已有少量TEST副本，仅实验，未改视频清单、未产v3。源文件与v1/v2均保留。

重要勘误：若干Gemini会话虽显示read_file完成与SUCCESS，却明确表示无法实际听到声学细节；其余声学报告存在冲突。因此历史通过此路径的自然度、音色连续、切字、逐字听写与精确字幕同步结论均降级为不可靠，不能作为验收。独立模型的少量文字抽检相符也不能证明实际音质和同步。结构QC仅证明可解码、时间戳与PCM数字范围，不能发现或豁免听感嘟声。

云端指定交接文档已使用读取版本号+requiredRevisionId保护，仅末尾追加详细v2技术交接、用户最新反馈与下一步，随后将完整新增段落读回比对并检查旧全文前缀保留；网址 https://docs.google.com/document/d/1S8MJ-5hafqAAKbRImdjcQP24ftSiGt0zRIcKkSP_jXA/edit 。视频链接 https://drive.google.com/file/d/1wSjkOM5ddQhUHaNpEF-ngaQGBMqxe84q/view 仅粗剪待修。下一步逐一检查尾提示音与尾字重叠，安全副本修尾或局部处理后实际人工试听；实质改善声线/表演回应用户AI味反馈，再考虑新版本、全片字幕对齐和混音。零新增费用，不公开发布，不覆盖原件。
 
### 2026-11-02｜新增16条程序合成音效；方舟体验内容用途限制已核实

新增 `output/ep01/sound_design/`：16条原创程序合成48kHz/16-bit/mono WAV（共186秒/17,856,704字节）、可复现程序、峰值/RMS及SHA256清单、七场动作锚点混音建议及Drive上传/元数据读回凭据。全部已上传指定私人文件夹11uMWY64q_tLolJ210NmLhfqnkW1D5fBR，读回MIME/大小/父目录相符；无checksum回传，未执行云端字节下载或听审。没有外部录音采样、未运行本机AI模型、未新增费用，未改分享权限。原foley及v2未更改。合成拟音仍为候选，柜擦/厨房/水声部分仅占位，不能称自然度、沉浸感或混音已验收。详见 `output/ep01/sound_design/SOUND_DESIGN_HANDOFF.md` 及 `SOUND_DESIGN_LINKS.md`。

关键授权核查：实际网页入口是火山方舟体验中心SeedAudio1.0。官方体验规则第10条及平台专用条款3.7.14明确体验内容仅限模型效果体验，不可商用，也不可给第三方/第三方平台传播分发使用。来源 https://docs.volcengine.com/docs/ark/volcengine-ark-experience-center-terms-and-disclaimer?lang=zh （2026-03-01生效）；https://console.volcengine.com/ark/region%3Acn-beijing/docs/volcengine-ark-platform-terms 。本次未消费体验额度生成音效。主代理确认v2含体验生成语音：该批语音及含它们的v2不得公开发布或用作商业成片，须先核清并替换；修尾与混音不改变使用限制。指定云盘仅用户私人交付，不变更分享权限、不扩大受众，也不代表素材权利问题已解决。套餐/API音频是另一服务路径，权益需独立核查，既不自动套同一限制，也不能推定有商用许可。

### 2026-11-02 20:00（Asia/Shanghai）｜Antigravity接手专注小说：完成资料通读、番茄最新规则核实与Gemini专项诊断

- 执行动作：全面接手AI创作项目，严格停止短视频、配音、图片等所有音画制作，本次只专注小说创作。已通读HANDOFF.md、discuss/下各版设定集（v1~v4）、正文（七条规矩及水落青泥v0~v4）、审稿与讨论记录。
- 实际验证：
  1. 真实核查番茄小说2026年10月最新规则：新人（Lv.0/Lv.1）长篇强制“完本签约模式”（15万或30万字起，整书一次审核，限申请3次）；若选择短故事赛道则要求5千-3万字全篇完结投稿，平台严打低质/机械AI水文。
  2. 实际调用Gemini完成三项拆解诊断：g64_story_diagnosis（两版旧稿痛点与好看原则）、g65_female_agency（女性角色主体性与开篇动作范例）、g66_novel_seeds_tradeoff（三大故事方向吸引力、风险与体量权衡）。
- 文件修改：discuss/novel_rebuild_20261101/下新增g64、g65、g66系列Prompt、原始输出及元数据文件；本HANDOFF.md追加本日志。因本机环境无GDRIVE凭据（在GitHub Secrets），本地更新未能直写线上Google Doc，特此说明。
- 下一步：向用户提交《接手诊断与方向汇报》，不直接盲写全书，与用户共同研讨确认故事核心、女性主角动机、体量与题材方案。

### 2026-11-02 20:05（Asia/Shanghai）｜用户拍板三十万字目标与云端执行诉求：完成长篇分卷架构与云端方案设计

- 执行动作：用户明确将小说目标锁定为【三十万字】（100-120章），并提出将小说生成任务放到云端执行。已完成：
  1. 调用Gemini完成g67专项分析：拆解三个方向在30万字大体量下的四卷宏观主线（单卷7-8万字）、地图延展逻辑、女主从第1章到第100章的成长张力及逻辑断裂风险。
  2. 澄清Google Drive操作机制：解释本地缺乏GDRIVE凭据的原因，并梳理插件直连 vs GitHub Actions云端直写的可行路径。
  3. 设计“GitHub Actions分卷阶梯生成+自动同步Google Drive”的云端工程化方案，避免单次盲写导致崩盘或AI味注水。
- 文件修改：discuss/novel_rebuild_20261101/下新增g67_300k_architecture系列文件；本HANDOFF.md追加本日志。
- 下一步：等待用户在三个30万字分卷方案中拍板选定核心题材，随后起草第一卷细纲及云端生成脚本。

### 2026-11-03 21:10（Asia/Shanghai）｜完成五十万字长篇提示词圣经并推送到云端写入Google Drive

- 执行动作：遵照用户要求，确立五十万字超长篇目标，从历史研究中筛选出最具爆火与高口碑潜力的题材《老井诡契：七条保命规矩》（规则怪谈/地底悬疑/九十年代硬核工业奇幻），编制完成超级完整提示词文档《discuss/SUPER_PROMPT_BIBLE_500K.md》，包含自主续写状态机、六分真四分假借火规则、女主核心动机与开门动作、五卷宏观分卷规划（180章/50万字）、AI味红线防范规范及第一章示范细纲。通过GitHub Actions工作流自动将Markdown文档同步写进用户指定Google Drive小说文件夹（1gnSv8eSD1HPJxncsUgVI40mGJ7e6g1qG）。
- 实际验证：本地文件 discuss/SUPER_PROMPT_BIBLE_500K.md 编译完备，publish.txt 挂载云端写入任务，触发 GitHub Actions `docs_to_drive.yml` 自动生成 Google Doc 链接供用户直接提供给 Gemini Web 端联动。
- 文件修改：discuss/SUPER_PROMPT_BIBLE_500K.md，discuss/publish.txt，HANDOFF.md。
- 下一步：将Google Doc直达链接及Gemini Web端一键启动咒语交付用户，支持用户在云端由Gemini直接调取该文档自主生成高质量小说。
