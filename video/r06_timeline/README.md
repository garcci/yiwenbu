# r06 measured-audio timeline builder

此目录只提供离线脚本，不联网、不触发CI、不运行模型、不修改原素材、不上传任何文件。最终生成的`bundle.json`与现有`video/ci_render/drive_io.py fetch --bundle-id …`兼容，可在本任务授权的私人Drive输入目录上传；上传与CI触发由协调者在本轮范围内另行执行。本目录没有提交或推送。

`build.py`读取冻结的28-beat方案和显式输入catalog，输出`manifest.json`、`asset-map.json`、`bundle.json`、`build-report.json`及`CREDITS.txt`。manifest已通过当前renderer.plan的结构检查，图片只作静帧硬切，禁止用推拉冒充动作。`render_ready=true`只表示结构可供渲染，声音、字卡排版、静音理解与人物动作仍未验收；在报告中明确标记。

## 输入步骤

1. 复制`inputs.template.json`到新的输入路径。为每个beat指定已确认图片key；在assets写明kind=image、confirmed=true、Drive ID、实际字节SHA256、相对path与provenance。同一图可供多个beat使用，不能把未经核对的名称候选当已确认图。另提供版权卡背景图。不要把含门影的静图提前当傍晚门闩图，也不要把机房照片当家中电话镜头。
2. 配音两批来源已锁定：batch01 folder=`1izOd2bZjaCTlCq_NS0IVvBsHLZKCHHmQ`，batch02 folder=`1XBq5kFbvg4bKcDJi1v61VobkaGb5Ap2a`。脚本不会访问云端；先将这两个指定文件夹下载到asset-root内部的batch01/batch02。每批需要manifest.frozen.json、state.json、MP3和文件名→云ID索引drive_upload.json。若云目录没有该索引，用已下载的Drive元数据列表制作结构`{"folder_id":"真实文件夹ID","files":[{"name":"S1_01.mp3","id":"真实DriveID"}]}`；不能按文件名猜ID。只接受指定文件夹，精确覆盖27条r06正文、completed状态、单次请求、任务授权与GitHub运行凭据、原始音频hash。`import_batches.py`实算本地字节hash并执行ffprobe，写入真实时长；不声称听感/逐字转写已核验。
3. 配音目录保持只读。运行命令示例（占位路径需替换）：

```sh
python3 video/r06_timeline/import_batches.py --inputs inputs.json --asset-root input-assets --batch01 input-assets/batch01 --batch02 input-assets/batch02 --output inputs.measured.json
```

4. 图片/配乐/音效已有可信SHA256时可用`probe_catalog.py --inputs … --asset-root … --output …`验证全部声明文件，所有非图片音轨均执行ffprobe。该脚本不替换预期hash，不会因失败回退或重新合成。每条音轨必须有actual ffprobe JSON和duration_seconds相符；本地素材通过不等于云端字节已验，CI下载仍会核hash。
5. 默认严格模式要求每句speech_start/speech_end和单行短语captions的相对起止，由人工标注或API时间戳经人工校对，method填human_marked或api_timestamp_human_checked。不能把按字数估时冒充这些方法。字幕每行<=20字，只接受显式时间，renderer还会按实际字体验证宽度。语音不变速，不裁原始尾部，不强制音频淡化。
6. 若本轮只做待听审预览，可显式加`--allow-unaligned-draft`：全文按语义标点分短页，再等分**页数**形成显示窗口；它们不是逐字/短语发声时间。报告明确UNALIGNED，所有语音的speech_end保守采用完整文件时长；尤其警告后敲门会等整份警告文件播完。此模式不能声称配音或字幕同步通过，预览后仍需真实人耳对齐。按页展示速度过快会拒绝构建，不强拉声音迁就文字。

```sh
python3 video/r06_timeline/build.py --inputs inputs.measured.json --output timeline-draft --allow-unaligned-draft
python3 video/ci_render/render.py --manifest timeline-draft/manifest.json --asset-map timeline-draft/asset-map.json --asset-root input-assets --validate-only
```

