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
        mapping = {name: {'path': name, 'sha256': digest(root / name), 'authorized_for_this_draft': True}
                   for name in ('a.ppm', 'b.ppm', 'tone.wav')}
        report = render(m, resolve_assets(m, mapping, root), root / 'output', args.font)
        assert report['video_frames'] == 50
        print(json.dumps({'synthetic_smoke_pass': True, 'frames': report['video_frames'],
                          'alpha_and_aspect_fit_pixels_pass': True, 'human_media_used': False, 'production_acceptance': False}))


if __name__ == '__main__':
    main()
