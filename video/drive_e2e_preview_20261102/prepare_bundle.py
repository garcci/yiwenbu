#!/usr/bin/env python3
"""Offline declaration for one 8-second technical preview; no network or generation."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import wave

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ci_render'))
from render import plan

IMAGE_ID = '1hRtm5SVRagq3EVPA_8pwtngiFfjGeKDo'
AUDIO_ID = '1g6an4mkAYoft_PVoaT42OqMdaDRDSxtX'
IMAGE_SHA = '3fad4582e2afe0de9cb5bdc7bef638372e79a5c83cb4b62fc84190235a5415dc'
AUDIO_SHA = 'd6687916aed6bd292f33306e110bef687fbe78c60b964fa70936fe912beed447'
FOLDER_ID = '11uMWY64q_tLolJ210NmLhfqnkW1D5fBR'


def bundle():
    return {
        'purpose': '8-second Drive-to-Actions technical preview; not the formal first episode; human review pending',
        'manifest': {
            'duration': 8, 'width': 360, 'height': 640, 'fps': 25,
            'fontSize': 16, 'safeInset': 28, 'captionBottom': 128,
            'badge': 'AI画面·AI配音｜技术预览待审',
            'scenes': [
                {'start': 0, 'end': 4, 'image': 'authorized-gpt-image.png'},
                {'start': 4, 'end': 8, 'layers': [{
                    'image': 'authorized-gpt-image.png', 'x': 0, 'y': 0, 'width': 360, 'height': 640,
                    'crop': {'x': .12, 'y': .05, 'width': .76, 'height': .76}, 'opacity': 1}]}],
            'captions': [{'text': '云盘端到端测试｜非正式成片', 'start': .2, 'end': 7.8}],
            'audio': [{'file': 'authorized-plan-paragraph.mp3', 'offset': .08,
                       'sourceStart': 0, 'duration': 7.872, 'volume': 1}]},
        'assets': {
            'authorized-gpt-image.png': {'path': 'assets/image.png', 'drive_file_id': IMAGE_ID, 'sha256': IMAGE_SHA},
            'authorized-plan-paragraph.mp3': {'path': 'assets/paragraph.mp3', 'drive_file_id': AUDIO_ID,
                                              'sha256': AUDIO_SHA, 'authorized_for_this_draft': True}}}


def encoded_bundle():
    return (json.dumps(bundle(), ensure_ascii=False, indent=2) + '\n').encode()


def inspect_local(image, audio, decoded_pcm):
    # Only these explicitly authorized files are read; no scanning of Downloads.
    image_bytes, audio_bytes = image.read_bytes(), audio.read_bytes()
    assert hashlib.sha256(image_bytes).hexdigest() == IMAGE_SHA
    assert hashlib.sha256(audio_bytes).hexdigest() == AUDIO_SHA
    assert image_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    dimensions = struct.unpack('>II', image_bytes[16:24])
    with wave.open(str(decoded_pcm)) as f:
        frames, rate, channels = f.getnframes(), f.getframerate(), f.getnchannels()
    assert (frames, rate, channels) == (188928, 24000, 1)
    return {'image': {'drive_id': IMAGE_ID, 'bytes': len(image_bytes), 'sha256': IMAGE_SHA,
                      'width': dimensions[0], 'height': dimensions[1]},
            'audio': {'drive_id': AUDIO_ID, 'bytes': len(audio_bytes), 'sha256': AUDIO_SHA,
                      'decoded_pcm_frames': frames, 'sample_rate': rate, 'channels': channels,
                      'decoded_duration_seconds': frames / rate,
                      'decoded_pcm_provenance': 'existing afconvert complete decode; afinfo current estimate agrees'},
            'cloud_hash_match': 'not_yet_verified; CI must download and compare SHA256 before rendering',
            'voice_acceptance': 'not_assessed', 'preview_status': 'prepared_not_run'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path)
    p.add_argument('--audio', type=Path)
    p.add_argument('--decoded-pcm', type=Path)
    p.add_argument('--write', action='store_true')
    args = p.parse_args()
    plan(bundle()['manifest'])
    if args.write:
        target = HERE / 'input-bundle.json'
        with target.open('xb') as f:
            f.write(encoded_bundle())
    if args.image and args.audio and args.decoded_pcm:
        report = inspect_local(args.image, args.audio, args.decoded_pcm)
        with (HERE / 'source-audit.json').open('x') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write('\n')
    assert (HERE / 'input-bundle.json').read_bytes() == encoded_bundle()
    print('Offline bundle valid:', hashlib.sha256(encoded_bundle()).hexdigest(), '8 seconds; 2 declared assets; no encoding run')


if __name__ == '__main__':
    main()
