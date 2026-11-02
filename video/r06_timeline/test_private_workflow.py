"""Offline review tests. No GitHub/Drive/media requests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
import run_private_preview as runner

HERE = Path(__file__).resolve().parent


class WorkflowTests(unittest.TestCase):
    def valid_trigger(self):
        d = json.loads((HERE / 'execute_once.example.json').read_text())
        d.update(zero_added_cost_confirmed=True, cost_evidence_utc=datetime.now(timezone.utc).isoformat())
        return d

    def test_example_is_not_executable(self):
        with self.assertRaises(ValueError): runner.validate_trigger(json.loads((HERE/'execute_once.example.json').read_text()), datetime.now(timezone.utc))

    def test_cost_evidence_expiry_and_approval_scope(self):
        d = self.valid_trigger(); runner.validate_trigger(d, datetime.now(timezone.utc))
        d['cost_evidence_utc'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        with self.assertRaises(ValueError): runner.validate_trigger(d, datetime.now(timezone.utc))
        d = self.valid_trigger(); d['upload_to_existing_private_drive'] = False
        with self.assertRaises(ValueError): runner.validate_trigger(d, datetime.now(timezone.utc))

    def test_asr_reference_requires_real_hash(self):
        d = self.valid_trigger(); d['alignment'] = {'drive_file_id': 'alignment_file_12345', 'sha256':'a'*64}
        runner.validate_trigger(d, datetime.now(timezone.utc))
        d['alignment']['sha256'] = 'missing'
        with self.assertRaises(ValueError): runner.validate_trigger(d, datetime.now(timezone.utc))

    def test_public_or_unknown_permission_refused(self):
        for d in ({}, {'permissions':[]}, {'permissions':[{'type':'anyone'}]}, {'permissions':[{'type':'domain'}]}):
            with self.assertRaises(ValueError): runner.private_permissions(d)
        runner.private_permissions({'permissions':[{'type':'user','role':'owner'}]})

    def test_workflow_is_unique_push_only_and_does_not_exist_in_target(self):
        text = (HERE/'workflow.ep01_r06_private_preview_once.yml').read_text()
        self.assertIn('paths: ["video/r06_timeline/execute_once.json"]', text)
        self.assertIn('branches: [claude/project-thread-l4wz3r]', text)
        self.assertNotIn('workflow_dispatch', text)
        self.assertNotIn('schedule:', text)
        self.assertNotIn('ARK_API_KEY', text)
        self.assertNotIn('upload-artifact', text)

    def test_candidate_remains_unconfirmed_and_no_audio_duration_claim(self):
        data = json.loads(runner.CANDIDATE.read_text())
        nonvoice = [v for v in data['assets'].values() if v['kind']!='voice']
        self.assertEqual(len(nonvoice),35)
        self.assertTrue(all(v['confirmed'] is False for v in nonvoice))
        self.assertTrue(all(v.get('duration_seconds') is None for v in nonvoice if v['kind']!='image'))
        self.assertFalse(data['render_ready'])

    def test_v3_plot_cards_sound_slices_and_dependency_order(self):
        d = json.loads(runner.CANDIDATE.read_text())
        for key in ('S6B01','S7B05'):
            text = ''.join(d['story_cards'][key]['lines'])
            self.assertNotIn('缺镜头',text)
            self.assertNotIn('预演',text)
            self.assertNotIn('尚缺',text)
        events = {e['id']:e for e in d['sound_events']}
        proof = {x['id']:x for x in json.loads((runner.CANDIDATE.parent/'local_sfx_duration_checks.json').read_text())}
        for e in events.values():
            self.assertTrue(proof[e['asset_id']]['local_sha256_match'])
            self.assertLessEqual(e.get('source_start',0)+e['duration'],proof[e['asset_id']]['actual_local_wav_seconds'])
        self.assertLess(events['late_phone_ring']['duration'], d['beat_lead']['S7B01'])
        self.assertGreater(d['beat_lead']['S3B02'],events['pager_screen']['duration'])
        self.assertGreaterEqual(d['beat_lead']['S6B01'],events['home_latch_brace']['duration'])
        workflow = (HERE/'workflow.ep01_r06_private_preview_once.yml').read_text()
        self.assertLess(workflow.index('安装编码'), workflow.index('校验唯一触发'))


if __name__ == '__main__': unittest.main()
