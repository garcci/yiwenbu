#!/usr/bin/env python3
"""Freeze a NEW local-hash/Drive-ID candidate; read only declared allowed image/SFX/music bytes."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
SOURCE = Path('/Users/ziling/Documents/yiwenbu-discuss/output/ep01/r06_edit_plan/assets.json')
OUT = HERE / 'frozen_candidates_20261102_v2'


def main():
    if OUT.exists(): raise SystemExit('Frozen output exists; never overwrite')
    evidence = json.loads((HERE / 'assets_drive_metadata_20261102.json').read_text())
    assets = json.loads(SOURCE.read_text())['assets']
    meta = {x['value']['id']: x['value']['result']['structuredContent'] for x in evidence['metadata'] if x['status'] == 'fulfilled'}
    replacements = {'I01': '深夜值班的电话调度员.png', 'I02': '深夜电讯室的专注值班员.png',
                    'I03': '深夜复古电脑工作台.png', 'I07': '昏灯下的温柔对话.png', 'I13': '门边的深夜家常 *'}
    result = json.loads((HERE / 'inputs.template.json').read_text()); audit = []
    for original in assets:
        key = original['id']
        if original['kind'] == 'voice_pending': continue
        cloud = meta[key]
        local = Path(original.get('local_candidate_path') or original.get('local_path'))
        if key in replacements:
            matches = list(Path('/Users/ziling/Downloads').glob(replacements[key]))
            if len(matches) != 1: raise ValueError('Replacement candidate ambiguous')
            local = matches[0]
        if local.suffix.lower() not in ('.png', '.wav', '.mp3') or 'Result-' in local.name or '未命名' in local.name:
            raise ValueError('Excluded source')
        data = local.read_bytes(); sha = hashlib.sha256(data).hexdigest(); md5 = hashlib.md5(data).hexdigest()
        remote_md5 = cloud.get('md5Checksum') or cloud.get('md5_checksum')
        verified = remote_md5 is not None and remote_md5 == md5
        kind = {'ai_still': 'image', 'procedural_sfx': 'sfx', 'music': 'music'}[original['kind']]
        entry = {'kind': kind, 'path': 'assets/' + kind + '/' + key + local.suffix,
                 'drive_file_id': original['drive_id'], 'sha256': sha, 'local_md5': md5,
                 'confirmed': verified, 'pairing_status': 'drive_metadata_md5_match' if verified else 'candidate_pending_cloud_byte_sha256',
                 'local_candidate_path': str(local), 'local_bytes': len(data), 'cloud_metadata_bytes': int(cloud['size']),
                 'cloud_metadata_name': cloud['title'], 'cloud_md5': remote_md5,
                 'cloud_metadata_size_matches': len(data) == int(cloud['size']),
                 'provenance': {'image': 'existing_GPT_still', 'sfx': 'original_procedural', 'music': 'official_incompetech_CC_BY_4'}[kind],
                 'image_content_review': 'not newly visually reviewed; source label is draft scene candidate',
                 'listening_review': 'not performed in this task'}
        if kind != 'image':
            entry.update(authorized_for_this_draft=True, duration_seconds=None, duration_method=None, ffprobe=None)
        if key == 'F07': entry['first_impact_seconds'] = .4
        if kind == 'music':
            title = {'M1': 'Long note One', 'M2': 'Evening Fall (Piano)', 'M3': 'Dark Walk'}[key]
            entry.update(license='CC BY 4.0', credit_read_seconds=7,
                         attribution_lines=[title+' — Kevin MacLeod', 'incompetech.com | CC BY 4.0',
                            'https://creativecommons.org/licenses/by/4.0/', '节选、重新排列、淡化与音量调整'],
                         attribution_text=title+' — Kevin MacLeod (incompetech.com)\nSource: '+original['source_url']+
                         '\nLicensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n音乐节选、重新排列、淡入淡出及音量调整。作者不为作品背书。')
        result['assets'][key] = entry
        audit.append({'id': key, 'original_local_path': original.get('local_candidate_path') or original.get('local_path'),
                      'replacement_by_unique_size_and_known_filename': key in replacements, 'new_candidate': entry})
    images = {'S1B01':'I02','S1B02':'I01','S1B03':'I01','S1B04':'I01','S1B05':'I01','S1B06':'I01','S1B07':'I02',
              'S2B01':'I04','S2B02':'I05','S2B03':'I05','S3B01':'I06','S3B02':'I07',
              'S4B01':'I08','S4B02':'I09','S5B01':'I10','S5B02':'I10','S5B03':'I11','S5B04':'I12',
              'S6B01':'I13','S6B02':'I13','S6B03':'I14','S6B04':'I13',
              'S7B01':'I13','S7B02':'I13','S7B03':'I13','S7B04':'I15','S7B05':'I16','S7B06':'I13'}
    result['assets'].pop('CREDIT_IMAGE', None)
    result['beat_images'] = images
    result['credit_image'] = 'I13'
    result['card_only_beats'] = ['S1B01','S2B03','S3B02','S5B02','S6B01','S7B01','S7B02','S7B03','S7B05','S7B06']
    extra = {'S6B01': ['傍晚，青禾回母亲家设防','门栓与木棍撑门动作尚缺镜头'],
             'S7B05': ['动作预演：放回听筒 → 先护母', '抵门和木棍 → 禁声', '连续动作尚缺镜头，不揭门外身份']}
    for key, lines in extra.items():result['story_cards'][key]={'read_seconds':4, 'lines':lines}
    result['status'] = 'NEW frozen candidate; all 35 cloud MD5 unavailable; not confirmed; voices pending measured import'
    result['render_ready'] = False
    result['sound_events'] = [
      {'id':'machine_room_open','asset_id':'F01','anchor':{'type':'beat_start','id':'S1B01'},'duration':12,'volume':.18,'role':'ambience','fade_in':.5,'fade_out':1},
      {'id':'copy_page','asset_id':'F13','anchor':{'type':'beat_end','id':'S2B01'},'source_start':.3,'duration':.5,'volume':.12},
      {'id':'pager_screen','asset_id':'F05','anchor':{'type':'beat_start','id':'S3B02'},'duration':1.7,'volume':.18},
      {'id':'backdoor_wind','asset_id':'F03','anchor':{'type':'beat_start','id':'S4B01'},'duration':12,'volume':.15,'role':'ambience','fade_in':.5,'fade_out':1},
      {'id':'door_three_knocks','asset_id':'F07','anchor':{'type':'speech_end','id':'S7_26'},'source_start':0,'duration':6,'volume':.3}]
    # No active music without chosen excerpt/listening. Full three-track IDs/hashes/credits are available.
    OUT.mkdir()
    for name, obj in [('inputs.assets-candidate.json', result), ('asset_pairing_audit.json', {'items':audit,'cloud_md5_verified_count':sum(x['new_candidate']['confirmed'] for x in audit),'local_sha256_measured_count':len(audit),'no_audio_duration_measurements':True,'no_voice_bytes_accessed':True})]:
        (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    (OUT/'freeze.json').write_text(json.dumps({'source_assets_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()},'render_ready':False},indent=2))
    print('Frozen candidate: 35 local hashes; no cloud MD5 fields; no confirmations or invented durations')


if __name__ == '__main__': main()
