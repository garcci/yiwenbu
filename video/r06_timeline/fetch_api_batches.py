#!/usr/bin/env python3
"""Prepared cloud-only fetch of two fixed known output folders; never a generation call."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from import_batches import FOLDERS

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fetch-known-batches', action='store_true', required=True,
                   help='Explicit network opt-in; never invoked by builder/tests')
    p.add_argument('--destination', type=Path, required=True); a = p.parse_args()
    if a.destination.exists(): raise SystemExit('New destination required')
    # Credentials come only from existing repository Drive OAuth helper, never args/files/logs.
    spec = importlib.util.spec_from_file_location('project_gdrive', HERE.parents[1] / 'gdrive.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    import requests
    try:
        a.destination.mkdir(parents=True)
        with requests.Session() as session:
            session.headers['Authorization'] = 'Bearer ' + module._token()
            for n, folder_id in enumerate(FOLDERS, 1):
                directory = a.destination / ('batch%02d' % n); directory.mkdir()
                items = []; page = None
                while True:
                    params = {'q': "'" + folder_id + "' in parents and trashed=false",
                              'fields': 'files(id,name,size,mimeType,parents),nextPageToken', 'pageSize': 1000}
                    if page: params['pageToken'] = page
                    r = session.get('https://www.googleapis.com/drive/v3/files', params=params, timeout=60,
                                    allow_redirects=False); r.raise_for_status(); d = r.json(); items.extend(d['files'])
                    page = d.get('nextPageToken')
                    if not page: break
                index = {}
                for item in items:
                    name = item['name']
                    if name in index: raise ValueError('Duplicate filename in known folder')
                    index[name] = item
                def download(name, limit):
                    item = index[name]
                    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or int(item['size']) > limit:
                        raise ValueError('Unexpected metadata in fixed batch folder')
                    response = session.get('https://www.googleapis.com/drive/v3/files/' + item['id'],
                                           params={'alt': 'media'}, timeout=180, stream=True, allow_redirects=False)
                    response.raise_for_status(); count = 0; target = directory / name
                    with target.open('xb') as f:
                        for chunk in response.iter_content(1024 * 1024):
                            count += len(chunk)
                            if count > limit: raise ValueError('Declared batch input too large')
                            f.write(chunk)
                    if count != int(item['size']): raise ValueError('Drive byte count mismatch')
                    return target
                state = json.loads(download('state.json', 2_000_000).read_text())
                frozen = json.loads(download('manifest.frozen.json', 2_000_000).read_text())
                expected = {v['id']: v['text'] for v in json.loads((HERE / 'voice_lines_r06.json').read_text())['lines']}
                payload = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
                if hashlib.sha256(payload).hexdigest() != state['manifest_sha256']: raise ValueError('Batch manifest mismatch')
                for segment in frozen['segments']:
                    sid = segment['id']
                    if sid not in expected or segment['text'] != expected[sid] or not re.fullmatch(r'S[1-7]_[0-9]{2}', sid):
                        raise ValueError('Unexpected API paragraph')
                    record = state['segments'][sid]
                    if record['status'] != 'completed': raise ValueError('API paragraph not complete')
                    receipt = json.loads(download(sid + '.receipt.json', 100_000).read_text())
                    if receipt != record: raise ValueError('Receipt/state mismatch')
                    audio = download(sid + '.mp3', 100_000_000)
                    if hashlib.sha256(audio.read_bytes()).hexdigest() != record['audio_sha256']:
                        raise ValueError('API audio hash mismatch')
                (directory / 'drive_upload.json').write_text(json.dumps({'folder_id': folder_id,
                    'files': [{'name': item['name'], 'id': item['id']} for item in items]}, ensure_ascii=False, indent=2))
        print('Two fixed API batches downloaded and byte hashes checked. Run import_batches for ffprobe. No generation or upload used.')
    except Exception:
        raise SystemExit('Fixed batch fetch stopped; no service responses or credentials logged; no retry/fallback') from None


if __name__ == '__main__': main()
