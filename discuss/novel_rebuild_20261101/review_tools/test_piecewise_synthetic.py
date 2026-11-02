"""SYNTHETIC ONLY: transport/archival checks, not actual review or model calls."""
import unittest

import test_synthetic as fixture
from piecewise_review import generate, merge
from review_matrix import PIECES, digest, format_equivalent, read_json, write_json


class PiecewiseSynthetic(unittest.TestCase):
    setUp = fixture.SyntheticValidation.setUp
    check = fixture.SyntheticValidation.check
    change = fixture.SyntheticValidation.change

    def archive_piecewise(self, failed_piece=None, shared_url=None):
        response = read_json(self.responses / '01.json')
        response_paths, status_paths = {}, {}
        for p in PIECES:
            single = dict(response['pieces'][p], reviewer_id='01', piece=p,
                          input_hash=self.m['input_hash'])
            rf = self.root / f'SYNTHETIC_{p}.json'
            sf = self.root / f'SYNTHETIC_{p}_status.json'
            write_json(rf, single)
            write_json(sf, {
                'reviewer_id': '01', 'piece': p, 'source_sha256': self.m['sources'][p]['sha256'],
                'input_hash': self.m['input_hash'], 'transport': 'browser', 'success': True,
                'independent_session': True, 'private_session': True,
                'response_completed': p != failed_piece, 'extraction_complete': True,
                'response_truncated': False, 'api_error': None,
                'model_label': 'SYNTHETIC Flash-Lite NOT A CALL',
                'call_id': f'SYNTHETIC-browser-01-{p}',
                'session_url': shared_url if p == 'novel' and shared_url else f'https://gemini.google.com/app/SYNTHETIC-01-{p}',
                'response_sha256': digest(rf.read_bytes())})
            response_paths[p], status_paths[p] = rf, sf
        out = merge(self.bundle / 'manifest.json', '01', response_paths, status_paths,
                    self.root / 'SYNTHETIC_assembled')
        (self.responses / '01.json').write_bytes((out / 'responses/reviewer_01.json').read_bytes())
        (self.statuses / '01.json').write_bytes((out / 'statuses/reviewer_01_status.json').read_bytes())
        return out

    def sol_status(self, completed=True):
        path = self.statuses / '08.json'
        status = read_json(path)
        status.pop('exit_code')
        status.pop('model')
        status.pop('call_id')
        status.update(transport='subagent', model_label='SYNTHETIC GPT-6.1 Sol NOT A CALL',
                      agent_task_id='SYNTHETIC-NOT-AN-ACTUAL-TASK-08', agent_completed=completed,
                      extraction_complete=True, participated_in_writing=False)
        write_json(path, status)

    def test_piecewise_and_sol_completed_synthetic_only(self):
        self.archive_piecewise()
        self.sol_status()
        self.assertTrue(self.check()['gate'])

    def test_piecewise_one_unfinished(self):
        self.archive_piecewise(failed_piece='episode01')
        self.assertFalse(self.check()['gate'])

    def test_cross_persona_session_reuse(self):
        url = 'https://gemini.google.com/app/SYNTHETIC-shared'
        self.archive_piecewise(shared_url=url)
        path = self.statuses / '02.json'
        status = read_json(path)
        status.pop('exit_code')
        status.update(transport='browser', session_url=url+'?different=query', model_label='SYNTHETIC',
                      private_session=True, response_completed=True, extraction_complete=True,
                      response_truncated=False)
        write_json(path, status)
        self.assertFalse(self.check()['gate'])

    def test_raw_archive_tamper_rejected(self):
        out = self.archive_piecewise()
        path = out / 'raw/reviewer_01_novel.response.json'
        path.write_bytes(path.read_bytes()+b'\n')
        self.assertFalse(self.check()['gate'])

    def test_subagent_unfinished(self):
        self.sol_status(completed=False)
        self.assertFalse(self.check()['gate'])

    def test_format_equivalence_is_diagnostic_only(self):
        self.assertTrue(format_equivalent('“合成假数据”', '**合成假数据**'))
        self.assertFalse(format_equivalent('合成……数据', '合成假数据'))
        self.assertFalse(format_equivalent('合成真数据', '合成假数据'))
        self.change(lambda r: r['pieces']['novel']['scores'][self.m['dimensions'][0]].update(evidence_quote='“合成假数据”'))
        result = self.check()
        self.assertFalse(result['gate'])
        self.assertTrue(result['format_equivalence_diagnostics_only'][0]['format_equivalent'])

    def test_generate_twenty_one_single_piece_prompts(self):
        out = self.root / 'SYNTHETIC_prompts'
        generate(self.bundle / 'manifest.json', out)
        files = list(out.glob('*.prompt.txt'))
        self.assertEqual(len(files), 30)
        prompt = (out / 'reviewer_01_episode01.prompt.txt').read_text()
        self.assertIn('BEGIN episode01', prompt)
        self.assertNotIn('BEGIN novel', prompt)
        self.assertNotIn('BEGIN season_outline', prompt)


if __name__ == '__main__':
    unittest.main()
