#!/usr/bin/env python3
"""Merge two ALREADY DOWNLOADED known API batches. Offline; no directory discovery/network."""
import argparse
import hashlib
import json
from pathlib import Path
from probe_catalog import probe_catalog

FOLDERS = ('1izOd2bZjaCTlCq_NS0IVvBsHLZKCHHmQ', '1XBq5kFbvg4bKcDJi1v61VobkaGb5Ap2a')
HERE = Path(__file__).resolve().parent


def merge(data, roots, asset_root):
    expected = {v['id']: v['text'] for v in json.loads((HERE / 'voice_lines_r06.json').read_text())['lines']}
    seen = set()
    for folder_id, directory in zip(FOLDERS, roots):
        directory = directory.resolve()
        if not directory.is_relative_to(asset_root.resolve()): raise ValueError('Batch must be inside asset root')
        state = json.loads((directory / 'state.json').read_text())
        frozen = json.loads((directory / 'manifest.frozen.json').read_text())
        # Supply index downloaded with metadata. Never guess a Drive ID from a filename.
        index = json.loads((directory / 'drive_upload.json').read_text())
        if index.get('folder_id') != folder_id: raise ValueError('Unexpected API batch folder')
        files = {}
        for item in index['files']:
            if item['name'] in files: raise ValueError('Duplicate Drive filename; resolve explicitly')
            files[item['name']] = item['id']
        payload = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        if hashlib.sha256(payload).hexdigest() != state['manifest_sha256']: raise ValueError('Frozen batch hash mismatch')
        for segment in frozen['segments']:
            sid = segment['id']; record = state['segments'][sid]
            if sid in seen or segment['text'] != expected.get(sid) or record.get('status') != 'completed':
                raise ValueError('Duplicate/changed/incomplete API segment')
            seen.add(sid)
            if record.get('request_count') != 1 or not record.get('github_run_id') or not record.get('authorization_id'):
                raise ValueError('API receipt provenance missing')
            path = directory / (sid + '.mp3')
            relative = str(path.relative_to(asset_root.resolve()))
            data['assets'][sid] = {'kind': 'voice', 'path': relative, 'drive_file_id': files[sid + '.mp3'],
                'sha256': record['audio_sha256'], 'confirmed': True, 'provenance': 'subscription_api_new',
                'authorized_for_this_draft': True, 'source_text': segment['text'], 'source_text_verified': True,
                'github_run_id': record['github_run_id'], 'api_folder_id': folder_id,
                'speech_start': None, 'speech_end': None, 'speech_boundary_method': None,
                'caption_method': None, 'captions': []}
    if seen != set(expected): raise ValueError('Both known batches must supply exact 27 IDs')
    # Probe declared voices only, leaving image/music entries for separately verified catalog input.
    measured = probe_catalog({'assets': {k: data['assets'][k] for k in seen}}, asset_root)
    data['assets'].update(measured['assets'])
    data['api_audio_status'] = '27 source texts and byte hashes verified; ffprobe measured; listening pending'
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True); p.add_argument('--asset-root', type=Path, required=True)
    p.add_argument('--batch01', type=Path, required=True); p.add_argument('--batch02', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    if a.output.exists(): raise SystemExit('Choose a new output path')
    try: d = merge(json.loads(a.inputs.read_text()), [a.batch01, a.batch02], a.asset_root)
    except (ValueError, KeyError, OSError): raise SystemExit('Batch import stopped; missing/mismatched declared evidence') from None
    a.output.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
    print('Two known batches imported offline; 27 audio byte hashes and measured durations verified. Listening pending.')


if __name__ == '__main__': main()
