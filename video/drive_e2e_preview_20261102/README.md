# 8秒云盘到云盘技术预览：准备完成，尚未运行

范围只有“读取两个既有授权文件 → GitHub FFmpeg合成与完整解码 → 回传原私有项目目录”。不是正式第一集，不生成新音画、不使用网页体验音频，不调用任何生成API，不改分享，不删除文件，也不上传GitHub Artifact。既有无真实素材CI合成烟测成功不代表这条真实素材链已通过。

`input-bundle.json` 是供云盘输入的原字节JSON，符合 `video/ci_render/drive_io.py` 的 manifest/assets 规范。冻结 SHA256：

```
7edf0a8a9729a31ee466a23829bfe26db829fadfd96ea2b762c7f4adb743a96b
```

只使用：

- GPT人物图片：[第一集第一场镜头2](https://drive.google.com/file/d/1hRtm5SVRagq3EVPA_8pwtngiFfjGeKDo/view)。本机明确源文件“深夜电讯室的专注值班员.png”实算1939030字节、941×1672、SHA256 `3fad4582e2afe0de9cb5bdc7bef638372e79a5c83cb4b62fc84190235a5415dc`。云盘元数据名称、字节数、父目录已读取；本轮未在本机下载并重新计算云盘图片SHA，CI必须下载后强校验，不匹配即停止。
- 新套餐API原音：[单自然段MP3](https://drive.google.com/file/d/1g6an4mkAYoft_PVoaT42OqMdaDRDSxtX/view)。本机实算63021字节、SHA256 `d6687916aed6bd292f33306e110bef687fbe78c60b964fa70936fe912beed447`。当前系统afinfo估计7.872秒；本任务读取既有完整解码PCM，为188928帧/24000Hz/单声道=7.872秒，没有重新运行模型或生成音频。音轨不变速，从0起使用7.872秒，视频落点0.08秒，总片长8秒，不截尾。

只保留一个图片源；第0—4秒显示全图，第4—8秒切到同图明确裁切，测试图像处理和切换，不冒称两张独立新图、连续动作或正式镜头设计。字幕仅为“云盘端到端测试｜非正式成片”，不是伪造逐字对齐；全片保留AI画面/AI配音标注。原图与声音的创作/听感接受状态仍待审。

## 集成者下一步

1. 将 `input-bundle.json` 原字节上传至已授权的项目云盘目录，取得云盘文件ID。主代理已按原字节上传并核对元数据，当前输入包ID为 `1kvWhg162PMKu0fN4CtfGJeAbc5GBtLDl`；本代理没有自行上传或伪造ID。
2. 本代理已据主代理提供的真实ID创建 `execute-once.json` 并离线校验；hash保持上面原值。再次确认本次免费分钟/云盘空间和零美元预算阻断仍适用，才保留 `zero_added_cost_confirmed:true`。开关不是费用查询或自动费用保证。
3. 审阅后由主代理普通推送工作分支 `claude/project-thread-l4wz3r`。新增workflow只匹配此分支、精确路径 `video/drive_e2e_preview_20261102/execute-once.json`；准备目录、说明书或workflow本身的变动不会触发。不要触及旧TTS/批量生成触发路径。
4. 工作流第一次运行会先无Drive凭据检查范围、冻结包、运行次数以及本workflow历史。仅允许第一次push运行；任何前次运行（即使失败）都会消耗本次一次性资格，禁止GitHub rerun。需要重试时由用户/主代理重新明确本次范围后另建独立workflow，不能自行绕过。

下载只使用现有 `GDRIVE_CLIENT_ID`、`GDRIVE_CLIENT_SECRET`、`GDRIVE_REFRESH_TOKEN` 三项Secrets。输出目录固定为已有私有短视频项目目录 `11uMWY64q_tLolJ210NmLhfqnkW1D5fBR`，环境变量使用该明文目录ID，**不修改全局Secret的目的目录**。输出前验证该目录已存在且权限列表中没有anyone/domain；权限无法读取或目录不符会停止，不新建目录、不改权限。

输出以运行ID加“99-云盘端到端8秒技术预览-非正式成片”命名，先查同名并拒绝已有文件；实际上传只用POST files.create发起新建，再向该新建会话PUT字节，绝不调用可PATCH的上传函数。即使预查后另有人创建同名文件，也只可能新增一个同名文件，不覆盖竞态文件；后续只核对本次创建响应返回的ID。仅上传MP4、QC和字幕，读回父目录/字节数/MD5后输出三个云盘原件链接。不存在公开分享动作。`contents:read/actions:read` 用于代码与一次性运行历史读取，不申请仓库写权限。后续CI应核对真实结果与云盘回传，不能只据这里的准备状态报成功。

## 本次离线验证

```sh
python3 video/drive_e2e_preview_20261102/prepare_bundle.py
python3 -m unittest discover -s video/drive_e2e_preview_20261102 -v
```

已执行：源文件哈希/图片头/既有解码PCM时长核对；冻结包8秒、200帧、两资产时轴验证；7项离线测试；Python编译；YAML解析。未执行：真实素材编码、云端哈希比对、本代理直接进行的Drive输入包上传、CI触发、真实输出回传或完整人工收听。没有读取Result-10、Result-4、未命名或其他体验音频。

创建语义参考：[Google Drive官方上传说明](https://developers.google.com/workspace/drive/api/guides/manage-uploads)。新增竞态mock回归确认名称查询只发生一次、发起POST新建，且PATCH与旧_put_once均未被调用；这不是实际云端竞态实验。
