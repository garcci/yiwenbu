# 第一集 Ubuntu / GitHub Actions 草稿合成

这是独立于 macOS Swift 的 FFmpeg 合成入口，不生成图片或配音，不运行本地模型，也不调用付费生成 API。画面由用户在 ChatGPT 网页自行生成、下载后放入云盘；ChatGPT 订阅不代表可免费使用 OpenAI API。脚本只消费明确列出的既有图片与当前获准用于草稿的音频。

**当前交付状态：基础合成已有主代理核实的GitHub合成素材烟测成功记录（见文末）；本机未安装FFmpeg/Pillow，本次新增story_overlays仅做代码与离线规范自测，尚无其实际编码、中文排版、完整解码或云盘往返成功的证明。没有因本次修改触发workflow。** `work/ep01_assembly_20261102_v2/manifest.json` 只用于检查历史字段结构，不是获用户接受的成片、配音或默认生产输入。旧 `approvedForProduction` 字段不能替代本次授权。

## 输入包

上传一个 JSON 文件至 Google Drive，文件内容为下述结构。`manifest` 沿用 Swift 清单的字段，`assets` 将清单里每个原逻辑路径映射至本次明确输入的云盘文件。原路径只作键，绝不回退读取 `/Users/...` 或 `/tmp/...`。云盘文件 ID 与哈希需用用户明确选定的素材实际值替换；不要提交凭据。

```json
{
  "manifest": {
    "duration": 2, "width": 720, "height": 1280, "fps": 25,
    "fontSize": 29, "safeInset": 54, "captionBottom": 256,
    "badge": "原创虚构｜AI画面·AI配音｜草稿待审",
    "scenes": [{"start": 0, "end": 2, "frames": [
      {"image": "shot-a.png", "start": 0, "end": 1},
      {"image": "shot-b.png", "start": 1, "end": 2}
    ]}],
    "captions": [{"text": "测试字幕", "start": 0.2, "end": 1.8}],
    "audio": [{"file": "paragraph.wav", "offset": 0.1, "sourceStart": 0, "duration": 1.7, "volume": 1}]
  },
  "assets": {
    "shot-a.png": {"path": "assets/shot-a.png", "drive_file_id": "REPLACE_WITH_FILE_ID", "sha256": "REPLACE_WITH_64_LOWERCASE_HEX"},
    "shot-b.png": {"path": "assets/shot-b.png", "drive_file_id": "REPLACE_WITH_FILE_ID", "sha256": "REPLACE_WITH_64_LOWERCASE_HEX"},
    "paragraph.wav": {"path": "assets/paragraph.wav", "drive_file_id": "REPLACE_WITH_FILE_ID", "sha256": "REPLACE_WITH_64_LOWERCASE_HEX", "authorized_for_this_draft": true}
  }
}
```

音轨 `authorized_for_this_draft:true` 必须由本次真实授权支持，仅表示允许用于此草稿，不能表示听感获接受。禁止用历史 v2 的批准字段机械填充。代码在下载/读文件前拦截 `Result-10.wav`、`Result-4.wav` 和以“未命名”开头的文件名；不能检测改名的参考人声，调用者不得借改名绕过授权。输入包最大 5MB，每素材最大 512MB，强制 SHA256，拒绝绝对输出映射路径、越界路径及重复/保留路径。不接受任意下载 URL，不解压压缩包；本地映射路径的文件或目录含符号链接时，在读取文件和哈希前拒绝。

支持：连续静态镜头硬切；每场 `frames` 的时间相对场景起点；单幅 `image`；一个全画布静态 `layers` 图层，可用归一化 `crop` 和 `opacity`；裁切后的完整图片精确缩放至图层矩形，`frames/image` 保持居中填满裁切。源 PNG 透明度与图层 opacity 相乘后先叠加到黑底，再转为 yuv420p。历史 v2 的 11 个场景可解析为 29 镜头，但不因此获得重渲染授权。拒绝多层、运动、灯光和淡化等尚未实现特性，不会静默丢掉它们。只有静态画面，不等于连续动作。

音频使用 `sourceStart/duration` 原速截取明确片段，`offset` 指定落点；不使用 `atempo` 或逐句自动加停顿，不生成或自动对齐配音。字幕单行、无 ASS 控制字符、时间不重叠，以同一 Noto CJK 字体测宽，超宽直接失败；`WrapStyle:2` 禁止自动折行。字幕位置保留底部至少 18%，AI 标注必须存在。实际平台遮挡与排版仍需审看。

## 在 GitHub 操作