前者只检查结构、ID/hash格式、音轨probe记录，后者核实际文件hash；真正图文排版、解码与混音需后续渲染和人工验收。builder默认拒绝test_fixture，合成数据不能当生产测量。

## 声音事件与时间

`sound_events`为独立事件表，**不自动展开原28-beat里重复的拟音建议**。各事件需要唯一id、asset_id、anchor（beat_start/beat_end/speech_end + id）、非负delay、source_start、duration、volume。duration不得超过ffprobe来源。音效可叠加，不做隐式循环；背景只添加真实需要的几个事件。音乐kind=music，环境声role=ambience时添加fadeIn/fadeOut（默认0.5/0.7秒，最多半段长）；对白没有强制淡化或变速。动态duck、响度限制及主观混音均未执行，谨慎低位增益，CI渲染后必须听审。

F07严格要求一个事件，anchor=S7_26 speech_end、delay=0、source_start=0、duration至少4.4秒，并且已确认first_impact_seconds=0.40。门图从警告结束+0.40秒后的首个视频帧起出现；警告原音频继续完整播放，余下若有静音不会被剪短。敲门beat最少6秒，母亲台词后置，保持先警告后三敲。请保留模板6秒原音效，事件不得伪造冲击点。

视觉核心卡必须含03:09、03:15、五句留言、十二月九日/城南水闸捞出和妈别开门；卡不能机器自报“空号”，终端号码栏空白由画面/编辑卡建立。read_seconds仅为视觉阅读预留起点，不是声音同步或静音理解实测。模板短卡是编辑草案，所有动作仍为静态预演；build-report保留原beat缺镜头清单。

## 音乐版权与剩余风险

只给实际使用的music key生成尾部版权卡。每首需要license=CC BY 4.0、1—4行attribution_lines、完整attribution_text和credit_read_seconds。卡需包含曲名/作者/来源、许可链接/改动说明；完整原曲官网链接及全文署名放CREDITS.txt，以后经授权发布时还应放发布简介。没有用音乐则不会生成虚假音乐署名。人声与画面权利凭据仍由catalog提供，非本脚本判定。

现renderer只提供静帧硬切，无法实现真实挂听筒、护母、抵门、敲门振动或口型动画。故事卡避免整段台词堆满屏，最终实际字体布局还可能因20字中英文宽度而拒绝渲染。音轨可能包含提示音/错字，ffprobe和hash都不能识别；本目录没有收听或证明这些问题不存在。禁止所有网页体验音、全部Result系列、未命名文件和失败自动回退。脚本从不持有或输出凭据。

## 本地离线验证

```sh
cd video/r06_timeline
python3 -m unittest -v
```

测试只用合成duration/probe与虚构ID/hash，不下载或打开实际声音，验证27ID覆盖、实测字段冲突拒绝、体验/Result拒绝、先警告后敲门、来源切片界限、无重复音乐展开、显式版权、缺线索拒绝、生产入口拒绝合成测试。不能把测试通过当实际出片成功。

## 供已获准GitHub云环境使用的抓取入口（此轮未运行）

```sh
python3 video/r06_timeline/fetch_api_batches.py --fetch-known-batches --destination input-assets
```

该入口只列出两已知文件夹，以现有项目Drive OAuth helper注入令牌，不在参数/日志/输出保存令牌；无合成或上传请求。逐个核state、manifest、receipt和MP3原字节SHA256，再调用上面的import_batches测时长。目标目录必须不存在，失败不自动重试或回退。只下载本批manifest列明的音频，不扫描体验文件。

## ASR导入及失败策略

将云端ASR转成显式结构（时间单位秒，针对原MP3的相对时间）：

```json
{"segments":[{"voice_id":"S1_01","audio_sha256":"真实原mp3的64位hash","human_checked":false,"words":[{"text":"妈","start":0.1,"end":0.3}]}]}
```

