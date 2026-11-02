# 独立 AI 模拟审稿记录工具

仅使用 Python 标准库；离线生成文件与验证记录，不调用 Gemini、不收费。读取父目录 `review_protocol.json`。不提供文学创作或评分，绝不填补缺分、伪造实际评论或调整分数。

## 准备封版

```sh
python3 review_matrix.py prepare --novel /绝对路径/小说.txt --episode01 /绝对路径/第一集.txt --season-outline /绝对路径/全季.txt --out /绝对路径/新的封版目录
```

输出三份逐字节快照、`manifest.json` 和 10 个 `reviewer_XX.prompt.txt`。每份提示含全部三份正文；每位评委必须使用新的独立 Gemini 会话，不传递作者讨论、旧分或其他评委回复。提示包含固定量尺，不透露放行门槛。UTF-8 原文不可在准备后更改；改稿必须新建封版并重新独立审稿。输出目录已存在时拒绝覆盖。

## 收集真实记录

每位评委的原始 JSON 回复单独存入 responses 目录（仅 10 个 `.json` 文件，不要先改分或补字段）。每次调用状态由实际调用记录据实生成，单独存 statuses 目录（仅 10 个 `.json` 文件），格式如下；此处是字段示意，不是实际调用：

```json
{
  "reviewer_id": "01",
  "transport": "cli",
  "input_hash": "manifest中的input_hash",
  "success": true,
  "exit_code": 0,
  "independent_session": true,
  "model": "实际Gemini模型名称",
  "call_id": "本次独立会话或调用的唯一标识",
  "response_sha256": "原始回复JSON文件字节的SHA256"
}
```

`transport="cli"` 保留进程退出码与 Gemini 模型名检查。官方 Gemini 网页审稿使用 `transport="browser"`，不需要、不应虚构进程 `exit_code`；共同字段 `reviewer_id`、`input_hash`、`success=true`、`independent_session=true`、唯一 `call_id`、`response_sha256` 保留，替换 CLI 专属字段为：

```json
{
  "transport": "browser",
  "response_completed": true,
  "extraction_complete": true,
  "private_session": true,
  "session_url": "https://gemini.google.com/app/实际独立私有会话标识",
  "model_label": "界面实际可见的模型标签，如Argon",
  "response_truncated": false,
  "api_error": null
}
```

以上为合并字段示意，不是完整实际状态或真实调用凭证。各次浏览器会话 URL 必须唯一，且来自官方 `https://gemini.google.com/app/` 下的具体会话。必须有实际完整回复及提取记录；API 错误、截断、只有输入框、仅模型选中或仅提交成功都不能标记完成。这些字段由操作者据实记录，工具不联网验证，不能单独证明已读完、私有会话状态或后台真实模型；`model_label` 仅记录界面文字，不由 Argon 等标签推断后台模型名称。主编审稿也不能自动作为十位终评之一。

状态失败不得改写成成功。重试保留旧调用记录在别的审计目录；用于本轮验收的十次调用须各自对应同一封版的一份真实完整回复。不要把合成 fixture 放进实际记录目录。

```sh
python3 review_matrix.py validate --manifest /绝对路径/封版目录/manifest.json --responses /绝对路径/responses --statuses /绝对路径/statuses --out /绝对路径/新的汇总目录
```

输出 `matrix_300.csv` 与 `summary.json`，无论缺多少分仍列出全部 300 格；缺失值保留为空，不补分。任一单格低于9.5、无效或缺分、缺作品/维度/评委、重复记录/JSON键、哈希错误、覆盖不足、引文不符、未解决实质硬伤或调用失败，`gate=false`，退出码2。均分仅统计。异常终止也不得视作通过。

`gate=true` 只表示所提交记录通过这些离线约束。程序不能独立证明调用真实、会话独立、全文确实读完、评论依据充分或文学质量达标；开头结尾引文与覆盖声明也不是读完的证明。必须核对原始调用证据与实际回复，不能用工具成功代替质量验收。

## 合成自检

```sh
python3 -m unittest -v test_synthetic.py
```

fixture 全部临时生成，并明确写为合成假数据；测试结束删除，不产出实际验收。测试涵盖全高分结构样例、单格低分、缺维度、错哈希、重复评委、缺读、假引文、调用失败、未解决硬伤、重复 JSON 键。

浏览器分支另测合成完整记录、未完成、缺少完整提取、API错误和截断。所有合成状态与分数均不是实际 Gemini 审稿，不得复制进 actual 或真实审稿目录。

## 单篇输入与三件归档合并

为manifest中全部既定persona生成单篇提示，每份只含对应封版源全文；当前十个视角各三件，共30份。早期只生成01—07的准备文件仍作为历史保留。

```sh
python3 piecewise_review.py generate --manifest /绝对路径/封版目录/manifest.json --out /绝对路径/新的提示目录
```

历史首轮准备在 `review_round01/piecewise_prompts/`；第四轮覆盖全十位的准备在 `review_round04/piecewise_prompts_all10/`。名称为 `reviewer_01_novel.prompt.txt`、`reviewer_01_episode01.prompt.txt`、`reviewer_01_season_outline.prompt.txt`，依此至10。量尺、正文和门槛不变；提示先短连续证据，再具体已做到/不足及分数，不给旧分或目标分，不要求因缺音画扣分。明确无不足时可说明个人审美保留；首尾40字符和长度仅是格式元数据，不能证明阅读。生成文件不等于已实际调用或完成评分。

