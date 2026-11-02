#!/usr/bin/env python3
"""One authorized Drive -> FFmpeg -> private Drive technical preview. No generation APIs."""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ci_render'))
from drive_io import download, drive_module, file_id
from render import digest, plan, render, require, resolve_assets
from prepare_bundle import bundle, encoded_bundle, FOLDER_ID

BRANCH = 'refs/heads/claude/project-thread-l4wz3r'
REPOSITORY = 'garcci/yiwenbu'
WORKFLOW = 'ep01_drive_e2e_once_20261102.yml'
TRIGGER = HERE / 'execute-once.json'
EXPECTED_BUNDLE_SHA = hashlib.sha256(encoded_bundle()).hexdigest()


def check_marker(marker):
    require(set(marker) == {'authorization', 'bundle_drive_id', 'bundle_sha256', 'zero_added_cost_confirmed'},
            'Unexpected trigger fields')
    require(marker['authorization'] == 'drive-e2e-technical-preview-20261102-once', 'Authorization mismatch')
    require(marker['zero_added_cost_confirmed'] is True, 'Current zero added cost evidence required')
    file_id(marker['bundle_drive_id'])
    require(marker['bundle_sha256'] == EXPECTED_BUNDLE_SHA, 'Bundle hash does not match frozen declaration')
    require((HERE / 'input-bundle.json').read_bytes() == encoded_bundle(), 'Repository bundle drift')
    plan(bundle()['manifest'])


def github_context():
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push', 'Only the authorized push event is permitted')
    require(os.environ.get('GITHUB_REF') == BRANCH, 'Unexpected branch')
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Unexpected repository')
    require(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'Reruns forbidden')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    require(re.fullmatch(r'[0-9]+', run_id), 'Invalid run ID')
    check_marker(json.loads(TRIGGER.read_text()))
    return run_id


def preflight():
    run_id = github_context()
    # Read-only run history: a previous run, even failed, consumes this one-time workflow.
    # A second attempt needs a newly scoped authorization and a separate workflow.
    url = f'https://api.github.com/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?event=push&per_page=100'
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    require(data['total_count'] <= 100, 'Cannot verify full workflow history')
    require(all(str(r['id']) == run_id for r in data['workflow_runs']), 'This one-time workflow was already attempted')
    print('One-time scope and zero-added-cost acknowledgement validated; no Drive access or generation request made.')


def create_only_upload(session, module, path, parent):
    # The name check is advisory. A racing same-name create must never switch us
    # to an update: POST files.create has no existing file ID in its endpoint.
    require(module._find(dict(session.headers), path.name, parent) is None,
            'Output already exists; overwrite forbidden')
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    created = session.post(module.UPLOAD,
        headers={'X-Upload-Content-Type': mime, 'X-Upload-Content-Length': str(path.stat().st_size)},
        params={'uploadType': 'resumable', 'fields': 'id'},
        json={'name': path.name, 'parents': [parent]}, timeout=60)
    created.raise_for_status()
    location = created.headers.get('Location', '')
    from urllib.parse import urlsplit
    destination = urlsplit(location)
    require(destination.scheme == 'https' and destination.netloc == 'www.googleapis.com'
            and destination.path == '/upload/drive/v3/files', 'Unexpected upload session endpoint')
    with path.open('rb') as data:
        uploaded = session.put(location, headers={'Content-Type': mime}, data=data, timeout=3600)
    uploaded.raise_for_status()
    # Verify only the ID returned by this creation, never a second name lookup
    # that could select a competing same-name file.
    return file_id(uploaded.json()['id'])


def execute():
    import requests
    run_id = github_context()
    marker = json.loads(TRIGGER.read_text())
    module = drive_module()
    require(module.enabled() and os.environ['GDRIVE_FOLDER_ID'] == FOLDER_ID, 'Unexpected Drive destination')
    root = Path(tempfile.mkdtemp(prefix='drive-e2e-once-'))
    print('Retaining this run directory:', root)
    declared = bundle()
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + module._token()
        raw_bundle = root / 'cloud-input-bundle.json'
        download(session, marker['bundle_drive_id'], raw_bundle, 5 * 1024 * 1024)
        require(digest(raw_bundle) == EXPECTED_BUNDLE_SHA, 'Cloud input bundle changed')
        require(raw_bundle.read_bytes() == encoded_bundle(), 'Cloud bundle differs from frozen declaration')
        # Only frozen repository IDs are used, after cloud bundle equality. No expansion from cloud instructions.
        for entry in declared['assets'].values():
            target = root / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            download(session, entry['drive_file_id'], target, 4 * 1024 * 1024)
            require(digest(target) == entry['sha256'], 'Authorized cloud asset differs from audited source')
        assets = resolve_assets(declared['manifest'], declared['assets'], root)
        output = root / 'preview-output'
        report = render(declared['manifest'], assets, output,
                        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
        require(report['structural_pass'] and report['decoded_to_end'], 'Structural QC incomplete')
        require(report['output_sha256'] == digest(output / 'draft.mp4'), 'Output changed after QC')
        # Confirm destination exists and is a folder. Never create folders or change permissions.
        response = session.get(module.API + '/' + FOLDER_ID,
                               params={'fields': 'id,mimeType,permissions(type,role)'}, timeout=30)
        response.raise_for_status()
        metadata = response.json()
        require(metadata['mimeType'] == module.FOLDER, 'Destination is not an existing folder')
        require('permissions' in metadata and not any(p['type'] in ('anyone', 'domain')
                for p in metadata['permissions']), 'Destination privacy cannot be confirmed')
        for name in ('draft.mp4', 'qc.json', 'captions.ass'):
            source = output / name
            unique_name = f'99-云盘端到端8秒技术预览-非正式成片-{run_id}-' + name
            copy = root / unique_name
            shutil.copyfile(source, copy)
            identifier = create_only_upload(session, module, copy, FOLDER_ID)
            response = session.get(module.API + '/' + identifier,
                params={'fields': 'id,size,parents,md5Checksum'}, timeout=30)
            response.raise_for_status()
            uploaded = response.json()
            require(int(uploaded['size']) == copy.stat().st_size and FOLDER_ID in uploaded['parents'],
                    'Uploaded output metadata mismatch')
            require(uploaded.get('md5Checksum') == hashlib.md5(copy.read_bytes()).hexdigest(),
                    'Uploaded output checksum mismatch')
            print('Private project output:', f'https://drive.google.com/file/d/{identifier}/view')
    print('8-second technical preview and full decoding completed; voice/visual acceptance remains pending.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preflight', action='store_true')
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    try:
        require(args.preflight != args.execute, 'Choose exactly one operation')
        preflight() if args.preflight else execute()
    except Exception:
        raise SystemExit('Technical preview stopped; no credentials, signed URLs, commands, or service responses logged.') from None


if __name__ == '__main__':
    main()
