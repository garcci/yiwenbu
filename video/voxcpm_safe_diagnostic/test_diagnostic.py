import ast,contextlib,importlib.util,io,json,os,subprocess,sys,types,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('zero_model_diag',P/'bootstrap.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
W=P/'workflow.voxcpm_safe_diagnostic_once.yml'
if not W.exists():W=Path(os.environ['GITHUB_WORKSPACE'])/'.github/workflows/voxcpm_safe_diagnostic_once.yml'
class Tests(unittest.TestCase):
    def test_no_model_download_loading_generation_or_upload_entry(self):
        tree=ast.parse((P/'bootstrap.py').read_text());calls=[];imports=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Call):calls.append(ast.unparse(n.func))
            elif isinstance(n,ast.Import):imports.extend(x.name for x in n.names)
            elif isinstance(n,ast.ImportFrom):imports.append(n.module)
        self.assertFalse(set(imports)&{'torch','torchaudio','voxcpm','transformers','huggingface_hub','synth_once'})
        self.assertFalse(any(any(k in c for k in ('generate','from_pretrained','snapshot_download','deliver','upload')) for c in calls))
        self.assertNotIn('upload-artifact',W.read_text());self.assertNotIn('workflow_dispatch',W.read_text())
    def test_environment_names_actual_workflow(self):
        tree=ast.parse((P/'bootstrap.py').read_text());needed={n.slice.value for n in ast.walk(tree) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and n.value.attr=='environ' and isinstance(n.slice,ast.Constant)}
        workflow=W.read_text()
        for key in needed-{'GITHUB_WORKSPACE','GITHUB_EVENT_PATH','RUNNER_TEMP'}:self.assertRegex(workflow,r'(?m)^\s+'+key+r':')
        self.assertIn('GDRIVE_FOLDER_ID: ${{ secrets.AUDITION_DRIVE_FOLDER_ID }}',workflow)
        self.assertIn('video/voxcpm_safe_diagnostic/execute_once.json',workflow)
        self.assertIn('discover -s video/voxcpm_safe_diagnostic -q',workflow)
        self.assertEqual(b.WORKFLOW,'.github/workflows/voxcpm_safe_diagnostic_once.yml')
    def test_draft_refused_and_explicit_no_model_contract_required(self):
        d=json.loads((P/'execute_once.example.json').read_text());now=datetime.now(timezone.utc)
        with self.assertRaises(ValueError):b.validate_trigger(d,now)
        d.update(zero_added_cost_confirmed=True,cost_evidence_utc=now.isoformat(),free_drive_storage_bytes_at_least=314572800)
        b.validate_trigger(d,now)
        for key in ('no_model_loading','no_audio_generation','install_packages'):
            bad=dict(d);bad[key]=False
            with self.assertRaises(ValueError):b.validate_trigger(bad,now)
    def test_unknown_private_exception_never_output(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            with self.assertRaises(b.Stopped):b.run_stage('PACKAGE_FETCH',lambda:(_ for _ in ()).throw(RuntimeError('PRIVATE_TOKEN_URL_DIALOGUE')))
        self.assertNotIn('PRIVATE_TOKEN_URL_DIALOGUE',stream.getvalue());rows=[json.loads(x) for x in stream.getvalue().splitlines()]
        self.assertEqual(rows[-1]['category'],'UNEXPECTED');self.assertEqual(rows[-1]['status'],'FAIL')
    def test_pip_uses_clean_env_and_only_enum_error(self):
        poison={k:'PRIVATE_SECRET_SENTINEL' for k in ('GDRIVE_CLIENT_SECRET','GH_TOKEN','OPENAI_API_KEY','HF_TOKEN','ACTIONS_RUNTIME_TOKEN','UNKNOWN_SECRET','HTTP_PROXY','PIP_INDEX_URL')}
        with patch.dict(os.environ,dict(poison,RUNNER_TEMP='/tmp')):
            env=b.safe_environment(Path('/tmp/empty-diagnostic-home'));self.assertNotIn('PRIVATE_SECRET_SENTINEL',env.values())
            def spawn(cmd,**kw):
                self.assertEqual(kw['env'],env);self.assertTrue(kw['close_fds']);self.assertEqual(kw['stdin'],subprocess.DEVNULL)
                return types.SimpleNamespace(returncode=1,stdout=b'',stderr=b'PRIVATE_SECRET_URL No matching distribution found')
            stream=io.StringIO()
            with patch.object(b.subprocess,'run',side_effect=spawn),contextlib.redirect_stdout(stream):
                with self.assertRaises(b.Stopped):b.run_stage('PIP_SDK',lambda:b.pip_install(['voxcpm==2.0.3'],env))
            self.assertNotIn('PRIVATE_SECRET',stream.getvalue());self.assertIn('PIP_WHEEL_UNAVAILABLE',stream.getvalue())
    def test_target_missing_write_capability_is_specific_fixed_error(self):
        meta={'mimeType':'application/vnd.google-apps.folder','trashed':False,'permissions':[{'type':'user'}]}
        with patch.object(b,'get_json',return_value=meta):
            with self.assertRaises(b.DiagnosticError) as e:b.target_check(None,'not_output')
        self.assertEqual(e.exception.category,'DRIVE_TARGET_NOT_WRITABLE')
    def test_complete_diagnostic_mock_has_only_two_installs_and_zero_models(self):
        class Session:
            def __enter__(self):return self
            def __exit__(self,*args):pass
        installs=[];stream=io.StringIO()
        environment={'GDRIVE_FOLDER_ID':'FAKE_PARENT_123','VOX_DESIGN_V2_PRIVATE_PACKAGE_ID':'FAKE_PACKAGE_123',
            'VOX_DESIGN_V2_PRIVATE_PACKAGE_SHA256':'a'*64,'RUNNER_TEMP':'/tmp','GDRIVE_CLIENT_SECRET':'PRIVATE_NOT_PASSED','GDRIVE_CLIENT_ID':'FAKE_CLIENT','GDRIVE_REFRESH_TOKEN':'FAKE_REFRESH'}
        with patch.dict(os.environ,environment),patch.dict(sys.modules,{'requests':types.SimpleNamespace(Session=Session)}),patch.object(b,'authenticate'),patch.object(b,'metadata'),patch.object(b,'fetch_package',return_value=b'fake'),patch.object(b,'unpack_verified',return_value=Path('/not-executed')),patch.object(b,'bind_manifest'),patch.object(b,'target_check'),patch.object(b,'resources'),patch.object(b,'pip_install',side_effect=lambda args,env:installs.append((args,env))),contextlib.redirect_stdout(stream):
            b.execute({'source_manifest_sha256':'a'*64})
        rows=[json.loads(x) for x in stream.getvalue().splitlines()]
        self.assertEqual([x['stage'] for x in rows if x['status']=='PASS'],['PRIVATE_ENV','DRIVE_AUTH','PACKAGE_METADATA','PACKAGE_FETCH','PACKAGE_VERIFY','MANIFEST_BINDING','DRIVE_TARGET','RESOURCE_BEFORE','PIP_CPU','PIP_SDK','RESOURCE_AFTER','COMPLETE'])
        self.assertEqual(len(installs),2)
        for args,env in installs:self.assertNotIn('PRIVATE_NOT_PASSED',env.values())
        self.assertNotIn('PRIVATE_NOT_PASSED',stream.getvalue())
    def test_pipeline_stops_at_failed_stage(self):
        stream=io.StringIO();calls=[]
        def operation():calls.append(1);raise b.DiagnosticError('NETWORK_TIMEOUT')
        with contextlib.redirect_stdout(stream),self.assertRaises(b.Stopped):b.run_stage('DRIVE_AUTH',operation)
        self.assertEqual(calls,[1]);self.assertEqual(json.loads(stream.getvalue().splitlines()[-1])['category'],'NETWORK_TIMEOUT')
