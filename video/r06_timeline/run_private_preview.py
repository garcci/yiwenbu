#!/usr/bin/env python3
"""One fixed-repository push-only private r06 draft. No synthesis endpoints or implicit retries."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build
import apply_asr

REPOSITORY = 'garcci/yiwenbu'
BRANCH = 'refs/heads/claude/project-thread-l4wz3r'
WORKFLOW = '.github/workflows/ep01_r06_private_preview_once.yml'
PARENT = '11uMWY64q_tLolJ210NmLhfqnkW1D5fBR'
AUTH = 'ep01-r06-private-preview-20261102-once'
CANDIDATE = HERE / 'frozen_candidates_20261102_v3/inputs.assets-candidate.json'


def need(value, message):
    if not value: raise ValueError(message)


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_trigger(trigger, now):
    need(set(trigger) == {'authorization_id', 'zero_added_cost_confirmed', 'cost_evidence_utc',
                          'actions_remaining_minutes_at_least', 'free_drive_storage_bytes_at_least',
                          'upload_to_existing_private_drive', 'alignment'}, 'Unexpected trigger fields')
    need(trigger['authorization_id'] == AUTH and trigger['zero_added_cost_confirmed'] is True and
         trigger['upload_to_existing_private_drive'] is True, 'Concrete zero-cost/private upload authorization missing')
    when = datetime.fromisoformat(trigger['cost_evidence_utc'].replace('Z', '+00:00'))
    need(when.tzinfo is not None and 0 <= (now - when).total_seconds() <= 3600, 'Cost evidence expired or future')
    need(trigger['actions_remaining_minutes_at_least'] >= 60 and
         trigger['free_drive_storage_bytes_at_least'] >= 314572800, 'Current free compute/storage evidence insufficient')
    alignment = trigger['alignment']
    if alignment is not None:
        need(set(alignment) == {'drive_file_id', 'sha256'}, 'Unexpected ASR reference fields')
        need(re.fullmatch(r'[A-Za-z0-9_-]{10,200}', alignment['drive_file_id']) and
             re.fullmatch(r'[0-9a-f]{64}', alignment['sha256']), 'Explicit actual ASR ID/hash required')


def private_permissions(data):
    permissions = data.get('permissions')
    need(isinstance(permissions, list) and bool(permissions), 'Private permissions unavailable')
    need(all(p.get('type') in ('user', 'group') for p in permissions), 'Public/domain/unknown sharing refused')


def preflight():
    need(os.getenv('GITHUB_REPOSITORY') == REPOSITORY and os.getenv('GITHUB_REF') == BRANCH and
         os.getenv('GITHUB_EVENT_NAME') == 'push' and os.getenv('GITHUB_RUN_ATTEMPT') == '1', 'Wrong GitHub execution scope')
    run_id = os.getenv('GITHUB_RUN_ID', ''); need(run_id.isdigit(), 'Current run identity missing')
    trigger_path = HERE / 'execute_once.json'; need(trigger_path.is_file(), 'Unique trigger absent')
    trigger = json.loads(trigger_path.read_text()); validate_trigger(trigger, datetime.now(timezone.utc))
    scope = json.loads((HERE / 'preview_scope.frozen.json').read_text())
    for relative, expected in scope['sha256'].items():
        need(sha(ROOT / relative) == expected, 'Reviewed source bytes changed')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    need(event.get('repository', {}).get('private') is True, 'Repository privacy unavailable or public')
    import requests
    token = os.getenv('GH_TOKEN'); need(token, 'Read-only Actions token missing')
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    # Require complete visible dedicated workflow history to contain this one run only.
    r = requests.get('https://api.github.com/repos/' + REPOSITORY + '/actions/workflows/' + Path(WORKFLOW).name + '/runs',
                     params={'per_page': 100}, headers=headers, timeout=30, allow_redirects=False)
    r.raise_for_status(); history = r.json()
    need(history.get('total_count') == 1 and len(history.get('workflow_runs', [])) == 1, 'Dedicated workflow has prior/unknown runs')
    current = history['workflow_runs'][0]
    need(str(current['id']) == run_id and current.get('head_sha') == os.getenv('GITHUB_SHA') and
         current.get('event') == 'push' and current.get('path') == WORKFLOW, 'Run/history identity mismatch')
    return trigger


def command(arguments):
    # Capture all subprocess output so service responses/paths are never forwarded to Actions logs.
    r = subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT, capture_output=True)
    need(r.returncode == 0, 'A declared pipeline stage failed; no retry/fallback')


def upload_private(output, extra, session, module):
    need(os.getenv('GDRIVE_FOLDER_ID') == PARENT, 'Unexpected Drive destination')
    def meta(identifier):
        r = session.get(module.API + '/' + identifier,
                        params={'fields': 'id,name,mimeType,parents,permissions(type,role),size,md5Checksum'},
                        timeout=30, allow_redirects=False); r.raise_for_status(); return r.json()
    parent = meta(PARENT); private_permissions(parent)
    need(parent.get('mimeType') == 'application/vnd.google-apps.folder', 'Target is not a folder')
    name = 'r06-private-preview-run-' + os.environ['GITHUB_RUN_ID'] + '-' + uuid.uuid4().hex[:8]
    r = session.post(module.API, params={'fields': 'id'}, json={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [PARENT]},
                     timeout=30, allow_redirects=False); r.raise_for_status(); folder = r.json()['id']
    fresh = meta(folder); private_permissions(fresh); need(fresh.get('parents') == [PARENT], 'Wrong created folder parent')
    report = json.loads((output / 'qc.json').read_text())
    need(report.get('structural_pass') is True and report.get('decoded_to_end') is True and
         sha(output / 'draft.mp4') == report['output_sha256'], 'No QC/hash passed rendered draft')
    files = [output / n for n in ('draft.mp4', 'qc.json', 'captions.ass')] + list(extra)
    need(sum(p.stat().st_size for p in files) <= 314572800, 'Actual upload exceeds declared free storage envelope')
    uploads = []
    for path in files:
        mime = 'video/mp4' if path.suffix == '.mp4' else ('application/json' if path.suffix == '.json' else 'text/plain')
        r = session.post(module.UPLOAD, params={'uploadType': 'resumable', 'fields': 'id'},
                         headers={'X-Upload-Content-Type': mime}, json={'name': path.name, 'parents': [folder]},
                         timeout=60, allow_redirects=False); r.raise_for_status()
        location = r.headers['Location']
        # Location is service-authenticated, never persisted, printed, or accepted from a file.
        need(location.startswith('https://www.googleapis.com/'), 'Unexpected upload transport')
        with path.open('rb') as f:
            done = session.put(location, headers={'Content-Type': mime}, data=f, timeout=900, allow_redirects=False)
        done.raise_for_status(); fid = done.json()['id']; actual = meta(fid); private_permissions(actual)
        need(actual.get('name') == path.name and actual.get('parents') == [folder] and
             int(actual['size']) == path.stat().st_size and
             actual.get('md5Checksum') == hashlib.md5(path.read_bytes()).hexdigest(), 'Uploaded file metadata/hash mismatch')
        uploads.append({'name': path.name, 'id': fid, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    result = {'folder_id': folder, 'files': uploads, 'human_review': 'pending', 'permissions_changed': False}
    (output / 'drive_delivery.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('Private Drive output: https://drive.google.com/drive/folders/' + folder)
    return result


def execute(trigger):
    import requests
    spec = importlib.util.spec_from_file_location('project_drive', ROOT / 'gdrive.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    need(module.enabled(), 'Existing Drive environment missing')
    # Verify private destination BEFORE any media fetch or render; no permission writes.
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + module._token()
        r = session.get(module.API + '/' + PARENT, params={'fields': 'permissions(type,role)'}, timeout=30, allow_redirects=False)
        r.raise_for_status(); private_permissions(r.json())
    work = Path(tempfile.mkdtemp(prefix='r06-private-preview-', dir=os.getenv('RUNNER_TEMP')))
    assets = work / 'input-assets'
    command([HERE/'fetch_api_batches.py', '--fetch-known-batches', '--destination', assets])
    command([HERE/'fetch_candidate_assets.py', '--fetch-candidates', '--inputs', CANDIDATE,
             '--asset-root', assets, '--output', work/'nonvoice.json'])
    command([HERE/'import_batches.py', '--inputs', work/'nonvoice.json', '--asset-root', assets,
             '--batch01', assets/'batch01', '--batch02', assets/'batch02', '--output', work/'measured.json'])
    measured = json.loads((work/'measured.json').read_text())
    # One short, low-level licensed cue only. No beat-wide automatic music expansion.
    measured['sound_events'].append({'id':'mother_memory_piano','asset_id':'M2','anchor':{'type':'beat_start','id':'S6B03'},
                                    'source_start':0,'duration':8,'volume':.03,'fade_in':1,'fade_out':2})
    input_path = work / 'ready-input.json'
    if trigger['alignment'] is not None:
        reference = trigger['alignment']
        with requests.Session() as session:
            session.headers['Authorization'] = 'Bearer ' + module._token()
            r = session.get(module.API + '/' + reference['drive_file_id'], params={'alt':'media'}, timeout=60, allow_redirects=False)
            r.raise_for_status(); raw = r.content
        need(len(raw) <= 5_000_000 and hashlib.sha256(raw).hexdigest() == reference['sha256'], 'ASR bytes/hash mismatch')
        alignment = json.loads(raw)
        need(alignment.get('complete_for_episode') is True and len(alignment.get('segments',[])) == 27,
             'ASR pilot/incomplete timestamps cannot calibrate an episode')
        need(all(x.get('auto_match') is True and not x.get('flags') for x in alignment['segments']), 'ASR mismatch/flags require manual correction')
        measured = apply_asr.apply(measured, alignment); mode = '--allow-unreviewed-asr'
    else:
        mode = '--allow-unaligned-draft'
    input_path.write_text(json.dumps(measured, ensure_ascii=False, indent=2))
    command([HERE/'build.py', '--inputs', input_path, '--output', work/'timeline', mode])
    command([ROOT/'video/ci_render/render.py','--manifest',work/'timeline/manifest.json','--asset-map',work/'timeline/asset-map.json',
             '--asset-root',assets,'--output-dir',work/'rendered'])
    extra = [work/'timeline'/n for n in ('build-report.json','manifest.json','asset-map.json','bundle.json','CREDITS.txt')]
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + module._token()
        upload_private(work/'rendered', extra, session, module)
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write('\nSubtitle mode: '+('UNALIGNED display-page draft; no precise sync claimed' if mode.endswith('unaligned-draft') else 'real ASR marks, human review pending')+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--preflight', action='store_true'); g.add_argument('--execute', action='store_true'); a = p.parse_args()
    try:
        trigger = preflight()
        if a.execute: execute(trigger)
        else: print('Fixed push scope, current run identity and explicit zero-cost/private-draft evidence validated. No Drive media read.')
    except Exception:
        raise SystemExit('Private r06 preview stopped; no retry/fallback, deletion, sharing changes or generation call. Service diagnostics withheld.') from None


if __name__ == '__main__': main()
