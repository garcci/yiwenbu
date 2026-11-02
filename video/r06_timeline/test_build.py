"""Offline synthetic metadata tests; never a measured production input."""
import copy
import json
from pathlib import Path
import unittest
import build

PLAN = json.loads((Path(__file__).parent / 'edit_plan_r06.json').read_text())

def asset(kind, name, duration=3):
    x = {'kind': kind, 'confirmed': True, 'path': 'assets/' + name + ('.png' if kind == 'image' else '.wav'),
         'sha256': 'a' * 64, 'drive_file_id': 'synthetic_id_' + name,
         'provenance': 'subscription_api_new' if kind == 'voice' else 'original_procedural'}
    if kind != 'image':
        x.update(authorized_for_this_draft=True, duration_seconds=duration, duration_method='ffprobe',
                 ffprobe={'streams': [{'codec_type': 'audio', 'duration': str(duration)}]})
    if kind == 'voice':
        x.update(speech_start=.1, speech_end=duration-.1, speech_boundary_method='human_marked',
                 source_text_verified=True, caption_method='human_marked',
                 captions=[{'start': .1, 'end': duration-.1, 'text': '合成测试非实际配音'}])
    return x


def fixture():
    a = {'IMAGE': asset('image', 'IMAGE'), 'F07': asset('sfx', 'F07', 6)}
    a['F07']['first_impact_seconds'] = .4
    for beat in PLAN['beats']:
        for v in beat['voice_line_ids']: a[v] = asset('voice', v)
    return {'test_fixture': True, 'assets': a,
            'beat_images': {b['id']: 'IMAGE' for b in PLAN['beats']},
            'story_cards': {'S1B01': {'read_seconds': 4, 'lines': ['台里03:09；号码栏空白', '那是我的声音']},
                'S1B07': {'read_seconds': 5, 'lines': ['妈，我没事。灯别关。', '三号柜后面。', '是他，他手上有铁锈味。', '别回头，小雯。']},
                'S2B02': {'read_seconds': 5, 'lines': ['凤，我没喝酒。', '我找到晚晚了。三号柜。', '十二月九日，城南水闸捞出']},
                'S7B01': {'read_seconds': 3, 'lines': ['家中03:15']},
                'S7B03': {'read_seconds': 1, 'lines': ['妈，别开门']}},
            'sound_events': [{'id': 'door_three_knocks', 'asset_id': 'F07', 'duration': 6,
                              'anchor': {'type': 'speech_end', 'id': 'S7_26'}, 'volume': .3}]}


