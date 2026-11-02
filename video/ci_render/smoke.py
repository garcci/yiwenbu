#!/usr/bin/env python3
"""Synthetic-only 2 second smoke test. No user's audio/images are opened."""
import argparse
import contextlib
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import wave
from render import digest, render, resolve_assets, encode_shot, run
from test_render import fixture


def alpha_and_fit_smoke(root):
    from PIL import Image
    image = Image.new('RGBA', (320, 160), (255, 0, 255, 0))
    pixels = image.load()
    for y in range(80, 160):
        for x in range(320):
            pixels[x, y] = (255, 0, 0, 255) if x < 64 else ((0, 255, 0, 128) if x < 256 else (0, 0, 255, 255))
    source = root / 'alpha-landscape.png'
    image.save(source)
    p = {'width': 320, 'height': 568, 'fps': 25}
    for fit, opacity, expected in [
        ('stretch', .5, [(128, 0, 0), (0, 64, 0), (0, 0, 128)]),
        ('cover', 1, [(0, 128, 0), (0, 128, 0), (0, 128, 0)])]:
        shot = {'start': 0, 'end': .04, 'crop': None, 'opacity': opacity, 'fit': fit}
        output = root / f'alpha-{fit}.mp4'
        encode_shot(source, shot, p, output, root)
        rgb = run(['ffmpeg', '-v', 'error', '-i', str(output), '-frames:v', '1',
                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        def sample(x, y):
            offset = (y * 320 + x) * 3
            return tuple(rgb[offset:offset + 3])
        assert len(rgb) == 320 * 568 * 3
        # Transparent top pixels must reveal black, never their hidden magenta RGB.
        assert max(sample(160, 100)) <= 12, (fit, 'transparent area not black')
        for x, wanted in zip((16, 160, 304), expected):
            actual = sample(x, 450)
            assert all(abs(a - b) <= 12 for a, b in zip(actual, wanted)), (fit, x, actual, wanted)


def story_timing_smoke(video, report):
    # Check immediately before/on/after both cards, including the scene cut.
    frames = (9, 10, 19, 20, 24, 25, 34, 35)
    select = '+'.join(f'eq(n,{n})' for n in frames)
    rgb = run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', f"select='{select}'",
               '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    stride = 320 * 568 * 3
    assert len(rgb) == len(frames) * stride
    for i, frame in enumerate(frames):
        expected = 10 <= frame < 20 or 25 <= frame < 35
        offset = i * stride + (161 * 320 + 33) * 3
        red, green, blue = rgb[offset:offset + 3]
        visible = red > 150 and green > 100 and blue < 140
        assert visible == expected, ('story card boundary', frame, (red, green, blue), expected)
        if expected:
            white_pixels = 0
            for y in range(168, 250):
                for x in range(40, 280):
                    offset = i * stride + (y * 320 + x) * 3
                    if min(rgb[offset:offset + 3]) > 180:
                        white_pixels += 1
            assert white_pixels > 20, ('story text missing', frame, white_pixels)
    assert [(c['start_frame'], c['end_frame_exclusive']) for c in report['story_overlay_timeline']] == [(10, 20), (25, 35)]
    assert report['silent_story_comprehension'] == 'not_assessed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    args = parser.parse_args()
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SystemExit('SKIPPED: ffmpeg/ffprobe missing; no actual encoding or decoding test ran.')
    with contextlib.nullcontext(tempfile.mkdtemp(prefix='ci-render-synthetic-')) as d:
        root = Path(d)
        print(f'Synthetic test files retained: {root}')
        alpha_and_fit_smoke(root)
        for name, pixel in [('a.ppm', bytes([64, 20, 10])), ('b.ppm', bytes([10, 30, 64]))]:
            (root / name).write_bytes(b'P6\n320 568\n255\n' + pixel * 320 * 568)
        with wave.open(str(root / 'tone.wav'), 'wb') as audio:
            audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b''.join(struct.pack('<h', round(4000 * math.sin(2 * math.pi * 440 * i / 48000)))
                                       for i in range(48000 * 2)))
        m = fixture()
        m['fontSize'] = 20
        m['safeInset'] = 24
        m['story_overlays'] = [
            {'id': 'screen', 'start': .4, 'end': .8, 'x': 32, 'y': 160, 'width': 256, 'height': 100,
             'fontSize': 16, 'lines': ['屏幕：空号']},
            {'id': 'ledger', 'start': 1, 'end': 1.4, 'x': 32, 'y': 160, 'width': 256, 'height': 100,
             'fontSize': 16, 'lines': ['红簿旧留言', '十二月九日｜已捞出']}]
        mapping = {name: {'path': name, 'sha256': digest(root / name), 'authorized_for_this_draft': True}
                   for name in ('a.ppm', 'b.ppm', 'tone.wav')}
        report = render(m, resolve_assets(m, mapping, root), root / 'output', args.font)
        assert report['video_frames'] == 50
        story_timing_smoke(root / 'output/draft.mp4', report)
        print(json.dumps({'synthetic_smoke_pass': True, 'frames': report['video_frames'],
                          'alpha_and_aspect_fit_pixels_pass': True, 'story_card_timing_and_text_pixels_pass': True, 'human_media_used': False, 'production_acceptance': False}))


if __name__ == '__main__':
    main()
