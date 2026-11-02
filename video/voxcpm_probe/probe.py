"""Cloud-only diagnostic: no model downloads, inference, uploads or secret logging."""
import os, re, shutil, subprocess, sys
from pathlib import Path
import requests


def isolated_environment(source):
    allowed=('PATH','HOME','LANG','LC_ALL','TMPDIR','RUNNER_TEMP','LD_LIBRARY_PATH','SSL_CERT_FILE')
    return {k:source[k] for k in allowed if k in source}


def check(name, fn):
    try:
        if not fn(): raise ValueError()
        print(name + ': PASS', flush=True)
    except Exception:
        print(name + ': FAIL', flush=True)
        raise SystemExit(1) from None


def main():
    parent=os.environ['GDRIVE_FOLDER_ID']
    check('configuration',lambda:bool(re.fullmatch('[A-Za-z0-9_-]{10,200}',parent)))
    session=requests.Session()
    def auth():
        r=session.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['GDRIVE_CLIENT_ID'],'client_secret':os.environ['GDRIVE_CLIENT_SECRET'],'refresh_token':os.environ['GDRIVE_REFRESH_TOKEN'],'grant_type':'refresh_token'},timeout=30,allow_redirects=False);r.raise_for_status()
        session.headers['Authorization']='Bearer '+r.json()['access_token'];return True
    check('drive_authentication',auth)
    def folder():
        r=session.get('https://www.googleapis.com/drive/v3/files/'+parent,params={'fields':'mimeType,trashed,capabilities(canAddChildren),permissions(type,role)'},timeout=30,allow_redirects=False);r.raise_for_status();m=r.json();p=m.get('permissions')
        return m.get('mimeType')=='application/vnd.google-apps.folder' and m.get('trashed') is False and m.get('capabilities',{}).get('canAddChildren') is True and isinstance(p,list) and bool(p) and all(x.get('type') in ('user','group') for x in p)
    check('drive_target',folder)
    def quota():
        r=session.get('https://www.googleapis.com/drive/v3/about',params={'fields':'storageQuota'},timeout=30,allow_redirects=False);r.raise_for_status();q=r.json()['storageQuota'];return int(q['limit'])-int(q['usage'])>=300*1024**2
    check('drive_capacity',quota)
    # Installed packages and their subprocesses must not inherit Drive credentials.
    clean_env=isolated_environment(os.environ)
    base=[sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir']
    def install(args):
        r=subprocess.run(base+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=360,env=clean_env)
        if r.returncode:
            err=r.stderr.lower()
            for needle,label in ((b'no space left','disk'),(b'resolutionimpossible','dependency'),(b'no matching distribution','package'),(b'timed out','network')):
                if needle in err:print('install_category: '+label,flush=True);break
            return False
        return True
    check('cpu_torch_install',lambda:install(['--index-url','https://download.pytorch.org/whl/cpu','torch==2.8.0','torchaudio==2.8.0']))
    check('sdk_install',lambda:install(['voxcpm==2.0.3','torchcodec==0.7','requests','soundfile']))
    def resources():
        m={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if ':' in x}
        return m['MemAvailable']>=12*1024**3 and shutil.disk_usage(os.environ['RUNNER_TEMP']).free>=8*1024**3
    check('resource_gate',resources)
    def sdk():
        env=dict(clean_env,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',NO_PROXY='')
        code="import inspect,importlib.metadata;from voxcpm import VoxCPM;assert importlib.metadata.version('voxcpm')=='2.0.3';assert 'seed' not in inspect.signature(VoxCPM._generate).parameters"
        return subprocess.run([sys.executable,'-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90).returncode==0
    check('offline_sdk_import',sdk)


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('diagnostic: FAIL') from None