示例不是有效完整转写。实际必须提供全部27条、完整words以及正确音频hash。适配器对NFKC/标点/空白之外的正文差异严格拒绝；时间缺失、倒退、重叠、超音频范围、单token过长也停止。不能把原文强塞给错转写再按比例造时间。

```sh
python3 video/r06_timeline/apply_asr.py --inputs inputs.measured.json --asr asr.words.json --output inputs.asr.json
python3 video/r06_timeline/build.py --inputs inputs.asr.json --output timeline-asr-preview --allow-unreviewed-asr
```

默认builder只接收human_marked或api_timestamp_human_checked；上述显式预览flag保留真实ASR边界但报告unreviewed_preview，未假称人耳验收。特别是未复核ASR的S7_26，敲门仍保守等完整音频文件结束，不拿可能偏早的ASR末字位置冒险。若ASR错字或缺时间，应停止待重识别/人工校正；只有明确选择--allow-unaligned-draft时才输出**不宣称同步**的页窗草稿，无自动降级。字幕页窗只服务粗预览，可读性与语音同步仍待人耳。

## 一次性私人云端workflow候选（尚未安装或触发）

`workflow.ep01_r06_private_preview_once.yml`仅为供独立复审的源文件，当前留在本目录。主代理若批准，应原字节安装为`.github/workflows/ep01_r06_private_preview_once.yml`；本子任务没有写`.github/workflows/`，没有创建真实`execute_once.json`、提交、推送或触发。推送代码/示例本身不匹配唯一触发路径。

约束：仅garcci/yiwenbu私有仓库、claude/project-thread-l4wz3r分支、push事件、run_attempt=1、唯一触发文件video/r06_timeline/execute_once.json。preflight要求专用workflow完整可见运行历史恰好仅当前run，另绑定当前head SHA。任何已有run或身份/历史不明停止，不删历史、不换ID重试。`execute_once.example.json`的zero_added_cost_confirmed=false，不能执行；主代理需要填写本次明确0新增费用与私人上传授权、当前至少60分钟免费Actions及300MiB私人Drive余量的证据，时间TTL一小时。脚本只校验传入证据是否完整新鲜，不自行声称已查到账单或额度。

`run_private_preview.py`流程：私人目标权限只读检查→固定两批API音频state/receipt/hash→35候选云端下载SHA强核→所有音轨ffprobe→27配音导入→有完整真实ASR则未复核ASR预览、无ASR则明确UNALIGNED→28-beat静帧渲染→全片解码QC→新建唯一私人run子目录create-only上传。35候选仍未确认，云端任何SHA不符立即停止，不能把大小相符或本地准备当云端配对完成。真实ASR必须完整27项且每项auto_match=true/flags为空；pilot、错字或缺时戳即停止，不能静默退级。未提供ASR时视频AI角标明确“字幕未对齐”，报告写明显示页窗非发声时序。

成片AI角标、片尾r06制作署名以及实际使用音乐的CC BY署名随输出保留。流水线只选择一个低位8秒M2母女场景钢琴候选，边缘淡化；不是已听审片段。其余两首音乐仅作候选，不自动铺满。分享权限只读，anyone/domain/未知均拒绝；新目录和文件依继承权限再次核验，不调用permissions写接口。上传只用POST新建/PUT新会话，绝不PATCH已有素材，同名不覆盖，不删除任何文件。上传后逐个读回MD5、大小、名称、父目录与私人权限。输出包括draft.mp4、qc.json、captions.ass、build-report.json、manifest.json、asset-map.json、bundle.json、CREDITS.txt。总上传封顶300MiB，超过或任何失败均停，不自动重试。

workflow不配置GitHub视频artifact留存、不调用任何生成或ASR服务，不读取ARK_API_KEY；只从环境取得已有Drive OAuth及GitHub只读token，参数/日志不携带凭据或云端响应。下载、测量、渲染和上传入口均未在本次执行，代码与离线测试通过不等于云端成功。
