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

REPO='garcci/yiwenbu'
REF='refs/heads/claude/project-thread-l4wz3r'
AUTH='ep01-voxcpm2-safe-diagnostic-20261102-01'
SOURCE_AUTH='ep01-voxcpm2-design-one-20261102-v2-01'
WORKFLOW='.github/workflows/voxcpm_safe_diagnostic_once.yml'
HERE=Path(__file__).resolve().parent


def need(ok):
    if not ok:raise ValueError('Boundary validation failed')


def validate_trigger(d,now):
    need(set(d)=={'authorization_id','zero_added_cost_confirmed','cost_evidence_utc','compute_policy',
                  'free_drive_storage_bytes_at_least','no_model_loading','no_audio_generation','install_packages','source_manifest_sha256'})
    need(d['authorization_id']==AUTH and d['zero_added_cost_confirmed'] is True
         and d['no_model_loading'] is True and d['no_audio_generation'] is True and d['install_packages'] is True)
    need(d['compute_policy']=='public_standard_linux' and d['free_drive_storage_bytes_at_least']>=314572800)
    need(re.fullmatch('[0-9a-f]{64}',d['source_manifest_sha256']))
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
    need(scope['authorization_id']==SOURCE_AUTH)
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


# Diagnostic-only public protocol. Never print service responses, private paths or exception text.
import contextlib
import shutil
import time
STAGES={'PUBLIC_PREFLIGHT','PRIVATE_ENV','DRIVE_AUTH','PACKAGE_METADATA','PACKAGE_FETCH','PACKAGE_VERIFY',
        'MANIFEST_BINDING','DRIVE_TARGET','RESOURCE_BEFORE','PIP_CPU','PIP_SDK','RESOURCE_AFTER','COMPLETE'}
CATEGORIES={'NONE','PRIVATE_ENV_MISSING','BOUNDARY_REJECTED','HTTP_4XX','HTTP_5XX','NETWORK_TIMEOUT','NETWORK_ERROR',
            'INPUT_INVALID','DRIVE_NOT_PRIVATE','DRIVE_TARGET_NOT_WRITABLE','DRIVE_SPACE_LOW_OR_UNKNOWN',
            'MEMORY_BELOW_GATE','DISK_BELOW_GATE','CHILD_TIMEOUT','PIP_NONZERO','PIP_WHEEL_UNAVAILABLE',
            'PIP_DEPENDENCY_CONFLICT','PIP_STORAGE','PIP_NETWORK','UNEXPECTED'}


class DiagnosticError(Exception):
    def __init__(self,category,numbers=None):
        self.category=category if category in CATEGORIES else 'UNEXPECTED'
        self.numbers=numbers


class Stopped(Exception):pass


def require(ok,category='BOUNDARY_REJECTED'):
    if not ok:raise DiagnosticError(category)


def category(error):
    if isinstance(error,DiagnosticError):return error.category
    if isinstance(error,subprocess.TimeoutExpired):return 'CHILD_TIMEOUT'
    if isinstance(error,(json.JSONDecodeError,KeyError,zipfile.BadZipFile)):return 'INPUT_INVALID'
    import requests
    if isinstance(error,requests.Timeout):return 'NETWORK_TIMEOUT'
    if isinstance(error,requests.HTTPError):
        status=getattr(error.response,'status_code',0)
        return 'HTTP_5XX' if 500<=status<=599 else 'HTTP_4XX' if 400<=status<=499 else 'NETWORK_ERROR'
    if isinstance(error,requests.RequestException):return 'NETWORK_ERROR'
    if isinstance(error,ValueError):return 'BOUNDARY_REJECTED'
    return 'UNEXPECTED'


def emit(stage,status,error='NONE',seconds=0,numbers=None):
    require(stage in STAGES and error in CATEGORIES)
    require(status in ('START','PASS','FAIL'))
    output={'stage':stage,'status':status,'category':error,'seconds':round(seconds,3)}
    if numbers:
        require(set(numbers)<= {'returncode','memory_available_mib','disk_free_mib'})
        require(all(isinstance(v,int) for v in numbers.values()));output.update(numbers)
    print(json.dumps(output,sort_keys=True),flush=True)


