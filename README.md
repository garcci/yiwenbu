# 异闻簿 · 自动出片

古书里的怪事，多半有破绽。每天自动从 `topics.json` 取一个公版古籍故事，一篇稿子同时出三种东西：竖屏成片（短视频平台）、单集音频（喜马拉雅，开头带AI声明）、三种尺寸封面和发布文案。攒够几十集后可以一键拼成1小时横屏合集（YouTube/B站）。

完整的注册、发布、变现步骤见云盘里的《异闻簿发布手册》。

## 全部用免费渠道

| 环节 | 用什么 | 费用 |
|---|---|---|
| 写稿 | GitHub Models（Actions 自带 `GITHUB_TOKEN`，默认 `openai/gpt-4.1-mini`） | 免费额度 |
| 画面 | Cloudflare Workers AI · FLUX.1 schnell | 每天 10,000 neurons 免费 |
| 配音 | edge-tts，默认声线 `zh-CN-YunjianNeural` | 免费 |
| 跑流水线 | GitHub Actions 定时任务 | 公开仓库不限分钟，私有仓库每月 2000 分钟 |
| 存成片 | 直接写进你的谷歌云盘“短视频/异闻簿-成片”，另备份一份 Actions 产物（30天） | 免费 |

## 一次性设置（约10分钟）

1. 在 GitHub 新建仓库，把这些文件推上去（`daily.yml`、`extras.yml` 放到 `.github/workflows/`，`ep01.json` 放到 `episodes/`，`gitignore.txt` 改名为 `.gitignore`）。
2. Cloudflare 后台：记下 Account ID；在“我的个人资料 → API 令牌”新建令牌，权限选 Workers AI。
3. 仓库 Settings → Secrets and variables → Actions，添加 `CF_ACCOUNT_ID`、`CF_API_TOKEN`。
4. 云盘自动写入：按发布手册“配置云盘”一节，用 `get_drive_token.py` 拿令牌，添加 `GDRIVE_CLIENT_ID`、`GDRIVE_CLIENT_SECRET`、`GDRIVE_REFRESH_TOKEN`、`GDRIVE_FOLDER_ID` 四个 Secrets。不配也能出片，只是不会进云盘。
5. Actions 页面手动运行一次“每日出片”（episode 填 `episodes/ep01.json`），之后每天早上6点自动跑下一集。成片会出现在云盘“异闻簿-成片/第XX集”。
6. 运行一次“账号素材与长合集”，选“账号素材”，拿到头像、专辑封面、频道横幅。

## 本地跑

```bash
pip install requests pillow edge-tts boto3   # 另需 ffmpeg
export GITHUB_TOKEN=...  CF_ACCOUNT_ID=...  CF_API_TOKEN=...
python make_episode.py --episode episodes/ep01.json   # 用现成稿件
python make_episode.py --next                          # 全自动
python make_episode.py --episode episodes/ep01.json --images placeholder --tts silent   # 离线试版式
python make_assets.py --brand                          # 头像、专辑封面、频道横幅
python compile_long.py --from 1 --to 50                # 横屏长合集 + 章节时间戳
```

## 文件说明

- `make_episode.py` 单集出片：竖屏视频、单集音频、封面、文案
- `compile_long.py` 横屏长合集，复用每集已生成的画面
- `make_assets.py` 账号素材和封面（白底、朱红单一强调色）
- `gdrive.py` 把成片、音频、封面写进谷歌云盘，同名文件覆盖，只留最终版
- `get_drive_token.py` 一次性在自己电脑上运行，拿云盘刷新令牌
- `series.json` 栏目设定：画风、声线、强调色、片尾声明、音频开头声明、红线
- `topics.json` 选题队列，往后追加即可
- `episode_prompt.txt` 写稿提示词
- `episodes/` 稿件，可以手改后用 `--episode` 重新出片
- `assets/bgm.mp3` 放一首免版权背景音乐会自动混音（不放就只有人声）

## 发布前人工检查

1. 画面有没有崩手、多余文字、吓人的形象，有就删掉 `work/epXX/imgNN.jpg` 重跑该集。
2. 稿件出处和情节是否符合原著。
3. 发布时勾选平台的“AI生成”声明，文案用 `output/epXX.txt`。

注意：每集AI画面会提交回仓库的 `work/epXX/`，做合集时直接复用，不会重复消耗 Cloudflare 额度。
