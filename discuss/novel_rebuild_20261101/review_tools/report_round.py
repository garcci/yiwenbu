"""Extract existing review opinions only; never score, fill, or alter responses."""
import argparse
import json
from pathlib import Path

PIECE_NAMES = {'novel': '完整短篇小说', 'episode01': '第一集文字台本', 'season_outline': '六集改编结构'}


def report(root):
    root = Path(root)
    responses = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((root / 'responses').glob('*.json'))]
    summary = json.loads((root / 'summary_round01_verified/summary.json').read_text(encoding='utf-8'))
    rows = [(r['reviewer_id'], p, d, c) for r in responses for p, v in r['pieces'].items() for d, c in v['scores'].items()]
    low = [x for x in rows if x[3]['score'] < 9.5]
    data_errors = [e for e in summary['errors'] if ': score below threshold (' not in e]
    overview = [
        '# 首轮独立 Sol 原评意见整理', '',
        '本文件只提取十份原始回复的分数、理由、引文和意见分歧；不增加文学评分，不改稿，不将工具校验当作文学验收。组名只是原意见索引，不是新评委结论。', '',
        '事实：300格均有有效数值；最低7.5，总均8.842；低于9.5共282格。离线门槛未过。覆盖范围声明复核后，剩余数据校验错误为0。全文读完与独立调用不能仅由这些声明和离线工具独立证明。', '',
        '|作品|原评分均值（仅统计）|最低|低于9.5格数|', '|---|---:|---:|---:|']
    for p, name in PIECE_NAMES.items():
        scores = [c['score'] for _, piece, _, c in rows if piece == p]
        overview.append(f'|{name}|{sum(scores)/len(scores):.3f}|{min(scores):g}|{sum(s < 9.5 for s in scores)}|')
    overview += ['', '## 优先可改的共性原意见', '',
        '以下按重复出现的问题汇集，不表示修改后能达到任何分数。完整逐格原文见 [低分逐观点原记录](low_score_findings.md)，完整300格见 [评分表](matrix_300.md)。', '']
    groups = [
        ('小说前半：同一账目、纸张候选及瞒借心理反复解释', 'novel', ['01','02','03','04','05','06','07','08','09','10'],
         lambda x: any(k in x['description'] for k in ('重复','复述','重述','反复')) and any(k in x['description'] for k in ('前半','前五','前两','第二节'))),
        ('首集：旁白解释叠加，动作、反应和悬疑停顿余量偏紧', 'episode01', ['01','02','03','04','05','06','07','08','09','10'], lambda x: True),
        ('全季：末集容量重于前段，3—5分钟内多项收束挤压悲伤停留', 'season_outline', ['02','03','04','05','06','07','08','09','10'],
         lambda x: any(k in x['description'] for k in ('末集','第六集','后两集'))),
        ('小说及全季：沈砚的占有私心到供述才明确，前置关系行为不足', 'novel', ['01','02','04','06','07','09','10'],
         lambda x: any(k in x['description'] for k in ('私心','占有欲','取代长生'))),
    ]
    for title, piece, ids, predicate in groups:
        overview += [f'### {title}', '', f'在{PIECE_NAMES[piece]}的 major_issues 中明确提出的评委：' + '、'.join(ids) + '。', '']
        for r in responses:
            if r['reviewer_id'] not in ids:
                continue
            matches = [i for i in r['pieces'][piece]['major_issues'] if predicate(i)]
            for issue in matches:
                overview += [f'- 评委{r["reviewer_id"]}原意见：{issue["description"]}', f'  原引文：“{issue["evidence_quote"]}”']
        if piece == 'novel' and '私心' in title:
            overview += ['', '同类全季结构意见还见评委01、02、04、06、07、10的 major_issues；评委03、08、09未在全季 major_issues 中单列这一条，不据此推断他们否定或同意。']
        overview.append('')
    overview += ['## 少数意见，不能被共性覆盖', '']
    selected = [('04','novel', '泥袄'), ('05','novel','东高桥'), ('08','novel','二十匹'), ('01','season_outline','第二集'), ('09','season_outline','第五集')]
    for rid,p,key in selected:
        r = next(r for r in responses if r['reviewer_id'] == rid)
        for i in r['pieces'][p]['major_issues']:
            if key in i['description']:
                overview += [f'- 评委{rid}/{PIECE_NAMES[p]}：{i["description"]}', f'  原引文：“{i["evidence_quote"]}”']
    overview += ['', '## 评价尺度存在分歧：并列原理由，不替任何评委裁决', '',
                 '下列只展示同作品同维度的原评分最低者和最高者；同分取编号最前者。分差是事实，分差本身不证明意见互斥。', '']
    for p,d in [('novel','悬念信息公平'),('novel','因果规则一致'),('episode01','情感可信度'),('season_outline','对白与叙事呈现')]:
        candidates = [(r['reviewer_id'], r['pieces'][p]['scores'][d]) for r in responses]
        minimum = min(candidates, key=lambda x: x[1]['score'])
        maximum = max(candidates, key=lambda x: x[1]['score'])
        overview += [f'### {PIECE_NAMES[p]} / {d}', '']
        for label,(rid,c) in [('最低原分',minimum),('最高原分',maximum)]:
            overview += [f'- {label}：评委{rid}，{c["score"]:g}。原理由：{c["reason"]}', f'  原引文：“{c["evidence_quote"]}”']
        overview.append('')
    overview += ['## 数据与校验边界', '',
                 '归一化说明：原始 reviewer_09_reading_note.md 使用“人工判断”“独立人工评分”等措辞；按本轮实际调用身份，这些是GPT-6.1 Sol的AI模拟阅读推断与评分，不等于真人判断、真人评委或真人受众调查。原始记录保持原样，不能用其中措辞推定存在真人评分。', '',
                 '30条coverage均声明complete=true，字符数依次为19400、2388、4122，源哈希与封版一致。27条非空limitations经逐条语义复核，仅限定文字/未制作成片、未提供后续完整台本、未实测受众或外部史实核验；原回复逐字节保持不变。独立sidecar绑定封版、源和原回复字节，不改变评分、引文和调用记录。', '',
                 f'复验错误总数{len(summary["errors"])}；其中低于门槛{len(low)}，其余数据错误{len(data_errors)}。未解决实质硬伤的结构校验项为0；这只说明评委未报出该标签的未解决硬伤，不证明文本无硬伤。', '',
                 '原件：responses/reviewer_01.json 至 reviewer_10.json。范围复核：coverage_scope_review.json。复验：summary_round01_verified/summary.json 和 matrix_300.csv。28项合成工具测试通过，不能据此认定文学质量过关。']
    (root/'first_round_editorial_findings.md').write_text('\n'.join(overview)+'\n', encoding='utf-8')
    details = ['# 282格低于9.5的逐观点原记录', '', '以下逐字提取原分、原理由和原引文，包含肯定与不足；没有新增根因、评分或修改方案。阈值未过不等于整条理由全为负面。', '']
    for rid,p,d,c in low:
        details += [f'## 评委{rid} / {PIECE_NAMES[p]} / {d} / {c["score"]:g}', '', f'原理由：{c["reason"]}', '', f'原引文：“{c["evidence_quote"]}”', '']
    (root/'low_score_findings.md').write_text('\n'.join(details), encoding='utf-8')
    matrix = ['# 原评分300格', '', '只显示原分，不补分、不改分；每格理由和引文见CSV及原回复。', '']
    dimensions = list(responses[0]['pieces']['novel']['scores'])
    for p,name in PIECE_NAMES.items():
        matrix += [f'## {name}', '', '|维度|'+'|'.join(r['reviewer_id'] for r in responses)+'|', '|---|'+'---:|'*len(responses)]
        for d in dimensions:
            matrix.append('|'+d+'|'+'|'.join(f'{r["pieces"][p]["scores"][d]["score"]:g}' for r in responses)+'|')
        matrix.append('')
    (root/'matrix_300.md').write_text('\n'.join(matrix), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    report(parser.parse_args().root)
