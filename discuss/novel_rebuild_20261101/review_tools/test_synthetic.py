"""SYNTHETIC ONLY. No real review, model invocation, or literary validation."""
import tempfile
import unittest
from pathlib import Path

from review_matrix import PIECES, digest, prepare, read_json, validate, write_json


class SyntheticValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='SYNTHETIC_REVIEW_ONLY_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paths = {}
        for p in PIECES:
            paths[p] = self.root / f'{p}.txt'
            paths[p].write_text(('合成假数据，不是实际文学作品。' * 8) + p + '\n', encoding='utf-8')
        self.bundle = self.root / 'synthetic_bundle'
        self.m = prepare(paths, self.bundle)
        self.responses = self.root / 'SYNTHETIC_responses'
        self.statuses = self.root / 'SYNTHETIC_statuses'
        self.responses.mkdir()
        self.statuses.mkdir()
        for rid, _ in self.m['personas']:
            response = {'reviewer_id': rid, 'input_hash': self.m['input_hash'],
                        'ai_simulation': True, 'pieces': {}}
            for p in PIECES:
                text = (self.bundle / self.m['sources'][p]['file']).read_text(encoding='utf-8')
                response['pieces'][p] = {
                    'source_sha256': self.m['sources'][p]['sha256'],
                    'coverage': {'complete': True, 'read_characters': len(text), 'limitations': ''},
                    'opening_quote': text.strip()[:40], 'ending_quote': text.strip()[-40:],
                    'scores': {d: {'score': 9.6, 'evidence_quote': '合成假数据', 'reason': '仅为校验分支的合成理由'}
                               for d in self.m['dimensions']}, 'major_issues': []}
            write_json(self.responses / f'{rid}.json', response)
            write_json(self.statuses / f'{rid}.json', {
                'reviewer_id': rid, 'input_hash': self.m['input_hash'], 'success': True,
                'transport': 'cli',
                'exit_code': 0, 'independent_session': True, 'model': 'SYNTHETIC-gemini-NOT-A-CALL',
                'call_id': f'SYNTHETIC-{rid}',
                'response_sha256': digest((self.responses / f'{rid}.json').read_bytes())})

    def check(self):
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses, self.root / 'result')
        self.assertEqual(result['cell_count'], 300)
        return result

    def change(self, mutation):
        path = self.responses / '01.json'
        value = read_json(path)
        mutation(value)
        write_json(path, value)
        status_path = self.statuses / '01.json'
        status = read_json(status_path)
        status['response_sha256'] = digest(path.read_bytes())
        write_json(status_path, status)

    def test_all_high_synthetic_only(self):
        self.assertTrue(self.check()['gate'])

    def test_one_low(self):
        self.change(lambda r: r['pieces']['novel']['scores'][self.m['dimensions'][0]].update(score=9.4))
        result = self.check()
        self.assertFalse(result['gate'])
        self.assertFalse(result['pieces']['novel']['gate'])
        self.assertTrue(result['pieces']['episode01']['gate'])

    def test_missing_dimension(self):
        self.change(lambda r: r['pieces']['episode01']['scores'].pop(self.m['dimensions'][0]))
        self.assertFalse(self.check()['gate'])

    def test_wrong_hash(self):
        self.change(lambda r: r.update(input_hash='incorrect'))
        self.assertFalse(self.check()['gate'])

    def test_duplicate_reviewer(self):
        self.change(lambda r: r.update(reviewer_id='02'))
        self.assertFalse(self.check()['gate'])

    def test_incomplete_read(self):
        self.change(lambda r: r['pieces']['season_outline']['coverage'].update(complete=False))
        self.assertFalse(self.check()['gate'])

    def scope_sidecar(self):
        response_path = self.responses / '01.json'
        response = read_json(response_path)
        sidecar = self.root / 'SYNTHETIC_scope_review.json'
        write_json(sidecar, {
            'input_hash': self.m['input_hash'],
            'manifest_sha256': digest((self.bundle / 'manifest.json').read_bytes()),
            'entries': [{
                'reviewer_id': '01', 'piece': 'novel', 'decision': 'scope_only',
                'response_sha256': digest(response_path.read_bytes()),
                'source_sha256': self.m['sources']['novel']['sha256'],
                'coverage': response['pieces']['novel']['coverage'],
                'rationale': 'SYNTHETIC: wording only excludes nonexistent audiovisual material.'}]})
        return sidecar

    def test_scope_limitation_requires_review(self):
        self.change(lambda r: r['pieces']['novel']['coverage'].update(limitations='只评价文字，不评价未制作音画'))
        self.assertFalse(self.check()['gate'])

    def test_bound_scope_limitation_passes(self):
        self.change(lambda r: r['pieces']['novel']['coverage'].update(limitations='只评价文字，不评价未制作音画'))
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses,
                          self.root / 'result', self.scope_sidecar())
        self.assertTrue(result['gate'])

    def test_scope_review_cannot_override_real_incomplete_read(self):
        self.change(lambda r: r['pieces']['novel']['coverage'].update(
            complete=False, read_characters=12, limitations='只读了开头，未阅读其余正文'))
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses,
                          self.root / 'result', self.scope_sidecar())
        self.assertFalse(result['gate'])
        self.assertIn('01/novel: hash mismatch or incomplete coverage', result['errors'])

    def test_scope_review_cannot_override_short_character_count(self):
        self.change(lambda r: r['pieces']['novel']['coverage'].update(
            complete=True, read_characters=12, limitations='只评价文字'))
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses,
                          self.root / 'result', self.scope_sidecar())
        self.assertFalse(result['gate'])
        self.assertIn('01/novel: hash mismatch or incomplete coverage', result['errors'])

    def test_scope_review_cannot_override_source_hash_mismatch(self):
        self.change(lambda r: r['pieces']['novel'].update(source_sha256='incorrect'))
        self.change(lambda r: r['pieces']['novel']['coverage'].update(limitations='只评价文字'))
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses,
                          self.root / 'result', self.scope_sidecar())
        self.assertFalse(result['gate'])
        self.assertIn('01/novel: hash mismatch or incomplete coverage', result['errors'])

    def test_stale_scope_sidecar_rejected(self):
        self.change(lambda r: r['pieces']['novel']['coverage'].update(limitations='只评价文字'))
        sidecar = self.scope_sidecar()
        self.change(lambda r: r['pieces']['novel']['coverage'].update(limitations='实际上末段未读'))
        result = validate(self.bundle / 'manifest.json', self.responses, self.statuses,
                          self.root / 'result', sidecar)
        self.assertFalse(result['gate'])

    def test_fabricated_quote(self):
        self.change(lambda r: r['pieces']['novel']['scores'][self.m['dimensions'][0]].update(evidence_quote='不存在的引用'))
        self.assertFalse(self.check()['gate'])

    def test_failed_call(self):
        path = self.statuses / '01.json'
        value = read_json(path)
        value['success'] = False
        write_json(path, value)
        self.assertFalse(self.check()['gate'])

    def test_unresolved_hard_flaw(self):
        self.change(lambda r: r['pieces']['novel']['major_issues'].append({
            'description': '合成硬伤', 'evidence_quote': '合成假数据',
            'severity': 'substantive_hard_flaw', 'resolved': False}))
        self.assertFalse(self.check()['gate'])

    def test_duplicate_json_key(self):
        path = self.responses / '01.json'
        path.write_text('{"reviewer_id":"01","reviewer_id":"01"}', encoding='utf-8')
        self.assertFalse(self.check()['gate'])

    def browser_status(self):
        path = self.statuses / '01.json'
        value = read_json(path)
        value.pop('exit_code')
        value.pop('model')
        value.update(transport='browser', response_completed=True, extraction_complete=True,
                     private_session=True, response_truncated=False, api_error=None,
                     model_label='SYNTHETIC Argon label ONLY',
                     session_url='https://gemini.google.com/app/SYNTHETIC-NOT-A-REAL-SESSION-01')
        write_json(path, value)
        return path, value

    def test_browser_complete_synthetic_only(self):
        self.browser_status()
        self.assertTrue(self.check()['gate'])

    def test_browser_unfinished(self):
        path, value = self.browser_status()
        value['response_completed'] = False
        write_json(path, value)
        self.assertFalse(self.check()['gate'])

    def test_browser_missing_extraction(self):
        path, value = self.browser_status()
        value.pop('extraction_complete')
        write_json(path, value)
        self.assertFalse(self.check()['gate'])

    def test_browser_api_error(self):
        path, value = self.browser_status()
        value['api_error'] = 'SYNTHETIC region error'
        write_json(path, value)
        self.assertFalse(self.check()['gate'])

    def test_browser_truncated(self):
        path, value = self.browser_status()
        value['response_truncated'] = True
        write_json(path, value)
        self.assertFalse(self.check()['gate'])


if __name__ == '__main__':
    unittest.main()