每个单篇回复是一个JSON对象，顶层含 `reviewer_id`、`input_hash`（父封版集合）、`piece`、`source_sha256`、`coverage`、`opening_quote`、`ending_quote`、`scores`、`major_issues`。评分数据结构不变。三件各用新的独立私有网页会话，跨persona也不得重复会话。该方式是本轮允许的分件阅读方式，不声称某一会话同时读过三件。

每件真实浏览器状态采用前述完整 `transport="browser"` 格式，另外明确 `piece` 与 `source_sha256`，`response_sha256` 必须对应这件原始回复字节。真实 `call_id` 可由本次实际会话URL派生，注明来源；不得编造成功、提取、私有性、时间、模型或进程退出码。

合并入口只归档，不运行模型、不修正或补写评价、不宣称通过：

```sh
python3 piecewise_review.py merge --manifest /绝对路径/封版目录/manifest.json --reviewer 01 --novel-response /原件/01_novel.json --novel-status /原件/01_novel_status.json --episode01-response /原件/01_episode01.json --episode01-status /原件/01_episode01_status.json --season-outline-response /原件/01_season_outline.json --season-outline-status /原件/01_season_outline_status.json --out /绝对路径/新的01归档目录
```

输出 `responses/reviewer_01.json`、`statuses/reviewer_01_status.json` 与 `raw/` 三组原字节回复及状态快照。合并响应的 `ai_simulation=true` 是归档方对AI模拟记录的标识；不改变三份原始评价，也不冒称它是单次模型回复。归档状态使用 `transport="browser_piecewise"`，嵌套保留三件的真实status、raw哈希、来源、实际会话URL和model_label，不添加虚构的顶层success/call_id/exit_code。失败状态也如实归档，待validate拦截；身份或封版不一致则拒绝合并。

将各persona归档的合并响应和状态纳入同一待验目录再运行原 `review_matrix.py validate`；保留归档raw所在位置（记录使用绝对路径）。验证器重新读取并校验全部raw字节、嵌套状态原值、三件同源和与合并响应一致；三件必须各自完成且独立，不能重用会话或call_id。归档命令成功仅说明文件准备好，不表示调用完成或文学质量通过。

## Sol辅助终评状态

协议可记录任意合法persona的未参与写作Sol独立审评，不限于08/09/10。首轮因Gemini审评的返回证据或运输失败，已由十个Sol独立评委完成复核；主要改稿仍由Gemini承担。这是本轮执行事实，不承诺今后全部采用Sol。Gemini界面当前已恢复Argon可选，但新的审评调用是否实际完成仍待完整返回证据确认。回复仍为完整三作品原JSON结构；状态 `transport="subagent"`，无需、也不应伪造网页URL或进程码：

```json
{
  "reviewer_id": "08",
  "input_hash": "父manifest的实际input_hash",
  "transport": "subagent",
  "agent_task_id": "实际独立agent任务ID",
  "model_label": "实际可见Sol模型标签",
  "success": true,
  "agent_completed": true,
  "extraction_complete": true,
  "independent_session": true,
  "participated_in_writing": false,
  "response_sha256": "真实原始完整回复JSON字节SHA256"
}
```

任务ID跨persona须唯一；任何未完成、缺提取、不独立、参与写作或哈希不符均拦截。状态只是据实记录，离线工具不能验证运行平台的实际模型身份或实际阅读质量。

## 严格引文与格式差异诊断

原逐字引文、首尾、评分门槛及gate逻辑保持。`summary.json` 新增 `format_equivalence_diagnostics_only`：仅对严格未匹配字段，另报告去除空白、Markdown装饰或引文最外层成对引号后是否能匹配；诊断不修改raw、不放行、不改分。省略、换字、跨处拼接、概述或不存在句子不能按语义自动视为原文。格式等价为false仍需人工区分具体原因，不能将所有未匹配都推定为没有阅读。

新增合成测试：

```sh
python3 -m unittest -v test_synthetic.py test_piecewise_synthetic.py
```

所有fixture继续临时生成、明确标注SYNTHETIC并自动删除；合成结构通过不是本轮真实验收通过。


## 覆盖限制的逐条复核（2026-11-02）

`coverage.complete=true`、精确字符数和源哈希继续是独立硬门；非空 `limitations` 不再被混称为哈希错误。默认仍拒绝非空或缺失/无效的限制声明，必须提供独立范围复核记录：

```sh
python3 review_matrix.py validate --manifest /封版/manifest.json --responses /原回复目录 --statuses /真实状态目录 --coverage-reviews /独立目录/coverage_scope_review.json --out /新的汇总目录
```

sidecar 顶层含 `input_hash`、`manifest_sha256` 和 `entries`。每条范围认可含 `reviewer_id`、`piece`、`decision="scope_only"`、`response_sha256`、`source_sha256`、逐字段原样的 `coverage` 与非空 `rationale`。只有绑定原字节与当前封版的记录才接受；空限制本来不需认可。逐条复核只能认可“仅评价所给文字，不认证未制作音画/未提供完整后续台本/未实测受众或外部事实”等范围边界，不能将自述漏读认可为范围限制。原始回复不得改动。sidecar是明确的操作者审计声明，程序不自动理解其语义，也不能证明实际读完。

回归测试包含：合法范围声明未经复核失败、绑定复核后通过、即使有范围sidecar但确实自述未读完/字符数不足仍失败、原覆盖声明改变后旧sidecar失败。

本轮可运行 `python3 report_round.py /绝对路径/review_round01/sol_final`，从本轮原回复和 `summary_round01_verified` 提取300格、低分原理由与共性意见索引；它不调用模型，不产生评分或改稿。文学未过与数据有效须分别报告。