新增 workflow 支持 `workflow_dispatch`；仅向指定项目分支推送 `video/ci_render/ci_smoke_trigger.txt` 时，还会自动执行一次合成素材烟测，不读取或上传真实素材。选择“第一集 FFmpeg 草稿合成与结构检查”手动运行时，可将云盘输入包 ID 留空，只执行两秒色块、正弦音和中文测试字幕烟测。另包含不同纵横比的合成透明 PNG，编码后抽样像素核验图层完整缩放、背景 cover、透明区黑底及半透明度。该测试不使用第一集真实媒体。

运行前须核实当前账户的 Actions 分钟、产物存储和云盘空间均不会新增费用，才勾选 `zero_cost_confirmed`；默认不运行。此开关只是人工确认，**不是额度查询或费用自动保证**。GitHub 的实际额度/计费取决于账户与仓库设置。本次扩展没有重新查询账单，也没有启动新的云端运行；既有运行和本次新增能力的状态须分别核对。

有真实输入时填写输入包的云盘文件 ID。下载使用仓库已有的 OAuth 凭据环境变量 `GDRIVE_CLIENT_ID`、`GDRIVE_CLIENT_SECRET`、`GDRIVE_REFRESH_TOKEN`；回传还需 `GDRIVE_FOLDER_ID`。仅配置 Secrets，不把凭据放进输入包、命令行或日志。现有凭据必须具有读取指定素材权限；只读令牌不能用于回传。

`upload_to_drive` 默认关闭，明确勾选才写入已配置云盘的 `ci-drafts/run-运行ID-尝试次数/`，不创建公开共享或发布到视频平台。复用根目录 `gdrive.py` 的 OAuth/上传逻辑，并避免其重试函数输出包含上传 URL 的异常。既有文件夹权限决定谁能看到草稿，脚本不改变权限。`keep_github_artifact` 默认关闭，明确选择才将结果在 GitHub 保留一天；仓库可见性及 Actions 权限决定受众。两个保存选项均关闭时，只完成临时合成与检查，文件保留在临时 runner，生命周期由 GitHub 管理；脚本不显式删除。

## 本地/已准备目录运行

需要 Ubuntu FFmpeg（含 libx264、AAC、libass）、Pillow、中文字体。Drive 往返另需 requests。可在获准的 Ubuntu 环境使用系统包 `ffmpeg fonts-noto-cjk python3-pil python3-requests`。macOS 可指定实际 CJK 字体文件，但这里没有验证其编码行为。

```sh
python3 -m unittest discover -s video/ci_render -v
python3 video/ci_render/smoke.py
python3 video/ci_render/render.py --manifest /prepared/manifest.json \
  --asset-map /prepared/asset-map.json --asset-root /prepared \
  --output-dir /prepared/new-draft --validate-only
python3 video/ci_render/render.py --manifest /prepared/manifest.json \
  --asset-map /prepared/asset-map.json --asset-root /prepared \
  --output-dir /prepared/new-draft
```

本地 `asset-map.json` 与 `assets` 字典相同，只需 `path/sha256` 和本次音频授权字段，不需要 `drive_file_id`。输出目录必须不存在，拒绝覆盖。`--validate-only` 读指定资产及哈希但不解码/测字宽；规范通过不能说成成片成功。仅 `smoke.py` 会生成无人物的合成测试媒体并保留测试文件，路径会在测试开始时输出。

## 结果与局限

成功输出 `draft.mp4`、`captions.ass`、`qc.json`。后者记录每音轨原素材哈希、真实时长、截取时间、落点、速度固定为 1；镜头和字幕时轴；视频/音频实际时长；帧数；H.264/AAC；完整解码结果。先经 ffprobe 检查，再 FFmpeg 从头完整解码，二者通过才移动成片并允许回传。每条音频超过源长度时失败，不静默截断或变速。容器与轨道时长误差阈值 0.1 秒。

结构检查不能证明字幕语义对齐、口型同步、音色/情绪好听、混音未削波、角色一致性或剧情可接受；尚无响度/黑帧/静音自动诊断。报告明确保留人工画面与听感审查、配音接受状态“未评估”。原素材不修改。合成中间文件、测试文件和输入保留在本次运行目录，不自动删除；GitHub 临时 runner 由平台管理，本机若需删除须先取得用户同意；失败日志刻意不打印命令/服务响应，诊断信息有限。编码速度与长片资源占用尚未实测。

