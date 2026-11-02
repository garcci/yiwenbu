import contextlib
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from render import asset_references, plan, resolve_assets, ass_time, qc, shot_filter


def fixture():
    return {'duration': 2, 'width': 320, 'height': 568, 'fps': 25,
            'badge': 'AI画面·AI配音｜测试', 'captions': [{'text': '测试字幕', 'start': .2, 'end': 1.8}],
            'scenes': [{'start': 0, 'end': 2, 'frames': [
                {'image': 'a.ppm', 'start': 0, 'end': 1}, {'image': 'b.ppm', 'start': 1, 'end': 2}]}],
            'audio': [{'file': 'tone.wav', 'offset': .1, 'sourceStart': 0, 'duration': 1.7, 'volume': .2}]}


class ValidationTests(unittest.TestCase):
    def test_real_v2_schema_can_be_planned_without_opening_media(self):
        path = Path(__file__).resolve().parents[2] / 'work/ep01_assembly_20261102_v2/manifest.json'
        if not path.is_file():
            self.skipTest('Historical local manifest not in checkout')
        m = json.loads(path.read_text())
        p = plan(m)
        self.assertEqual(p['duration'], 239.88)
        self.assertEqual(len(p['shots']), 29)

    def test_plan_does_not_change_audio_timing(self):
        m = fixture()
        original = copy.deepcopy(m)
        self.assertEqual(len(plan(m)['shots']), 2)
        self.assertEqual(m, original)

    def test_forbidden_references_rejected_before_files_are_opened(self):
        for name in ('Result-10.wav', '/secret/Result-4.wav', '未命名.m4a', '未命名 2.wav'):
            m = fixture()
            m['audio'][0]['file'] = name
            with self.assertRaises(ValueError):
                asset_references(m)

    def test_bad_timeline_captions_and_unsupported_features(self):
        variants = []
        m = fixture(); m['scenes'][0]['frames'][1]['start'] = 1.04; variants.append(m)
        m = fixture(); m['captions'][0]['text'] = '一行\n二行'; variants.append(m)
        m = fixture(); m['captions'][0]['text'] = '{\\pos(0,0)}'; variants.append(m)
        m = fixture(); m['scenes'][0]['light'] = {}; variants.append(m)
        m = fixture(); m['audio'][0]['duration'] = 4; variants.append(m)
        m = fixture(); m['badge'] = ''; variants.append(m)
        for m in variants:
            with self.assertRaises(ValueError):
                plan(m)

    def test_mapping_requires_current_audio_authorization_hash_and_containment(self):
        with contextlib.nullcontext(tempfile.mkdtemp(prefix='ci-render-test-')) as d:
            root = Path(d)
            (root / 'asset').write_bytes(b'safe synthetic input')
            sha = hashlib.sha256((root / 'asset').read_bytes()).hexdigest()
            m = fixture()
            mapping = {x: {'path': 'asset', 'sha256': sha, 'authorized_for_this_draft': True}
                       for x in asset_references(m)}
            self.assertEqual(len(resolve_assets(m, mapping, root)), 3)
            del mapping['tone.wav']['authorized_for_this_draft']
            with self.assertRaises(ValueError):
                resolve_assets(m, mapping, root)
            mapping['tone.wav']['authorized_for_this_draft'] = True
            mapping['tone.wav']['path'] = '../outside'
            with self.assertRaises(ValueError):
                resolve_assets(m, mapping, root)
            mapping['tone.wav']['path'] = 'asset'
            mapping['tone.wav']['sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                resolve_assets(m, mapping, root)

    def test_qc_checks_encoding_duration_and_full_decode(self):
        p = plan(fixture())
        metadata = {'format': {'duration': '2.0'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 568,
             'pix_fmt': 'yuv420p', 'duration': '2.0', 'avg_frame_rate': '25/1', 'nb_frames': '50'},
            {'codec_type': 'audio', 'codec_name': 'aac', 'duration': '2.0'}]}
        with patch('render.probe', return_value=metadata), patch('render.run', return_value=b'') as decode:
            report = qc(Path('/synthetic/draft.mp4'), p)
            self.assertTrue(report['decoded_to_end'])
            self.assertEqual(report['voice_acceptance'], 'not_assessed')
            decode.assert_called_once()
            self.assertIn('-xerror', decode.call_args.args[0])
        metadata['streams'][1]['duration'] = '1.8'
        with patch('render.probe', return_value=metadata), self.assertRaises(ValueError):
            qc(Path('/synthetic/draft.mp4'), p)

    def test_layers_stretch_and_alpha_composites_before_yuv(self):
        m = fixture()
        m['scenes'] = [
            {'start': 0, 'end': 1, 'layers': [{'image': 'a.png', 'x': 0, 'y': 0,
             'width': 320, 'height': 568, 'opacity': .5,
             'crop': {'x': .1, 'y': .2, 'width': .5, 'height': .5}}]},
            {'start': 1, 'end': 2, 'image': 'b.png'}]
        p = plan(m)
        layer, background = p['shots']
        self.assertEqual(layer['fit'], 'stretch')
        self.assertEqual(background['fit'], 'cover')
        graph = shot_filter(layer, p)
        self.assertIn('crop=iw*0.5:ih*0.5:iw*0.1:ih*0.2,scale=320:568,', graph)
        self.assertNotIn('force_original_aspect_ratio', graph)
        self.assertIn('format=rgba,colorchannelmixer=aa=0.5', graph)
        self.assertIn('color=c=black:s=320x568:r=25,format=rgba[black]', graph)
        self.assertIn('[black][foreground]overlay', graph)
        self.assertTrue(graph.endswith('format=yuv420p[out]'))
        self.assertIn('force_original_aspect_ratio=increase,crop=320:568', shot_filter(background, p))

    def test_symlink_cannot_hide_excluded_basename_before_hashing(self):
        with contextlib.nullcontext(tempfile.mkdtemp(prefix='ci-render-link-test-')) as d:
            root = Path(d)
            # This is only synthetic text under a blocked name, never user media.
            (root / 'Result-10.wav').write_bytes(b'synthetic regression fixture only')
            (root / 'innocent.wav').symlink_to(root / 'Result-10.wav')
            mapping = {x: {'path': 'innocent.wav', 'sha256': '0' * 64,
                          'authorized_for_this_draft': True} for x in asset_references(fixture())}
            with patch('render.digest', side_effect=AssertionError('must not open linked media')) as hashing:
                with self.assertRaisesRegex(ValueError, 'Symlinks forbidden'):
                    resolve_assets(fixture(), mapping, root)
                hashing.assert_not_called()
            (root / 'actual-directory').mkdir()
            (root / 'directory-link').symlink_to(root / 'actual-directory', target_is_directory=True)
            mapping['a.ppm']['path'] = 'directory-link/anything.png'
            with patch('render.digest', side_effect=AssertionError('must not hash')):
                with self.assertRaisesRegex(ValueError, 'Symlinks forbidden'):
                    resolve_assets(fixture(), mapping, root)

    def test_ass_timestamp_carry(self):
        self.assertEqual(ass_time(59.999), '0:01:00.00')


if __name__ == '__main__':
    unittest.main()
