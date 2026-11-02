#!/usr/bin/env python3
"""Offline ffprobe + SHA validation on declared files only. Never fetch or mutate sources."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def probe_catalog(data, root):
    root = root.resolve()
    for key, entry in data['assets'].items():
        relative = Path(entry['path'])
        if (relative.is_absolute() or '..' in relative.parts or
            re.search(r'result-\d+|未命名', key + ' ' + str(relative), re.I) or
            entry.get('provenance') in (None, '', 'experience', 'web_experience')):
            raise ValueError('Unsafe or excluded declared source')
        if entry.get('kind') == 'voice' and entry.get('provenance') != 'subscription_api_new':
            raise ValueError('Voice must be new subscription/API output')
        candidate = root / relative
        if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root):
            raise ValueError('Symlink source forbidden')
        path = candidate.resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise ValueError('Source unavailable')
        expected = entry.get('sha256', '')
        if not re.fullmatch(r'[0-9a-f]{64}', expected): raise ValueError('Trusted byte hash required before probe')
        h = hashlib.sha256()
        with path.open('rb') as f:
            for part in iter(lambda: f.read(1024 * 1024), b''): h.update(part)
        if h.hexdigest() != expected: raise ValueError('Declared byte hash mismatch')
        if entry['kind'] != 'image':
            r = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                               capture_output=True, check=False)
            if r.returncode: raise ValueError('ffprobe failed; source unchanged')
            d = json.loads(r.stdout); streams = [s for s in d['streams'] if s['codec_type'] == 'audio']
            if len(streams) != 1: raise ValueError('Expected one audio stream')
            entry['ffprobe'] = d
            entry['duration_seconds'] = float(streams[0].get('duration', d['format']['duration']))
            entry['duration_method'] = 'ffprobe'
        entry['local_bytes_verified'] = True
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True); p.add_argument('--asset-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    if a.output.exists(): raise SystemExit('Output exists; choose a new path')
    try: d = probe_catalog(json.loads(a.inputs.read_text()), a.asset_root)
    except (ValueError, KeyError, OSError): raise SystemExit('Probe stopped; declared inputs invalid or unavailable') from None
    a.output.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
    print('Declared bytes verified and audio metadata measured. No listening or speech alignment performed.')


if __name__ == '__main__': main()
