#!/usr/bin/env python3
"""Fetch a declared bundle, or explicitly upload a QC-passed draft. Never log tokens/responses."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import asset_references, blocked, digest, require


def drive_module():
    spec = importlib.util.spec_from_file_location('repo_gdrive', Path(__file__).resolve().parents[2] / 'gdrive.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_id(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{10,200}', value), 'Invalid Drive file ID')
    return value


def download(session, identifier, destination, max_bytes):
    # Fixed Drive endpoint; neither arbitrary URLs nor shell arguments are accepted.
    url = 'https://www.googleapis.com/drive/v3/files/' + file_id(identifier)
    count = 0
    with session.get(url, params={'alt': 'media'}, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        with destination.open('xb') as f:
            for chunk in response.iter_content(1024 * 1024):
                count += len(chunk)
                require(count <= max_bytes, 'Drive input exceeds size limit')
                f.write(chunk)


def fetch(identifier, destination):
    import requests
    module = drive_module()
    require(not destination.exists(), 'Input directory must not already exist')
    destination.mkdir(parents=True)
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + module._token()
        bundle_file = destination / 'bundle.json'
        download(session, identifier, bundle_file, 5 * 1024 * 1024)
        bundle = json.loads(bundle_file.read_text())
        manifest, mapping = bundle['manifest'], bundle['assets']
        # Enumerate ALL references first. No excluded audio is opened/downloaded.
        refs = asset_references(manifest)
        targets = set()
        for source, kind in refs.items():
            entry = mapping[source]
            require(kind != 'audio' or entry.get('authorized_for_this_draft') is True,
                    'Current draft audio authorization missing')
            require(not blocked(entry['path']), 'Forbidden mapped filename')
            relative = Path(entry['path'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe relative path')
            target = (destination / relative).resolve()
            require(target.is_relative_to(destination.resolve()) and target not in targets
                    and target.name not in {'bundle.json', 'manifest.json', 'asset-map.json'}, 'Duplicate/reserved asset path')
            targets.add(target)
            file_id(entry['drive_file_id'])
            sha = entry['sha256']
            require(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{64}', sha), 'SHA256 required')
        for source in refs:
            entry = mapping[source]
            target = destination / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            download(session, entry['drive_file_id'], target, 512 * 1024 * 1024)
            require(digest(target) == entry['sha256'], 'Downloaded asset SHA256 mismatch')
        (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        (destination / 'asset-map.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f'Downloaded declared bundle and {len(refs)} assets. No generation API used.')


def upload(directory, subfolder):
    module = drive_module()
    require(module.enabled(), 'Drive credentials/destination are required for explicit upload')
    require(re.fullmatch(r'ci-drafts/[A-Za-z0-9_-]+', subfolder), 'Use a unique ci-drafts/run-id subfolder')
    report = json.loads((directory / 'qc.json').read_text())
    require(report.get('structural_pass') is True and report.get('decoded_to_end') is True,
            'Upload requires successful structural QC and full decoding')
    require(digest(directory / 'draft.mp4') == report['output_sha256'], 'Output changed after QC')
    # Reuse OAuth, folder handling and upload protocol; bypass _put retry logging,
    # whose RequestException text can expose a resumable upload URL.
    headers = {'Authorization': 'Bearer ' + module._token()}
    parent = module._folder(headers, subfolder)
    for name in ('draft.mp4', 'qc.json', 'captions.ass'):
        module._put_once(headers, directory / name, parent)
    print('QC-passed draft uploaded to the authorized Drive folder; not publicly published.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    a = commands.add_parser('fetch')
    a.add_argument('--bundle-id', required=True)
    a.add_argument('--destination', type=Path, required=True)
    b = commands.add_parser('upload')
    b.add_argument('--directory', type=Path, required=True)
    b.add_argument('--subfolder', required=True)
    args = p.parse_args()
    try:
        if args.command == 'fetch':
            fetch(args.bundle_id, args.destination)
        else:
            upload(args.directory, args.subfolder)
    except Exception:
        # Do not include RequestException, URLs, auth headers, response bodies, or credentials.
        raise SystemExit('Drive operation failed; no service response or credentials logged.') from None


if __name__ == '__main__':
    main()
