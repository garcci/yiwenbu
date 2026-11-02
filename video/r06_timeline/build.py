#!/usr/bin/env python3
"""Offline measured-audio r06 builder. No network, model, upload, or fallback."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ci_renderer', HERE.parent / 'ci_render/render.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def need(ok, message):
    if not ok:
        raise ValueError(message)


def seconds(x, label, minimum=0):
    need(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= minimum,
         'Invalid seconds: ' + label)
    return float(x)


def up(t, fps=25):
    return math.ceil((t - 1e-9) * fps) / fps


def check_asset(key, entry, kind):
    need(entry.get('kind') == kind and entry.get('confirmed') is True, 'Unconfirmed asset: ' + key)
    need(re.fullmatch(r'[A-Za-z0-9_-]{10,200}', entry.get('drive_file_id', '')), 'Drive ID required: ' + key)
    need(re.fullmatch(r'[0-9a-f]{64}', entry.get('sha256', '')), 'Byte SHA256 required: ' + key)
    path = entry.get('path', '')
    need(isinstance(path, str) and path and not Path(path).is_absolute() and '..' not in Path(path).parts,
         'Relative safe path required: ' + key)
    # Reject ALL old Result assets, unnamed files, and experience provenance.
    need(not re.search(r'result-\d+|未命名', key + ' ' + path, re.I), 'Old/unnamed source forbidden')
    need(entry.get('provenance') not in (None, '', 'experience', 'web_experience'), 'Provenance required: ' + key)
    if kind != 'image':
        need(entry.get('authorized_for_this_draft') is True, 'Audio authorization missing: ' + key)
        seconds(entry.get('duration_seconds'), key, .001)
        need(entry.get('duration_method') == 'ffprobe' and isinstance(entry.get('ffprobe'), dict),
             'Actual ffprobe record required: ' + key)
        probe = entry['ffprobe']
        streams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
        need(len(streams) == 1, 'One probed audio stream required: ' + key)
        raw = streams[0].get('duration', probe.get('format', {}).get('duration'))
        need(raw is not None and abs(float(raw) - entry['duration_seconds']) < .011,
             'Duration disagrees with ffprobe: ' + key)
    if kind == 'voice':
        need(entry.get('provenance') == 'subscription_api_new', 'New API voice only: ' + key)
        need(entry.get('source_text_verified') is True, 'Voice source-text ID/text not verified: ' + key)
        start = seconds(entry.get('speech_start'), key + ' speech_start')
        end = seconds(entry.get('speech_end'), key + ' speech_end', .001)
        need(start < end <= entry['duration_seconds'], 'Speech boundary out of range: ' + key)
        need(entry.get('speech_boundary_method') in ('human_marked', 'api_timestamp_human_checked', 'api_timestamp_unreviewed', 'file_duration_conservative'),
             'Speech markers require human verification: ' + key)


def draft_page_marks(inputs):
    """Explicit opt-in: page display windows, NOT speech/word alignment."""
    import copy
    inputs = copy.deepcopy(inputs)
    for key, a in inputs['assets'].items():
        if a.get('kind') != 'voice': continue
        duration = seconds(a.get('duration_seconds'), key, .001)
        text = a.get('source_text', '')
        pages = []
        for phrase in re.findall(r'[^，。！？；…]+[，。！？；…]*', text):
            pages.extend(phrase[i:i+18] for i in range(0, len(phrase), 18))
        need(pages and duration / len(pages) >= .45, 'Draft pages too fast; supply human phrase marks: ' + key)
        a['speech_start'], a['speech_end'] = 0, duration
        a['speech_boundary_method'] = 'file_duration_conservative'
        a['caption_method'] = 'unaligned_equal_page_display_windows'
        a['captions'] = [{'start': duration*i/len(pages), 'end': duration*(i+1)/len(pages), 'text': text}
                         for i, text in enumerate(pages)]
    inputs['unaligned_draft'] = True
    return inputs


def build(plan, inputs):
    need(inputs.get('test_fixture') is not True, 'Synthetic fixture requires explicit test-only call')
    expected = {v['id']: v['text'] for v in json.loads((HERE / 'voice_lines_r06.json').read_text())['lines']}
    for key, text in expected.items():
        need(inputs['assets'].get(key, {}).get('source_text') == text, 'API source text differs from frozen r06: ' + key)
    return _build(plan, inputs)


def _build(plan, inputs):
    catalog = inputs['assets']
    voice_ids = [v for beat in plan['beats'] for v in beat['voice_line_ids']]
    need(len(voice_ids) == len(set(voice_ids)) == 27, 'Expected unique 27 voice IDs')
    for vid in voice_ids:
        need(vid in catalog, 'Missing new API voice: ' + vid)
        check_asset(vid, catalog[vid], 'voice')
        if catalog[vid]['speech_boundary_method'] == 'api_timestamp_unreviewed':
            need(inputs.get('allow_unreviewed_asr') is True, 'ASR requires human check or explicit preview opt-in')
        if not inputs.get('unaligned_draft'):
            need(catalog[vid]['speech_boundary_method'] != 'file_duration_conservative', 'Conservative markers require explicit draft mode')
    manifest = {'width': 720, 'height': 1280, 'fps': 25, 'fontSize': 29, 'safeInset': 54,
                'captionBottom': 256, 'badge': 'AI静帧剪辑草稿·待听审', 'scenes': [], 'captions': [],
                'story_overlays': [], 'audio': []}
    if inputs.get('unaligned_draft'):
        manifest['badge'] = 'AI静帧草稿·字幕未对齐·待听审'
    elif inputs.get('allow_unreviewed_asr'):
        manifest['badge'] = 'AI静帧草稿·ASR待复核'
    timeline, speech, used, issues, cursor = {}, {}, set(), [], 0.0
    cards = inputs.get('story_cards', {})
    # No free-form giant clue cards: curate explicit lines for each beat.
    for beat in plan['beats']:
        bid = beat['id']; start = cursor
        image = inputs['beat_images'].get(bid)
        need(image in catalog, 'Confirmed beat image required: ' + bid)
        check_asset(image, catalog[image], 'image'); used.add(image)
        hold = seconds(inputs.get('visual_holds', {}).get(bid, 1.2), bid + ' visual hold')
        if bid == 'S7B04': hold = max(hold, 6.0)
        local = seconds(inputs.get('beat_lead', {}).get(bid, 0), bid + ' lead')
        for vid in beat['voice_line_ids']:
            a = catalog[vid]; gap = seconds(inputs.get('voice_gaps', {}).get(vid, 0), vid + ' gap')
            offset = start + local
            warning_end = a['duration_seconds'] if vid == 'S7_26' and a['speech_boundary_method'] in ('api_timestamp_unreviewed', 'file_duration_conservative') else a['speech_end']
            speech[vid] = {'start': offset + a['speech_start'], 'end': offset + warning_end,
                           'file_start': offset, 'file_end': offset + a['duration_seconds']}
            manifest['audio'].append({'file': vid, 'offset': offset, 'duration': a['duration_seconds'],
                                      'sourceStart': 0, 'volume': 1})
            used.add(vid)
            captions = a.get('captions')
            need(isinstance(captions, list) and captions, 'Measured phrase captions required: ' + vid)
            last = 0
            for cap in captions:
                cs, ce = seconds(cap['start'], vid + ' caption'), seconds(cap['end'], vid + ' caption end')
                need(last <= cs < ce <= a['duration_seconds'], 'Caption timing invalid: ' + vid)
                need(isinstance(cap.get('text'), str) and len(cap['text']) <= 20,
                     'Supply measured single-line phrases <=20 characters: ' + vid)
                manifest['captions'].append({'start': offset + cs, 'end': offset + ce, 'text': cap['text']})
                last = ce
            if a.get('caption_method') == 'unaligned_equal_page_display_windows':
                need(inputs.get('unaligned_draft') is True, 'Unaligned captions require explicit draft mode')
            if a.get('caption_method') == 'api_timestamp_unreviewed':
                need(inputs.get('allow_unreviewed_asr') is True, 'Unreviewed captions require explicit preview mode')
            need(a.get('caption_method') in ('human_marked', 'api_timestamp_human_checked', 'api_timestamp_unreviewed', 'unaligned_equal_page_display_windows'),
                 'No character-count subtitle timing: ' + vid)
            local += a['duration_seconds'] + gap
        card = cards.get(bid)
        if card:
            # Reading estimate is visual layout only, never a speech timestamp.
            hold = max(hold, seconds(card['read_seconds'], bid + ' read_seconds', 1))
        end = up(start + max(local, hold))
        if bid == 'S7B03':
            # Cut to door on first impact; keep full source audio playing naturally.
            end = up(speech['S7_26']['end'] + .4)
        manifest['scenes'].append({'id': bid, 'start': start, 'end': end, 'image': image,
                                   'transition': {'kind': 'cut'}})
        if bid in inputs.get('card_only_beats', []):
            need(card is not None, 'Card-only beat needs explicit readable story card: ' + bid)
            scene = manifest['scenes'][-1]
            scene.pop('image')
            scene['layers'] = [{'image': image, 'x': 0, 'y': 0, 'width': 720, 'height': 1280, 'opacity': 0}]
        timeline[bid] = {'start': start, 'end': end}
        if card:
            manifest['story_overlays'].append(story(bid, start, end, card['lines']))
        if beat.get('missing_assets'):
            issues.append({'beat_id': bid, 'missing_assets_from_r06': beat['missing_assets'],
                           'action_status': 'still_only; continuous action not verified'})
        cursor = end
    # Explicit events only. Do not naively expand every repeated beat sound suggestion.
    events = inputs.get('sound_events', [])
    seen = set(); knock_count = 0; music_keys = set()
    for event in events:
        eid = event['id']; need(eid not in seen, 'Duplicate sound event ID'); seen.add(eid)
        key = event['asset_id']; need(key in catalog, 'Missing event asset: ' + key)
        a = catalog[key]; kind = a.get('kind'); need(kind in ('sfx', 'music'), 'Event must be sfx/music')
        check_asset(key, a, kind); used.add(key)
        anchor = event['anchor']; delay = seconds(event.get('delay', 0), eid + ' delay')
        if anchor['type'] == 'beat_start': offset = timeline[anchor['id']]['start'] + delay
        elif anchor['type'] == 'beat_end': offset = timeline[anchor['id']]['end'] + delay
        elif anchor['type'] == 'speech_end': offset = speech[anchor['id']]['end'] + delay
        else: raise ValueError('Unsupported explicit sound anchor')
        source = seconds(event.get('source_start', 0), eid + ' source')
        duration = seconds(event['duration'], eid + ' duration', .001)
        need(source + duration <= a['duration_seconds'] + 1e-6, 'Event slice exceeds real source: ' + eid)
        gain = event.get('volume', .15); need(isinstance(gain, (int, float)) and 0 <= gain <= 1, 'Invalid event gain')
        if key == 'F07':
            knock_count += 1
            need(anchor == {'type': 'speech_end', 'id': 'S7_26'} and delay == 0 and source == 0,
                 'F07 must start after full warning with original 0.40s first-impact offset')
            need(duration >= 4.4, 'F07 must retain all three knocks and tail')
            need(abs(a.get('first_impact_seconds', -1) - .4) < .001,
                 'Verified F07 first impact offset 0.40s required')
        if kind == 'music': music_keys.add(key)
        track = {'file': key, 'offset': offset, 'sourceStart': source, 'duration': duration, 'volume': gain}
        # Supported by the concurrently updated renderer; voices remain untouched.
        if kind == 'music' or event.get('role') == 'ambience':
            track['fadeIn'] = min(seconds(event.get('fade_in', .5), eid + ' fade in'), duration / 2)
            track['fadeOut'] = min(seconds(event.get('fade_out', .7), eid + ' fade out'), duration / 2)
        manifest['audio'].append(track)
    need(knock_count == 1, 'Exactly one explicit F07 three-knock event required')
    # Sound may extend past a beat but never silently truncate. Extend final static hold.
    audio_end = max(x['offset'] + x['duration'] for x in manifest['audio'])
    if audio_end > cursor:
        cursor = up(audio_end); manifest['scenes'][-1]['end'] = cursor
    # Final credit cards are separate readable stills; only credit actual music.
    credit_image = inputs.get('credit_image', (manifest['scenes'][-1].get('image') or manifest['scenes'][-1]['layers'][0]['image']))
    need(credit_image in catalog, 'Credit image missing'); check_asset(credit_image, catalog[credit_image], 'image'); used.add(credit_image)
    credits = []
    for key in sorted(music_keys):
        a = catalog[key]
        need(a.get('license') == 'CC BY 4.0' and a.get('attribution_lines') and a.get('attribution_text'),
             'Music needs verified license + exact credit text: ' + key)
        lines = a['attribution_lines']
        duration = max(5, seconds(a.get('credit_read_seconds', 6), key + ' credit hold'))
        end = up(cursor + duration)
        manifest['scenes'].append({'start': cursor, 'end': end, 'image': credit_image, 'transition': {'kind': 'cut'}})
        manifest['story_overlays'].append(story('credit_' + key, cursor, end, lines, 20))
        cursor = end; credits.append(a['attribution_text'])
    manifest['duration'] = cursor
    mapping = {k: {x: catalog[k][x] for x in ('path', 'sha256', 'drive_file_id')}
               | ({'authorized_for_this_draft': True} if catalog[k]['kind'] != 'image' else {}) for k in sorted(used)}
    need(len({v['path'] for v in mapping.values()}) == len(mapping), 'Duplicate mapped paths')
    renderer.plan(manifest)
    # Required visual evidence must be explicit curated readable cards, no machine self-report.
    all_lines = '\n'.join(line for c in manifest['story_overlays'] for line in c['lines'])
    for clue in ('03:09', '03:15', '妈，我没事', '灯别关', '三号柜后面', '是他', '别回头', '十二月九日', '城南水闸捞出', '妈，别开门'):
        need(clue in all_lines, 'Required visual clue missing: ' + clue)
    report = {'render_ready': True, 'meaning': 'structural timeline only; media and human review pending',
              'voice_speed': 1, 'caption_alignment': ('UNALIGNED draft page windows; NOT precise speech timestamps' if inputs.get('unaligned_draft') else 'explicit supplied phrase marks; not independently heard here'),
              'asr_review': 'unreviewed_preview' if inputs.get('allow_unreviewed_asr') else 'per_input_method',
              'human_audio_review': 'pending', 'silent_comprehension': 'pending', 'motion': 'still_only',
              'timeline': timeline, 'speech_anchors': speech, 'missing_shots': issues,
              'sfx_policy': 'explicit event instances; overlapping intentional; no beat auto-expansion',
              'mix_limitations': 'renderer fixed gain + optional edge fades; no dynamic ducking/loudness limiter; audition required',
              'music_attribution': credits}
    return manifest, mapping, report


def story(key, start, end, lines, font=27):
    need(isinstance(lines, list) and 1 <= len(lines) <= 4, '1-4 explicit story lines required')
    return {'id': key, 'start': start, 'end': end, 'x': 60, 'y': 160, 'width': 600,
            'height': 180, 'fontSize': font, 'lines': lines}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--plan', type=Path, default=HERE / 'edit_plan_r06.json')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--allow-unreviewed-asr', action='store_true', help='Explicit preview only: retain real ASR marks but human listening pending')
    p.add_argument('--allow-unaligned-draft', action='store_true', help='Explicitly use full-file conservative warning end and unsynchronized caption page windows')
    args = p.parse_args()
    try:
        need(not args.output.exists(), 'Output must be a new directory')
        inputs = json.loads(args.inputs.read_text())
        if args.allow_unaligned_draft: inputs = draft_page_marks(inputs)
        if args.allow_unreviewed_asr: inputs['allow_unreviewed_asr'] = True
        m, a, report = build(json.loads(args.plan.read_text()), inputs)
        args.output.mkdir(parents=True)
        for name, obj in [('manifest.json', m), ('asset-map.json', a), ('build-report.json', report),
                          ('bundle.json', {'manifest': m, 'assets': a})]:
            (args.output / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
        (args.output / 'CREDITS.txt').write_text('\n\n'.join(report['music_attribution']))
        print('Offline bundle built. Structural timeline validated; listening, image identity and silent review pending.')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit('Build stopped: ' + str(exc)) from None


if __name__ == '__main__':
    main()
