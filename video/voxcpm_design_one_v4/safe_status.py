"""Strict safe telemetry: fixed enums and bounded numeric values; never arbitrary strings."""
import json,math,time
STAGES={'PUBLIC_PREFLIGHT','PACKAGE_AUTH','PACKAGE_METADATA','PACKAGE_FETCH','PACKAGE_VERIFY',
 'PRIVATE_START','PRIVATE_BUDGET','DRIVE_AUTH_PRECHECK','DRIVE_AUTH_PREMODEL','DRIVE_AUTH_PREUPLOAD','DRIVE_PRECHECK','PIP_CPU','PIP_SDK','DRIVE_PREMODEL',
 'MODEL_PROCESS','MODEL_BUDGET','MODEL_RESOURCE','DOWNLOAD_SDK_IMPORT','MODEL_DOWNLOAD',
 'MODEL_IMPORT','MODEL_LOAD','MODEL_GENERATE','MODEL_OUTPUT','DRIVE_PREUPLOAD',
 'UPLOAD_AUDIO','UPLOAD_RECEIPT','COMPLETE'}
CATEGORIES={'NONE','BOUNDARY_REJECTED','NETWORK_TIMEOUT','NETWORK_ERROR','HTTP_4XX','HTTP_5XX',
 'CHILD_TIMEOUT','CHILD_NONZERO','IMPORT_FAILED','INPUT_INVALID','RESOURCE_BELOW_GATE',
 'MODEL_MEMORY_ERROR','OUTPUT_REJECTED','UPLOAD_VERIFY_FAILED','PIP_NONZERO',
 'PIP_WHEEL_UNAVAILABLE','PIP_DEPENDENCY_CONFLICT','PIP_STORAGE','PIP_NETWORK','UNEXPECTED',
 'PY_UNBOUND_LOCAL','PY_NAME_ERROR','PY_ATTRIBUTE_ERROR','PY_TYPE_ERROR','PY_ASSERTION_ERROR',
 'PY_NOT_IMPLEMENTED','PY_GENERATOR_EXHAUSTED','PY_RUNTIME_ERROR','DISK_FULL','FILESYSTEM_PERMISSION','FILESYSTEM_NOT_FOUND'}
NUMBERS={'returncode','memory_available_mib','disk_free_mib'}


class Stop(Exception):pass


class Failure(Exception):
    def __init__(self,category,numbers=None):
        self.category=category if category in CATEGORIES else 'UNEXPECTED';self.numbers=numbers


def validate(row):
    if not isinstance(row,dict) or not {'stage','status','category','seconds'}<=set(row) or set(row)-({'stage','status','category','seconds'}|NUMBERS):return False
    if not all(type(row[k]) is str for k in ('stage','status','category')):return False
    if row['stage'] not in STAGES or row['status'] not in ('START','PASS','FAIL') or row['category'] not in CATEGORIES:return False
    seconds=row['seconds']
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<=seconds<=86400:return False
    return all(type(row[k]) is int and -4096<=row[k]<=2**40 for k in set(row)&NUMBERS)


def emit(stage,status,category='NONE',seconds=0,numbers=None,sink=None):
    row={'stage':stage,'status':status,'category':category,'seconds':round(seconds,3)}
    if numbers:row.update(numbers)
    if not validate(row):raise Stop() from None
    line=json.dumps(row,sort_keys=True)
    if sink is None:print(line,flush=True)
    else:
        with sink.open('a',encoding='utf-8') as output:output.write(line+'\n')


def classify(error):
    if isinstance(error,Failure):return error.category
    import subprocess
    if isinstance(error,subprocess.TimeoutExpired):return 'CHILD_TIMEOUT'
    if isinstance(error,ImportError):return 'IMPORT_FAILED'
    if isinstance(error,(KeyError,json.JSONDecodeError)):return 'INPUT_INVALID'
    if isinstance(error,MemoryError):return 'MODEL_MEMORY_ERROR'
    # Inspect known signatures privately; never emit the original message.
    if isinstance(error,RuntimeError) and 'out of memory' in str(error).lower():return 'MODEL_MEMORY_ERROR'
    # Only fixed categories derived from exception classes/errno; never class names or messages.
    if isinstance(error,UnboundLocalError):return 'PY_UNBOUND_LOCAL'
    if isinstance(error,NameError):return 'PY_NAME_ERROR'
    if isinstance(error,AttributeError):return 'PY_ATTRIBUTE_ERROR'
    if isinstance(error,TypeError):return 'PY_TYPE_ERROR'
    if isinstance(error,AssertionError):return 'PY_ASSERTION_ERROR'
    if isinstance(error,NotImplementedError):return 'PY_NOT_IMPLEMENTED'
    if isinstance(error,StopIteration) or isinstance(getattr(error,'__cause__',None),StopIteration):return 'PY_GENERATOR_EXHAUSTED'
    if isinstance(error,RuntimeError):return 'PY_RUNTIME_ERROR'
    if isinstance(error,PermissionError):return 'FILESYSTEM_PERMISSION'
    if isinstance(error,FileNotFoundError):return 'FILESYSTEM_NOT_FOUND'
    import errno
    if isinstance(error,OSError) and error.errno==errno.ENOSPC:return 'DISK_FULL'

    try:
        import requests
        if isinstance(error,requests.Timeout):return 'NETWORK_TIMEOUT'
        if isinstance(error,requests.HTTPError):
            status=getattr(error.response,'status_code',0)
            return 'HTTP_5XX' if 500<=status<=599 else 'HTTP_4XX' if 400<=status<=499 else 'NETWORK_ERROR'
        if isinstance(error,requests.RequestException):return 'NETWORK_ERROR'
    except ImportError:pass
    if isinstance(error,ValueError):return 'BOUNDARY_REJECTED'
    return 'UNEXPECTED'


def stage(name,operation,sink=None):
    emit(name,'START',sink=sink);started=time.monotonic()
    try:result=operation()
    except Exception as error:
        emit(name,'FAIL',classify(error),time.monotonic()-started,getattr(error,'numbers',None),sink)
        raise Stop() from None
    numbers=result if isinstance(result,dict) and set(result)<=NUMBERS else None
    emit(name,'PASS',seconds=time.monotonic()-started,numbers=numbers,sink=sink)
    return result


def replay(raw):
    if len(raw.encode('utf-8'))>65536:raise Stop() from None
    accepted=[]
    for line in raw.splitlines():
        try:row=json.loads(line)
        except (ValueError,TypeError):continue
        if validate(row):
            print(json.dumps(row,sort_keys=True),flush=True);accepted.append(row)
    return accepted


def replay_partial(raw):
    # TimeoutExpired may expose bytes or text. Bound before decoding; never read stderr.
    if isinstance(raw,str):raw=raw.encode('utf-8')
    if not isinstance(raw,bytes):return []
    return replay(raw[:65536].decode('utf-8','ignore'))