def run_stage(name,operation):
    emit(name,'START');started=time.monotonic()
    try:
        result=operation()
    except Exception as error:
        emit(name,'FAIL',category(error),time.monotonic()-started,numbers=getattr(error,'numbers',None));raise Stopped() from None
    numbers=result if isinstance(result,dict) and set(result)<= {'returncode','memory_available_mib','disk_free_mib'} else None
    emit(name,'PASS',seconds=time.monotonic()-started,numbers=numbers)
    return result


def permissions(meta):
    ps=meta.get('permissions')
    require(isinstance(ps,list) and ps and all(p.get('type') in ('user','group') for p in ps),'DRIVE_NOT_PRIVATE')


def get_json(session,url,fields):
    response=session.get(url,params={'fields':fields},timeout=30,allow_redirects=False)
    response.raise_for_status();return response.json()


def authenticate(session):
    response=session.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['GDRIVE_CLIENT_ID'],
        'client_secret':os.environ['GDRIVE_CLIENT_SECRET'],'refresh_token':os.environ['GDRIVE_REFRESH_TOKEN'],
        'grant_type':'refresh_token'},timeout=30,allow_redirects=False)
    response.raise_for_status();session.headers['Authorization']='Bearer '+response.json()['access_token']


def metadata(session,parent,package):
    folder=get_json(session,'https://www.googleapis.com/drive/v3/files/'+parent,'mimeType,permissions(type,role)')
    permissions(folder);require(folder.get('mimeType')=='application/vnd.google-apps.folder')
    file=get_json(session,'https://www.googleapis.com/drive/v3/files/'+package,'mimeType,size,parents,permissions(type,role)')
    permissions(file);require(file.get('parents')==[parent] and int(file['size'])<=4*1024**2)


def fetch_package(session,identifier):
    response=session.get('https://www.googleapis.com/drive/v3/files/'+identifier,params={'alt':'media'},timeout=60,allow_redirects=False)
    response.raise_for_status();require(len(response.content)<=4*1024**2);return response.content


def bind_manifest(payload,trigger):
    manifest=json.loads((payload/'private_design/manifest.json').read_text())
    canonical=hashlib.sha256(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(manifest['authorization_id']==SOURCE_AUTH and canonical==trigger['source_manifest_sha256'])
    # No private source code is imported or executed in this diagnostic.


def target_check(session,parent):
    meta=get_json(session,'https://www.googleapis.com/drive/v3/files/'+parent,
                  'mimeType,trashed,capabilities(canAddChildren),permissions(type,role)')
    permissions(meta)
    require(meta.get('mimeType')=='application/vnd.google-apps.folder' and meta.get('trashed') is False
            and meta.get('capabilities',{}).get('canAddChildren') is True,'DRIVE_TARGET_NOT_WRITABLE')
    quota=get_json(session,'https://www.googleapis.com/drive/v3/about','storageQuota').get('storageQuota',{})
    try:available=int(quota['limit'])-int(quota['usage'])
    except (KeyError,ValueError,TypeError):raise DiagnosticError('DRIVE_SPACE_LOW_OR_UNKNOWN') from None
    require(available>=300*1024**2,'DRIVE_SPACE_LOW_OR_UNKNOWN')


def resources(stage):
    mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if ':' in x}
    memory=mem['MemAvailable'];disk=shutil.disk_usage(os.environ['RUNNER_TEMP']).free
    numbers={'memory_available_mib':memory//1024**2,'disk_free_mib':disk//1024**2}
    if memory<12*1024**3:raise DiagnosticError('MEMORY_BELOW_GATE',numbers)
    if disk<8*1024**3:raise DiagnosticError('DISK_BELOW_GATE',numbers)
    return numbers


SYSTEM_KEYS=('PATH','LANG','LC_ALL','TZ')
METADATA_KEYS=('GITHUB_REPOSITORY','GITHUB_REF','GITHUB_EVENT_NAME','GITHUB_RUN_ATTEMPT',
               'GITHUB_RUN_ID','GITHUB_ACTIONS','RUNNER_OS','RUNNER_TEMP')


def safe_environment(home):
    env={k:os.environ[k] for k in SYSTEM_KEYS+METADATA_KEYS if k in os.environ}
    env.update({'HOME':str(home),'TMPDIR':str(home),'TMP':str(home),'TEMP':str(home),
        'XDG_CONFIG_HOME':str(home/'config'),'XDG_CACHE_HOME':str(home/'cache'),'HF_HOME':str(home/'huggingface'),
        'HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','HF_HUB_DISABLE_TELEMETRY':'1','DO_NOT_TRACK':'1',
        'PIP_CONFIG_FILE':os.devnull,'PYTHONNOUSERSITE':'1'})
    return env


def pip_install(args,env):
    result=subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir']+args,
        env=env,cwd=os.environ['RUNNER_TEMP'],stdin=subprocess.DEVNULL,close_fds=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=6*60)
    if result.returncode:
        # Classification only: never log an original line or exception message.
        body=(result.stdout+result.stderr).decode('utf-8','replace')
        code='PIP_NONZERO'
        for marker,value in (('No matching distribution found','PIP_WHEEL_UNAVAILABLE'),
                             ('ResolutionImpossible','PIP_DEPENDENCY_CONFLICT'),
                             ('No space left on device','PIP_STORAGE'),
                             ('ReadTimeoutError','PIP_NETWORK'),('CERTIFICATE_VERIFY_FAILED','PIP_NETWORK')):
            if marker in body:code=value;break
        raise DiagnosticError(code,{'returncode':int(result.returncode)})
    return {'returncode':0}


