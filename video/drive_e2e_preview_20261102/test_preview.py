import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prepare_bundle import bundle, encoded_bundle, IMAGE_ID, AUDIO_ID
from run_preview import check_marker, EXPECTED_BUNDLE_SHA, preflight, BRANCH, REPOSITORY, create_only_upload
from render import asset_references, plan


def marker():
    return {'authorization': 'drive-e2e-technical-preview-20261102-once',
            'bundle_drive_id': 'TEST_ONLY_BUNDLE_ID_12345', 'bundle_sha256': EXPECTED_BUNDLE_SHA,
            'zero_added_cost_confirmed': True}


class PreviewTests(unittest.TestCase):
    def test_frozen_two_assets_eight_seconds(self):
        b = bundle()
        self.assertEqual((HERE / 'input-bundle.json').read_bytes(), encoded_bundle())
        self.assertEqual(hashlib.sha256(encoded_bundle()).hexdigest(), EXPECTED_BUNDLE_SHA)
        self.assertEqual(set(e['drive_file_id'] for e in b['assets'].values()), {IMAGE_ID, AUDIO_ID})
        self.assertEqual(len(asset_references(b['manifest'])), 2)
        self.assertEqual(plan(b['manifest'])['duration'], 8)
        self.assertEqual(b['manifest']['audio'][0]['duration'], 7.872)
        self.assertTrue(b['assets']['authorized-plan-paragraph.mp3']['authorized_for_this_draft'])
        self.assertIn('非正式成片', b['manifest']['captions'][0]['text'])
        self.assertIn('AI', b['manifest']['badge'])

    def test_marker_rejects_extra_resources_hash_drift_and_missing_cost_confirmation(self):
        check_marker(marker())
        for key, value in [('bundle_sha256', '0' * 64), ('zero_added_cost_confirmed', False),
                           ('authorization', 'wrong'), ('bundle_drive_id', 'https://invalid.example/')]:
            candidate = marker(); candidate[key] = value
            with self.assertRaises(ValueError):
                check_marker(candidate)
        candidate = marker(); candidate['extra_audio'] = 'forbidden'
        with self.assertRaises(ValueError):
            check_marker(candidate)

    def test_rerun_rejected_before_any_network(self):
        env = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': BRANCH, 'GITHUB_REPOSITORY': REPOSITORY,
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}
        with patch.dict('os.environ', env, clear=True), patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'Reruns forbidden'):
                preflight()
            network.assert_not_called()

    def test_previous_run_consumes_one_time_authorization(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        env = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': BRANCH, 'GITHUB_REPOSITORY': REPOSITORY,
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GH_TOKEN': 'synthetic-test-token'}
        with patch.dict('os.environ', env, clear=True), patch('pathlib.Path.read_text', return_value=json.dumps(marker())), \
             patch('urllib.request.urlopen', return_value=response), \
             patch('json.load', return_value={'total_count': 2, 'workflow_runs': [{'id': 123}, {'id': 122}]}):
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                preflight()

    def test_racing_same_name_create_never_updates_existing_file(self):
        root = Path(tempfile.mkdtemp(prefix='drive-create-race-test-'))
        source = root / 'synthetic-output.mp4'
        source.write_bytes(b'synthetic upload bytes only')
        module = unittest.mock.MagicMock()
        module.UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
        # Another writer inserts this name after our initial check. A second
        # lookup would now find the competing object; it must not be used.
        module._find.side_effect = [None, 'COMPETING_EXISTING_FILE_ID']
        session = unittest.mock.MagicMock()
        session.headers = {'Authorization': 'Bearer synthetic-test-token'}
        session.post.return_value.headers = {'Location': module.UPLOAD + '?uploadType=resumable&upload_id=synthetic'}
        session.put.return_value.json.return_value = {'id': 'NEW_CREATED_FILE_ID_12345'}
        identifier = create_only_upload(session, module, source, 'PARENT_FOLDER_ID_12345')
        self.assertEqual(identifier, 'NEW_CREATED_FILE_ID_12345')
        module._find.assert_called_once()
        module._put_once.assert_not_called()
        session.patch.assert_not_called()
        session.post.assert_called_once()
        self.assertEqual(session.post.call_args.args, (module.UPLOAD,))
        self.assertEqual(session.post.call_args.kwargs['json'],
                         {'name': source.name, 'parents': ['PARENT_FOLDER_ID_12345']})
        self.assertNotIn('COMPETING_EXISTING_FILE_ID', session.put.call_args.args[0])
        session.put.assert_called_once()

    def test_existing_name_stops_before_upload_or_patch(self):
        module = unittest.mock.MagicMock()
        module._find.return_value = 'EXISTING_FILE_ID_12345'
        session = unittest.mock.MagicMock()
        session.headers = {}
        with self.assertRaisesRegex(ValueError, 'overwrite forbidden'):
            create_only_upload(session, module, Path('not-opened.mp4'), 'PARENT_FOLDER_ID_12345')
        session.post.assert_not_called()
        session.put.assert_not_called()
        session.patch.assert_not_called()
        module._put_once.assert_not_called()

    def test_workflow_exact_branch_path_no_generation_or_deletion(self):
        workflow = (HERE.parents[1] / '.github/workflows/ep01_drive_e2e_once_20261102.yml').read_text()
        self.assertIn('branches: [claude/project-thread-l4wz3r]', workflow)
        self.assertIn('paths: ["video/drive_e2e_preview_20261102/execute-once.json"]', workflow)
        self.assertNotIn('workflow_dispatch', workflow)
        self.assertNotIn('ARK_API_KEY', workflow)
        self.assertNotIn('upload-artifact', workflow)
        self.assertNotIn('rm ', workflow)
        self.assertNotIn('schedule:', workflow)
        code = (HERE / 'run_preview.py').read_text()
        for blocked in ('shutil.rmtree', '.unlink(', 'os.remove(', 'openspeech', 'api.openai.com'):
            self.assertNotIn(blocked, code)


if __name__ == '__main__':
    unittest.main()