命令语法参考：[FFmpeg 官方滤镜说明](https://ffmpeg.org/ffmpeg-filters.html)、[ffprobe 官方说明](https://ffmpeg.org/ffprobe.html)。

## 静音叙事的独立视觉信息层（本次新增，尚未云端实测）

底部单行对白字幕不能代替屏幕、红簿和提示信息。新增可选的顶层 `story_overlays`，用于显著的屏幕信息或道具卡：文字先用当前中文字体确定性绘制为透明背景PNG卡片，再按明确时间与位置叠加，之后再绘对白字幕和AI标注。不调用生成模型，不读或修改音轨，不将道具内容冒充人物对白。没有该字段的既有清单沿用原来的最终ASS编码入口。

```json
{
  "story_overlays": [
    {
      "id": "screen_unknown_number",
      "start": 8.0, "end": 11.0,
      "x": 64, "y": 180, "width": 592, "height": 160,
      "fontSize": 28,
      "lines": ["设备屏幕｜空号", "03:09　留言接入"]
    },
    {
      "id": "ledger_old_message",
      "start": 39.0, "end": 44.0,
      "x": 64, "y": 600, "width": 592, "height": 180,
      "fontSize": 28,
      "lines": ["红簿｜旧留言", "十二月九日　城南水闸捞出", "苏建国"]
    }
  ]
}
```

以上只是720×1280画布的接口示例，不是已采用的剧情信息或对齐结果；须依据最终台本与画面填写。“声音变了”等提示也应在真实剧情揭示时刻出现，不能用提前解释破坏悬念。关键日期、旧留言原句、人物归属须与文字来源逐字核对，渲染器不会自行推断、补写或验证剧情。

接口与限制：

- `start/end` 为整片秒数，必须精确对齐视频帧，采用 `[start,end)`；QC同时列出 `start_frame/end_frame_exclusive`，均从0计数。起始帧显示，结束帧不显示。不是逐句强制停顿，音速仍为1。
- `x/y/width/height` 为整数像素，原点是画布左上角。与历史Swift图层左下坐标不同。每卡最大面积为全画幅35%，最多32卡；同一时段的卡片矩形不能互相覆盖。
- 安全范围为：左右不得进入 `safeInset`；顶部不得进入 `max(80,40+2×AI字号)`；下边界不得超过 `height-captionBottom-3×对白字号`。整个底部对白/平台区域始终保留，即使当时没有对白。越界、侵入保留区立即失败。这是几何约束，不能保证各平台按钮位置、人物面部或画面关键道具不被遮挡，最终需实际审看并调整位置。
- `lines` 为1—4条明确短文字，每条最多60字符。允许卡片多行，但底部对白仍严格单行。拒绝换行字符、反向/隐形控制字符、ASS/滤镜控制符及未知字段；用户文字只绘入PNG，不进入ASS或滤镜表达式。`id` 只允许1—40个英文字母、数字、下划线或连字符，且全片唯一。
- `fontSize` 为12—100整数像素，默认取对白字号且至少16。以实际指定字体测宽/测高，超出卡片即停止，不自动折行、删字、缩字或缩短显示时长。阅读速度与停留时长是否充分仍需人工判断。
- 当前只支持固定样式的文字道具卡：暗底、白字、细暖色边框；不支持透视贴合设备屏幕、自动跟踪、外部预制道具图、多层任意贴图、富文本、外部字体URL或模型生成。不能据“存在卡片”就声称静音观众已理解剧情。

结果新增 `story-cards/story-N.png` 供审阅，QC的 `story_overlay_timeline` 记录每卡文字、矩形、起止秒、起止帧与PNG SHA256；`silent_story_comprehension` 始终写 `not_assessed`。静音验收应另外逐镜核对：观众是否实际看清来电空号、红簿旧留言及死亡日期、哪句话改变、各信息出现先后与人物反应之间的因果。当前代码只提供展示与核查能力，不自动判定这些已成立。

新增合成烟测保留原有PNG alpha、纵横比、中文ASS、音轨和完整解码检查，另外生成两张中文道具卡，核对第9/10/19/20/24/25/34/35帧的入场、出场边界、卡片边框和白色字形像素，并核对QC帧区间；这些合成短卡用于检查时序，不是供实际观众阅读的时长标准。本机缺FFmpeg/ffprobe，**本次新增的卡片编码/像素/时序烟测未执行**，需后续获准GitHub运行。既有合成烟测曾由主代理核实在[运行41397239189](https://github.com/garcci/yiwenbu/actions/runs/41397239189)成功，不能将它当成本次新增卡片功能通过的证据。
