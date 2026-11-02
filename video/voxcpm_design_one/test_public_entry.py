import ast,importlib.util,json,re,unittest
from datetime import datetime,timezone
from pathlib import Path
P=Path(__file__).resolve().parent
W=P/'workflow.voxcpm_design_one_once.yml'
if not W.exists():
    import os
    W=Path(os.environ['GITHUB_WORKSPACE'])/'.github/workflows/voxcpm_design_one_once.yml'
spec=importlib.util.spec_from_file_location('safe_bootstrap',P/'bootstrap.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class SafetyTests(unittest.TestCase):
    def test_draft_refused(self):
        with self.assertRaises(ValueError):b.validate_trigger(json.loads((P/'execute_once.example.json').read_text()),datetime.now(timezone.utc))
    def test_actual_environment_names(self):
        tree=ast.parse((P/'bootstrap.py').read_text())
        needed={n.slice.value for n in ast.walk(tree) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and n.value.attr=='environ' and isinstance(n.slice,ast.Constant)}
        workflow=W.read_text()
        for name in needed-{'GITHUB_WORKSPACE','GITHUB_EVENT_PATH'}:self.assertRegex(workflow,r'(?m)^\s+'+name+r':')
        self.assertIn('GDRIVE_FOLDER_ID: ${{ secrets.AUDITION_DRIVE_FOLDER_ID }}',workflow)
    def test_no_public_content_or_artifacts(self):
        workflow=W.read_text()
        for token in ('upload-artifact','git push','voxcpm.yml','ARK_API_KEY','Result-','prompt_wav'):
            self.assertNotIn(token,workflow)
        self.assertIn('timeout-minutes: 55',workflow);self.assertIn('runs-on: ubuntu-24.04',workflow)
        self.assertIn('video/voxcpm_design_one/execute_once.json',workflow)
    def test_raw_failure_hidden(self):
        import contextlib,io
        from unittest.mock import patch
        s=io.StringIO()
        with patch('sys.argv',['bootstrap','--execute']),patch.object(b,'preflight',side_effect=RuntimeError('PRIVATE_URL_TOKEN')):
            with contextlib.redirect_stdout(s),self.assertRaises(SystemExit) as e:b.main()
        self.assertNotIn('PRIVATE_URL_TOKEN',str(e.exception));self.assertEqual(s.getvalue(),'')