class BuildTests(unittest.TestCase):
    def test_fixture_not_accepted_by_production_entry(self):
        with self.assertRaisesRegex(ValueError, 'Synthetic fixture'): build.build(PLAN, fixture())

    def test_compatible_measured_timeline_without_speed_change(self):
        m, mapping, report = build._build(PLAN, fixture())
        build.renderer.plan(m)
        voices = [a for a in m['audio'] if a['file'].startswith('S')]
        self.assertEqual(len(voices), 27)
        self.assertTrue(all(a['duration'] == 3 and 'fadeIn' not in a for a in voices))
        self.assertEqual(len(mapping), 29)
        knock = next(a for a in m['audio'] if a['file'] == 'F07')
        self.assertGreaterEqual(knock['offset'], report['speech_anchors']['S7_26']['end'])
        self.assertAlmostEqual(report['timeline']['S7B04']['start'], build.up(knock['offset'] + .4))
        self.assertLessEqual(knock['offset'] + 6, report['speech_anchors']['S7_27']['file_start'])

    def test_missing_voice_refuses_no_fallback(self):
        f = fixture(); del f['assets']['S3_09']
        with self.assertRaisesRegex(ValueError, 'Missing new API'): build._build(PLAN, f)

    def test_duration_not_claimed_without_probe(self):
        f = fixture(); f['assets']['S1_01']['ffprobe']['streams'][0]['duration'] = '8'
        with self.assertRaisesRegex(ValueError, 'disagrees'): build._build(PLAN, f)

    def test_experience_and_old_result_refused(self):
        for update in ({'provenance': 'experience'}, {'path': 'assets/Result-24.wav'}):
            f = fixture(); f['assets']['S1_01'].update(update)
            with self.assertRaises(ValueError): build._build(PLAN, f)

    def test_knock_source_trim_refused(self):
        f = fixture(); f['sound_events'][0]['source_start'] = .2; f['sound_events'][0]['duration'] = 5
        with self.assertRaisesRegex(ValueError, 'F07'): build._build(PLAN, f)

    def test_music_edges_only_no_repeat_expansion(self):
        f = fixture(); a = asset('music', 'M1', 10)
        a.update(license='CC BY 4.0', attribution_lines=['Long note One', 'Kevin MacLeod (incompetech.com)',
                 'https://creativecommons.org/licenses/by/4.0/', '节选、调音与淡化'], attribution_text='test attribution', credit_read_seconds=6)
        f['assets']['M1'] = a
        f['sound_events'].append({'id': 'music_1', 'asset_id': 'M1', 'duration': 4,
                                 'anchor': {'type': 'beat_start', 'id': 'S1B01'}, 'volume': .04})
        m, _, report = build._build(PLAN, f)
        self.assertEqual(len([t for t in m['audio'] if t['file'] == 'M1']), 1)
        self.assertEqual(m['audio'][-1]['fadeIn'], .5)
        self.assertEqual(len(report['music_attribution']), 1)

    def test_clues_cannot_be_silently_omitted(self):
        f = fixture(); del f['story_cards']['S2B02']
        with self.assertRaisesRegex(ValueError, 'visual clue missing'): build._build(PLAN, f)

    def test_asr_exact_text_and_hash_or_stop(self):
        import apply_asr
        f = fixture()
        for a in f['assets'].values():
            if a['kind'] == 'voice': a['source_text'] = '妈，我没事。'
        asr = {'segments': [{'voice_id': k, 'audio_sha256': a['sha256'], 'words': [
            {'text': '妈，', 'start': .1, 'end': .4}, {'text': '我没事。', 'start': .5, 'end': 1.3}]}
            for k, a in f['assets'].items() if a['kind'] == 'voice']}
        marked = apply_asr.apply(f, asr)
        with self.assertRaisesRegex(ValueError, 'ASR requires human'): build._build(PLAN, marked)
        marked['allow_unreviewed_asr'] = True
        m, _, report = build._build(PLAN, marked)
        self.assertAlmostEqual(report['speech_anchors']['S7_26']['end'], report['speech_anchors']['S7_26']['file_end'])
        asr['segments'][0]['words'][0]['text'] = '爸，'
        with self.assertRaisesRegex(ValueError, 'differs'): apply_asr.apply(f, asr)

    def test_asr_missing_time_stops(self):
        import apply_asr
        f = {'assets': {'S1_01': dict(asset('voice', 'S1_01'), source_text='妈')}}
        asr = {'segments': [{'voice_id': 'S1_01', 'audio_sha256': 'a'*64, 'words': [{'text': '妈', 'start': .1}]}]}
        with self.assertRaises(KeyError): apply_asr.apply(f, asr)

    def test_unaligned_draft_does_not_claim_speech_sync(self):
        f = fixture()
        for a in f['assets'].values():
            if a['kind'] == 'voice': a['source_text'] = '妈，我没事。'
        f = build.draft_page_marks(f)
        m, _, report = build._build(PLAN, f)
        self.assertIn('UNALIGNED', report['caption_alignment'])
        self.assertEqual(report['speech_anchors']['S7_26']['end'], report['speech_anchors']['S7_26']['file_end'])

    def test_missing_action_uses_card_only_black_background(self):
        f = fixture(); f['card_only_beats'] = ['S1B01']
        m, _, _ = build._build(PLAN, f)
        self.assertNotIn('image', m['scenes'][0])
        self.assertEqual(m['scenes'][0]['layers'][0]['opacity'], 0)
        build.renderer.plan(m)


if __name__ == '__main__': unittest.main()
