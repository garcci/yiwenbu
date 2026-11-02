#!/usr/bin/env python3
"""Prepared CI-only fetch/strong-SHA confirmation for frozen nonvoice candidates. Not called implicitly."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from probe_catalog import probe_catalog

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ci_render'))
import drive_io


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fetch-candidates', action='store_true', required=True)
    p.add_argument('--inputs', type=Path, required=True); p.add_argument('--asset-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    if a.output.exists(): raise SystemExit('New output required')
    data = json.loads(a.inputs.read_text()); selected = {}
    for key, entry in data['assets'].items():
        if entry['kind'] == 'voice': continue
        if not re.fullmatch(r'(I[0-9]{2}|F[0-9]{2}|M[1-3])', key):
            raise SystemExit('Only frozen declared image/SFX/music keys accepted')
        if entry.get('provenance') not in ('existing_GPT_still', 'original_procedural', 'official_incompetech_CC_BY_4'):
            raise SystemExit('Undeclared/experience provenance refused')
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
            raise SystemExit('Invalid candidate path/hash')
        drive_io.file_id(entry['drive_file_id']); selected[key] = entry
    # Validate all refs before opening a network session; no credential arguments or prints.
    import requests
    module = drive_io.drive_module()
    try:
        a.asset_root.mkdir(parents=True, exist_ok=True)
        root = a.asset_root.resolve()
        with requests.Session() as session:
            session.headers['Authorization'] = 'Bearer ' + module._token()
            for key, entry in selected.items():
                target = root / entry['path']
                if target.exists() or any(p.is_symlink() for p in target.parents if p != root):
                    raise ValueError('Existing/symlink destination; no overwrite')
                target.parent.mkdir(parents=True, exist_ok=True)
                drive_io.download(session, entry['drive_file_id'], target, 100 * 1024 * 1024)
                if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('Candidate/cloud bytes differ; stop, never substitute')
                entry['confirmed'] = True
                entry['pairing_status'] = 'downloaded_drive_bytes_sha256_match'
        # Only now measure nonvoice sources. This step is never claimed complete by preparation.
        measured = probe_catalog({'assets': selected}, root)
        data['assets'].update(measured['assets'])
        data['status'] = 'Declared nonvoice candidates SHA256-confirmed in this CI run; voice/listening pending'
        a.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        print('Declared nonvoice cloud bytes SHA256 verified; measured audio duration recorded; listening pending.')
    except Exception:
        raise SystemExit('Candidate fetch stopped; no fallback/overwrite/retry; no service responses or credentials logged') from None


if __name__ == '__main__': main()
