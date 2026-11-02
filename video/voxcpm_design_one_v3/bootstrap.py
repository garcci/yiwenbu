#!/usr/bin/env python3
"""Public-safe launcher. All private production inputs stay in a hash-pinned private Drive package."""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
import safe_status as status

REPO='garcci/yiwenbu'
REF='refs/heads/claude/project-thread-l4wz3r'
AUTH='ep01-voxcpm2-design-one-20261102-v3-01'
WORKFLOW='.github/workflows/voxcpm_design_one_v3_once.yml'
HERE=Path(__file__).resolve().parent


def need(ok):
    if not ok:raise ValueError('Boundary validation failed')


def validate_trigger(d,now):
    need(set(d)=={'authorization_id','zero_added_cost_confirmed','cost_evidence_utc','compute_policy',
                  'free_drive_storage_bytes_at_least','upload_to_existing_private_drive','manifest_sha256'})
    need(d['authorization_id']==AUTH and d['zero_added_cost_confirmed'] is True
         and d['upload_to_existing_private_drive'] is True)
    need(d['compute_policy']=='public_standard_linux' and d['free_drive_storage_bytes_at_least']>=314572800)
    need(re.fullmatch('[0-9a-f]{64}',d['manifest_sha256']))
    t=datetime.fromisoformat(d['cost_evidence_utc'].replace('Z','+00:00'))
    need(t.tzinfo is not None and 0<=(now-t).total_seconds()<=3600)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def private(meta):
    permissions=meta.get('permissions')
    need(isinstance(permissions,list) and permissions and all(p.get('type') in ('user','group') for p in permissions))


def unpack_verified(raw,expected,destination):
    need(re.fullmatch('[0-9a-f]{64}',expected) and hashlib.sha256(raw).hexdigest()==expected)
    need(not destination.exists());destination.mkdir()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist();need(0<len(infos)<=256 and sum(i.file_size for i in infos)<=10*1024**2)
        names=set()
        for i in infos:
            p=PurePosixPath(i.filename);mode=i.external_attr>>16
            need(not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and
                 str(p) not in names and not stat.S_ISLNK(mode) and not i.is_dir())
            need(i.compress_size>0 and i.file_size/i.compress_size<200)
            names.add(str(p))
        for i in infos:
            target=destination/PurePosixPath(i.filename);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:f.write(z.read(i))
    scope=json.loads((destination/'private-source-scope.json').read_text())
    need(scope['authorization_id']==AUTH)
    for relative,expected_hash in scope['sha256'].items():
        p=PurePosixPath(relative);need(not p.is_absolute() and '..' not in p.parts)
        target=destination/p;need(target.is_file() and not target.is_symlink() and sha(target)==expected_hash)
    return destination


def preflight():
    need(os.getenv('GITHUB_REPOSITORY')==REPO and os.getenv('GITHUB_REF')==REF and
         os.getenv('GITHUB_EVENT_NAME')=='push' and os.getenv('GITHUB_RUN_ATTEMPT')=='1')
    run=os.getenv('GITHUB_RUN_ID','');need(run.isdigit())
    trigger=json.loads((HERE/'execute_once.json').read_text());validate_trigger(trigger,datetime.now(timezone.utc))
    scope=json.loads((HERE/'public_scope.frozen.json').read_text())
    root=Path(os.environ['GITHUB_WORKSPACE'])
    for name,digest in scope['sha256'].items():need(sha(root/name)==digest)
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text());need(event['repository']['private'] is False)
    import requests
    headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
    r=requests.get('https://api.github.com/repos/'+REPO,headers=headers,timeout=30,allow_redirects=False)
    r.raise_for_status();need(r.json().get('private') is False and r.json().get('full_name')==REPO)
    r=requests.get('https://api.github.com/repos/'+REPO+'/actions/workflows/'+Path(WORKFLOW).name+'/runs',
                   params={'per_page':100},headers=headers,timeout=30,allow_redirects=False)
    r.raise_for_status();history=r.json();need(history.get('total_count')==1 and len(history.get('workflow_runs',[]))==1)
    current=history['workflow_runs'][0]
    need(str(current['id'])==run and current.get('head_sha')==os.getenv('GITHUB_SHA')
         and current.get('path')==WORKFLOW and current.get('event')=='push')
    return trigger


def execute(trigger):
    import requests
    package_id=os.environ['VOX_DESIGN_V3_PRIVATE_PACKAGE_ID'];expected=os.environ['VOX_DESIGN_V3_PRIVATE_PACKAGE_SHA256']
    parent=os.environ['GDRIVE_FOLDER_ID']
    need(re.fullmatch('[A-Za-z0-9_-]{10,200}',package_id) and re.fullmatch('[A-Za-z0-9_-]{10,200}',parent))
    with requests.Session() as session:
        def authenticate():
            r=session.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['GDRIVE_CLIENT_ID'],
              'client_secret':os.environ['GDRIVE_CLIENT_SECRET'],'refresh_token':os.environ['GDRIVE_REFRESH_TOKEN'],
              'grant_type':'refresh_token'},timeout=30,allow_redirects=False)
            r.raise_for_status();session.headers['Authorization']='Bearer '+r.json()['access_token']
        status.stage('PACKAGE_AUTH',authenticate)
        def metadata():
            for identifier in (parent,package_id):
                r=session.get('https://www.googleapis.com/drive/v3/files/'+identifier,
                  params={'fields':'id,mimeType,size,parents,permissions(type,role)'},timeout=30,allow_redirects=False)
                r.raise_for_status();meta=r.json();private(meta)
                if identifier==parent:need(meta.get('mimeType')=='application/vnd.google-apps.folder')
                else:need(meta.get('parents')==[parent] and int(meta['size'])<=4*1024**2)
        status.stage('PACKAGE_METADATA',metadata)
        def fetch():
            r=session.get('https://www.googleapis.com/drive/v3/files/'+package_id,params={'alt':'media'},timeout=60,allow_redirects=False)
            r.raise_for_status();need(len(r.content)<=4*1024**2);return r.content
        raw=status.stage('PACKAGE_FETCH',fetch)
    work=Path(tempfile.mkdtemp(prefix='private-design-v3-input-',dir=os.environ.get('RUNNER_TEMP')))
    payload=status.stage('PACKAGE_VERIFY',lambda:unpack_verified(raw,expected,work/'payload'))
    marker=payload/'private_design/execute_request.json'
    with marker.open('x') as f:json.dump(trigger,f)
    status.stage('PRIVATE_START',lambda:run_private_worker(payload))


def run_private_worker(payload):
    try:
        result=subprocess.run([sys.executable,str(payload/'private_design/cloud_adapter.py')],cwd=payload,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=48*60)
    except subprocess.TimeoutExpired as error:
        status.replay_partial(error.stdout)
        raise status.Failure('CHILD_TIMEOUT') from None
    rows=status.replay(result.stdout.decode('utf-8','replace'))
    if result.returncode:raise status.Failure('CHILD_NONZERO',{'returncode':int(result.returncode)})
    if not rows or rows[-1]['stage']!='COMPLETE' or rows[-1]['status']!='PASS':raise status.Failure('INPUT_INVALID')


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--preflight',action='store_true');g.add_argument('--execute',action='store_true');a=p.parse_args()
    try:
        trigger=status.stage('PUBLIC_PREFLIGHT',preflight)
        if a.execute:execute(trigger)
    except status.Stop:raise SystemExit(1) from None
    except Exception:
        status.emit('PUBLIC_PREFLIGHT','FAIL','UNEXPECTED');raise SystemExit(1) from None


if __name__=='__main__':main()