def private_environment():
    names=('GDRIVE_FOLDER_ID','VOX_DESIGN_V2_PRIVATE_PACKAGE_ID','VOX_DESIGN_V2_PRIVATE_PACKAGE_SHA256',
           'GDRIVE_CLIENT_ID','GDRIVE_CLIENT_SECRET','GDRIVE_REFRESH_TOKEN')
    require(all(os.environ.get(k) for k in names),'PRIVATE_ENV_MISSING')
    parent=os.environ['GDRIVE_FOLDER_ID'];package=os.environ['VOX_DESIGN_V2_PRIVATE_PACKAGE_ID']
    expected=os.environ['VOX_DESIGN_V2_PRIVATE_PACKAGE_SHA256']
    require(re.fullmatch('[A-Za-z0-9_-]{10,200}',parent) and re.fullmatch('[A-Za-z0-9_-]{10,200}',package)
            and re.fullmatch('[0-9a-f]{64}',expected),'PRIVATE_ENV_MISSING')
    return parent,package,expected


def execute(trigger):
    import requests
    parent,package,expected=run_stage('PRIVATE_ENV',private_environment)
    with requests.Session() as session:
        run_stage('DRIVE_AUTH',lambda:authenticate(session))
        run_stage('PACKAGE_METADATA',lambda:metadata(session,parent,package))
        raw=run_stage('PACKAGE_FETCH',lambda:fetch_package(session,package))
        with tempfile.TemporaryDirectory(prefix='private-zero-model-probe-',dir=os.environ['RUNNER_TEMP']) as directory:
            payload=run_stage('PACKAGE_VERIFY',lambda:unpack_verified(raw,expected,Path(directory)/'payload'))
            run_stage('MANIFEST_BINDING',lambda:bind_manifest(payload,trigger))
        run_stage('DRIVE_TARGET',lambda:target_check(session,parent))
    run_stage('RESOURCE_BEFORE',lambda:resources('RESOURCE_BEFORE'))
    with tempfile.TemporaryDirectory(prefix='private-zero-model-home-',dir=os.environ['RUNNER_TEMP']) as directory:
        env=safe_environment(Path(directory))
        run_stage('PIP_CPU',lambda:pip_install(['--index-url','https://download.pytorch.org/whl/cpu','torch==2.8.0','torchaudio==2.8.0'],env))
        run_stage('PIP_SDK',lambda:pip_install(['voxcpm==2.0.3','torchcodec==0.7','requests','soundfile'],env))
    run_stage('RESOURCE_AFTER',lambda:resources('RESOURCE_AFTER'))
    emit('COMPLETE','PASS')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true',required=True);parser.parse_args()
    try:
        trigger=run_stage('PUBLIC_PREFLIGHT',preflight);execute(trigger)
    except Stopped:raise SystemExit(1) from None
    except Exception:
        emit('PUBLIC_PREFLIGHT','FAIL','UNEXPECTED');raise SystemExit(1) from None


if __name__=='__main__':main()
