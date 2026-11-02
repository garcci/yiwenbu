"""Read-only fixed-label diagnostics; never calls TTS or prints private values."""
import hashlib, io, json, os, re, stat, zipfile
from pathlib import PurePosixPath
import requests


def check(label, operation):
    try:
        result = operation()
        if not result:
            raise ValueError()
        print(label + ': PASS', flush=True)
        return result
    except Exception:
        print(label + ': FAIL', flush=True)
        raise SystemExit(1) from None


def main():
    package = os.environ['AUDITION_PRIVATE_PACKAGE_ID']
    parent = os.environ['GDRIVE_FOLDER_ID']
    expected = os.environ['AUDITION_PRIVATE_PACKAGE_SHA256']
    check('configuration', lambda: all(re.fullmatch('[A-Za-z0-9_-]{10,200}', x) for x in (package, parent)) and re.fullmatch('[0-9a-f]{64}', expected))
    session = requests.Session()
    def authorize():
        r = session.post('https://oauth2.googleapis.com/token', data={'client_id':os.environ['GDRIVE_CLIENT_ID'], 'client_secret':os.environ['GDRIVE_CLIENT_SECRET'], 'refresh_token':os.environ['GDRIVE_REFRESH_TOKEN'], 'grant_type':'refresh_token'}, timeout=30, allow_redirects=False)
        r.raise_for_status()
        session.headers['Authorization']='Bearer '+r.json()['access_token']
        return True
    check('drive_authentication', authorize)
    def metadata(identifier):
        r=session.get('https://www.googleapis.com/drive/v3/files/'+identifier, params={'fields':'id,mimeType,size,parents,permissions(type,role)'}, timeout=30, allow_redirects=False)
        r.raise_for_status(); return r.json()
    def is_private(x):
        p=x.get('permissions'); return isinstance(p,list) and bool(p) and all(v.get('type') in ('user','group') for v in p)
    check('parent_permissions', lambda: (lambda x: x.get('mimeType')=='application/vnd.google-apps.folder' and is_private(x))(metadata(parent)))
    package_meta=check('package_readable', lambda: metadata(package))
    check('package_private', lambda: is_private(package_meta))
    check('package_size', lambda: int(package_meta['size'])<=4*1024**2)
    check('package_parent_matches', lambda: package_meta.get('parents')==[parent])
    def read_package():
        r=session.get('https://www.googleapis.com/drive/v3/files/'+package,params={'alt':'media'},timeout=60,allow_redirects=False)
        r.raise_for_status(); raw=r.content
        return raw if len(raw)<=4*1024**2 and hashlib.sha256(raw).hexdigest()==expected else None
    raw=check('package_hash',read_package)
    def inspect():
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos=z.infolist(); names=set()
            if not 0<len(infos)<=256 or sum(i.file_size for i in infos)>10*1024**2:return False
            for i in infos:
                p=PurePosixPath(i.filename); mode=i.external_attr>>16
                if p.is_absolute() or '..' in p.parts or '\\' in i.filename or str(p) in names or stat.S_ISLNK(mode) or i.is_dir() or i.compress_size<=0 or i.file_size/i.compress_size>=200:return False
                names.add(str(p))
            scope=json.loads(z.read('private-source-scope.json'))
            if scope['authorization_id']!='ep01-qinghe-voice-audition-20261102-01':return False
            for path,digest in scope['sha256'].items():
                if hashlib.sha256(z.read(path)).hexdigest()!=digest:return False
            source=z.read('video/role_tts_plan/runner.py').decode()
            match=re.search(r'^DRIVE_PARENT\s*=\s*[\'"]([^\'"]+)[\'"]',source,re.M)
            return bool(match and match.group(1)==parent)
    check('package_integrity_and_destination', inspect)


if __name__=='__main__':
    try: main()
    except Exception: raise SystemExit('diagnostic: FAIL') from None
