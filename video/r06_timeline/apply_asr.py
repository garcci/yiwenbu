#!/usr/bin/env python3
"""Offline ASR word-mark adapter. Transcript mismatch never silently repaired."""
import argparse
import copy
import json
import math
from pathlib import Path
import unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace()
                   and not unicodedata.category(c).startswith('P'))


def apply(data, asr):
    result = copy.deepcopy(data); seen = set()
    required = {k for k, v in result['assets'].items() if v['kind'] == 'voice'}
    for segment in asr['segments']:
        key = segment['voice_id']
        if key not in required or key in seen: raise ValueError('ASR duplicate/unexpected voice ID')
        seen.add(key); a = result['assets'][key]
        if segment['audio_sha256'] != a['sha256']: raise ValueError('ASR is for different audio bytes')
        words = segment['words']
        if not words or normalized(''.join(w['text'] for w in words)) != normalized(a['source_text']):
            raise ValueError('ASR transcript differs from source; listen/correct or explicit unaligned draft')
        last = 0; captions = []; current = None
        for word in words:
            start, end, text = word['start'], word['end'], word['text']
            if (not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or
                not math.isfinite(start) or not math.isfinite(end) or not last <= start < end <= a['duration_seconds']):
                raise ValueError('ASR missing/nonmonotonic/out-of-range word timing')
            if not text.strip() or len(text) > 18: raise ValueError('ASR token too long for trustworthy one-line caption')
            if current and len(current['text'] + text) > 18:
                captions.append(current); current = None
            if current:
                current['text'] += text; current['end'] = end
            else: current = {'text': text, 'start': start, 'end': end}
            last = end
            if text[-1] in '。！？；': captions.append(current); current = None
        if current: captions.append(current)
        method = 'api_timestamp_human_checked' if segment.get('human_checked') is True else 'api_timestamp_unreviewed'
        a.update(speech_start=words[0]['start'], speech_end=words[-1]['end'], speech_boundary_method=method,
                 caption_method=method, captions=captions)
    if seen != required: raise ValueError('ASR needs all 27 voices; missing marks never estimated')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True); p.add_argument('--asr', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    if a.output.exists(): raise SystemExit('Choose a new output path')
    try: result = apply(json.loads(a.inputs.read_text()), json.loads(a.asr.read_text()))
    except (KeyError, TypeError, ValueError, OSError): raise SystemExit('ASR adapter stopped: transcript/hash/timing incomplete or inconsistent; no estimated alignment') from None
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('ASR word marks imported; human review status retained. No listening performed.')


if __name__ == '__main__': main()
