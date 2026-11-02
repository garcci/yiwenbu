# Agent Plan ASR r06时间校准：只准备S1_01单次云端验证

默认runner.py与plan_asr_align_once.yml仍严格限定S1_01。主代理已推送并实际运行pilot，run 41404174217 completed/success；本代理随后只读核对远端及下载实际artifact，未重试。真实返回了4个词的毫秒时间戳，规范化正文一致，human_checked=false；详见pilot_verified_41404174217.json。没有本机模型。

后续余26段另准备在remaining26/与独立workflow中，固定排除S1_01、最多26连接，当前未触发、未提交推送。默认pilot入口不会自动扩成27段。冻结27条原音的Drive元数据与receipt仍是唯一允许来源；两段真实运行需分别复核当次额度，不能复用旧运行资格。

## 已有官方可行性依据

- [Agent Plan语音模型官方页](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)明确列出专用`wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream`，ASR2资源`volc.seedasr.sauc.duration`，专属API Key的X-Api-Key鉴权，并有带序号gzip二进制示例。官方说明此单流方式在完整发送或超过15秒后返回高精度结果。
- 套餐页引用的[官方单流ASR文档](https://docs.volcengine.com/docs/doubao-voice/unidirectional-streaming-automatic-speech-recognition-websocket?lang=en)说明`show_utterances=true`返回分句、分词；utterances及words中的start_time/end_time单位为毫秒，definite=true表示分句确定。示例有字/词粒度时间信息。
- [官方二进制协议资料](https://docs.volcengine.com/docs/doubao-voice/large-model-streaming-automatic-speech-recognition-api-1?lang=en)及套餐示例给出v1头、gzip、序号、长度、最终包标记及服务错误帧。本模块按该协议独立实现，不复制示例中会打印响应和异常、把key放命令行的做法。

这些是文档支持，不是当前账号握手/词时间戳实际成功证明。官方页面直接抓取曾超时，搜索服务返回的官方页面正文和样例可读；没有依赖社区代理或第三方接口推断套餐支持。

## 音频范围冻结

仅允许主代理指定的两批目录：

- 第一批`1izOd2bZjaCTlCq_NS0IVvBsHLZKCHHmQ`。
- 第二批`1XBq5kFbvg4bKcDJi1v61VobkaGb5Ap2a`。

`inputs.frozen.json`冻结具体S1_01至S7_27的文件ID、文件名、MP3 SHA256/字节、receipt文件ID及原字节SHA、对应TTS输入摘要、TTS运行ID。27份receipt原字节位于`receipts.frozen/`，与r06角色清单输入逐条匹配；资源seed-tts-2.0、状态completed且request_count=1。冻结输入SHA256为`f997b17d44424d7bfaa642b0b17c36868044fc3944f46b432b77a0b68b5a01c9`。

运行时只取S1_01的指定receipt与MP3，重新核对文件名、直接父目录、字节数及SHA；权限需为明确user/group私人范围，anyone/domain/未知权限即停止。程序不能列任意Drive目录或选择任意音频ID，不能读取体验中心、Result-10、Result-4、未命名或其他文件。元数据准备文件含这两个目录的文件清单；运行器不使用清单扩展白名单。

## 一次性云端启动方式

独立工作流`.github/workflows/plan_asr_align_once.yml`只匹配工作分支下`video/plan_asr_align/execute_once.json`，该文件当前不存在。`trigger.example.json`不是开关，推送代码/示例不会发请求。

1. 主代理复核当次Actions compute使用/包含金额（剩余至少$0.50）、存储在免费内、0元预算阻断，及ASR列于Agent Plan、ASR超额后付费关闭、套餐余量覆盖本次最多1连接/60秒。14:47:55已转达ASR包含及超额off，仅记录为历史观察，不能替代实际启动时的全套费用证据。
2. 填写`quota_evidence.pending.json`，移除draft_only，使用最早独立核查时间的一小时TTL；绑定固定授权ID`ep01-plan-asr-r06-pilot-20261102-01`及冻结输入摘要。当前证据是明确拒绝执行的草案。测试不读取生产证据来断言其无效。
3. 从trigger.example.json创建真实execute_once.json，再由主代理集中普通推送。runner要求GitHub环境、工作分支push、run_attempt=1，远端专用workflow完整可见历史恰好只有当前run。任何已有其他run、历史缺失/身份不明都拒绝，失败不自动重试。此为保守一次性push退路，不是持久原子消费服务；不能删除/改写历史或改ID绕过它。

工作流限5分钟，云端安装ffmpeg与websocket-client传输库，不安装模型。仅进程环境取得ARK_API_KEY、三项既有Drive secrets及Actions只读token；无命令行密钥、无外部签名URL、无响应/异常原文日志。Drive只读，不创建文件夹、不上传、不改权限。

依赖已更正为PyPI确实发布的websocket-client 1.9.2，使用requirements.txt及公开wheel SHA256的--require-hashes安装。官方PyPI元数据记载该版2026-08-31发布，Python要求>=3.10；本次只在内存读取wheel并检查源码/AST，确认create_connection、send_binary、status属性、redirect_limit和enable_multithread选项存在，没有安装或执行该包。验证记录见dependency_evidence.json。先前错误地将latest文档显示的1.10.0当成已发布版本，已撤下；今后不能用文档版本代替发行证明。离线测试约束工作流必须使用当前已核验版本及hash，这仍不等于真实云端安装或ASR握手已成功。

## 音频与协议行为

GitHub上先以ffmpeg将已核对原MP3解码/重采样为16kHz、16bit、单声道PCM；保留原MP3及receipt，不剪头尾、不降噪、不拉速。单段/本pilot总量均封顶60秒，超限不连接ASR。

每次只建立一个固定套餐WebSocket连接，拒绝跳转，按200ms发带序号gzip音频包，最后一包负序号及最终标记，接收线程保存最终结果。网络/协议/服务错误或缺完成标记即停，不重连、不换接口、不切普通按量API。request开启show_utterances及full结果，关闭ITN和语义顺滑；不提供原台词、热词、纠错表或上下文提示，避免将标准答案灌成识别结果。

## 给r06_timeline的输出

artifact `plan-asr-r06-S1_01-pilot`保留1天：原MP3/receipt、成功ASR二进制帧、解析后的全部事件、状态、费用证据和`alignment.json`。失败/成功均尝试保留artifact；平台硬终止时不保证artifact成功，不能据配置宣称结果已取回。

alignment形状兼容：顶层segments，条目含voice_id、原MP3 audio_sha256、words中的text/start/end（秒）、human_checked=false。另附实际ASR全文、冻结原文、原始毫秒转换出的分句、差异、flags、auto_match；顶层明确scope=pilot_S1_01_only、source_total_segments=27、complete_for_episode=false。

只有正文去标点/空白后逐字一致、词文本覆盖实际转录、确定分句及所有词时间有效且在音频/分句内、不重叠时auto_match=true。数字形式不自动互换，人名错字不静默修正。缺时间戳则words留空或只保留实际有效项并标失败，不按字数插值、不造时序。builder只能自动采用auto_match=true的条目，不能把flags不为空的词表当校准完成；human_checked始终false，ASR不能证明音色、表演、AI味或用户听审通过。

离线检查：`python3 -m unittest discover -s video/plan_asr_align/tests -v`与`python3 video/plan_asr_align/runner.py`。默认仅校验冻结receipt和元数据，不读真实音频、不请求Drive或ASR。
