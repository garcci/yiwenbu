# 新冻结候选：已有素材接入，2026-11-02

实际完成：对16张GPT图、16条程序合成音效、3首已许可音乐共35项，重新只读本机字节计算SHA256和MD5，并逐项读取已知Drive ID的文件名、大小、MIME、父目录，显式请求md5Checksum及sha256Checksum。35次连接器响应均没有返回checksum字段，因此**云端MD5核验通过0项，35项均未验证**，全部confirmed=false。本次没有下载云端媒体、没有读取任何配音文件、没有运行ffprobe或模型，没有新增费用或上传动作。媒体时长保持null，不把历史时长或文件名秒数当本次测量。

候选配置：`inputs.assets-candidate.json`，共62项（35项非配音素材+27项待实测API配音槽位）；完整记录ID、相对路径、当前本机SHA256、本机MD5、Drive ID、原云盘文件名、字节数和未验证状态。`asset_pairing_audit.json`记录旧本机候选与本次重定位。`freeze.json`记录配置与审计SHA256、旧source assets源hash。原r06_edit_plan/assets.json和旧plan均未覆盖。

重要发现：旧候选I01/I02/I03/I07/I13本机字节数与已知云端文件不符，旧SHA不能照用。本次在已知PNG池按云端唯一大小和文件名重新定位候选：

- I01：深夜值班的电话调度员.png，1,977,331字节。
- I02：深夜电讯室的专注值班员.png，1,939,030字节。
- I03：深夜复古电脑工作台.png，1,827,074字节。
- I07：昏灯下的温柔对话.png，1,926,699字节。
- I13：门边的深夜家常……png，1,970,213字节。

这五个是**新的配对候选**，没有因为大小相符就确认云端字节一致。其余11图+19音频原候选大小相符，同样没有hash通过。新候选35项大小均与Drive元数据相符，仍必须云端下载强核SHA256。音色、拟音自然度、音乐听感及图的连续动作没有复核。

只在未来已授权GitHub运行时使用显式入口：

```sh
python3 video/r06_timeline/fetch_candidate_assets.py --fetch-candidates --inputs video/r06_timeline/frozen_candidates_20261102_v2/inputs.assets-candidate.json --asset-root input-assets --output inputs.nonvoice-confirmed.json
```

该入口不自动执行：按35个声明ID下载到新目标文件，逐字节SHA256相同才promote confirmed=true；任何不符停止，不覆盖源件、不替换素材、不回退体验音。然后才对实际下载的19条音效/音乐运行ffprobe并填真实时长。可与两API批次的独立下载/导入脚本共用asset-root，指定文件不得已存在。27条语音仍需import_batches由state/receipt/hash/ffprobe填入；本候选没有其时长或听审结论。

缺少真实动作/道具图的beat用card_only_beats处理：renderer的静态图层opacity=0，画面为纯黑底加显式短卡，不让错误照片伪装成终端动画、寻呼机、撑门、挂听筒护母动作。保持03:09/03:15、原五句、日期及改句可读。其余已存在图仅静帧候选，不能当动作实现。音乐三首ID/hash和署名齐备但未进活跃cue；音效只保留5个明确草稿事件，避免自动展开beat重复拟音。实际混音、图片含义、字幕安全区、ASR同步及静音理解仍须后续验收。render_ready=false。
