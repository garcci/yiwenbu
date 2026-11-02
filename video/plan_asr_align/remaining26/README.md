# 排除已成功S1_01的余26段：准备完成，未触发

主代理要求先做一次套餐ASR验证。已只读核实pilot实际成功：远端HEAD d9c7d7e1b337002fd769f4bc48af7d5330e64808；[run 41404174217](https://github.com/garcci/yiwenbu/actions/runs/41404174217)为唯一一次、attempt=1、completed/success，2026-11-02 07:07:22Z结束。下载实际artifact读回，收到8帧及final=true，音频duration=1248ms，实际转录“妈，我没事”，原文仅多句号；规范化逐字一致。实际4个词：妈0.08–0.32、我0.48–0.72、没0.72–0.88、事0.88–1.08秒。原MP3为10029字节，SHA256 5a6a288e206745147ae723b4cfcbd9a92f342cf71bea0965f1bd8733a18d5939，与冻结一致。此为真实机器返回，不是听感、音色或用户验收。

核验摘要保存于../pilot_verified_41404174217.json，实际artifact下载副本在被忽略的../pilot_actual_41404174217/。没有重跑pilot、没有新ASR调用、没有推送。

本目录scope.frozen.json固定S1_02至S7_27，共26个ID，明确排除S1_01。范围摘要18aa896e00619034d730bf09bd6509c1c0144a8d9cbb46b3264fd5ee05ff8e1e；沿用27份已冻结原MP3/receipt白名单，不接受其他Drive路径或体验素材。每段最多60秒、全批最多600秒、最多26个连接，顺序识别，网络/协议/服务错误即停、不重试。先验证26份receipt/原音SHA与总时长，之后才开始连接ASR。

独立授权ID ep01-plan-asr-r06-remaining26-20261102-01、独立工作流.github/workflows/plan_asr_align_remaining26_once.yml。只由本目录execute_once.json的首次push触发；该文件尚不存在，trigger.example.json不是开关。远端专用workflow可见历史必须恰好只有本次push run；它是保守一次性历史门禁，不是永久原子防重放。禁止删除历史或复用失败批次授权。

quota_evidence.pending.json是明确拒绝执行的草案。主代理需在实际触发前记录最新Actions compute金额/存储/0元预算、ASR列于套餐且超额关闭、套餐覆盖26连接及实际总时长的事实，并绑定本输入摘要与范围摘要。不能把pilot启动前的金额或其成功运行当作本批最新额度证明。当前只准备，不触发、不推送。

输出仍是每段成功原始响应帧/解析事件、原MP3/receipt、状态、alignment.json；voice_id、原MP3 audio_sha256、words秒级时间兼容r06_timeline。human_checked始终false。实际转录保留，错字/缺字/数字格式不一致不默改；缺词时间、非确定分句、越界/重叠均auto_match=false，原始有效时间可留待核对，不按字数补点。

先前pilot数据不重新识别。余26段返回后，使用../merge_results.py在离线状态合并真实pilot alignment.json与余26段alignment.json；拒绝重复S1_01、缺段、音频摘要不一致和错误时间单位。完整合并同时输出complete_for_episode=true和coverage_complete_for_episode=true，二者仅表示27段覆盖；它们与auto_match_all独立，不代表每段匹配通过。错字或缺词时间仍保留原flags、auto_match_all=false及review_required_ids，粗剪runner的逐段auto_match/flags检查会拒绝这些段落。测试冻结当前粗剪的真实两条门槛表达式，若本地存在消费者源码还会核对AST一致，不让云端测试依赖其他代理尚未提交的目录。builder不得自动采用auto_match=false的段落，不把机器匹配当用户实际听审。

本批工作流保留artifact一天；硬终止不保证上传成功。后续原件取回/云盘交付由主代理统筹，当前不新增任何分享或发布步骤。本机只做准备与mock，不运行ASR模型。
