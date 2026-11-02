#!/usr/bin/env python3
"""Offline FFmpeg draft assembly. No generation APIs, models or implicit uploads."""
import argparse
import contextlib
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
import unicodedata

BLOCKED = {'result-4.wav', 'result-10.wav', '未命名.m4a'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(value, name, low=0, high=3600):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high, f'Invalid {name}')
    return value


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def blocked(name):
    base = Path(name).name.casefold()
    return base in BLOCKED or base.startswith('未命名')


def asset_references(manifest):
    refs = []
    for scene in manifest.get('scenes', []):
        for frame in scene.get('frames', []):
            refs.append((frame['image'], 'image'))
        for layer in scene.get('layers', []):
            refs.append((layer['image'], 'image'))
        if 'image' in scene:
            refs.append((scene['image'], 'image'))
    for track in manifest.get('audio', []):
        refs.append((track['file'], 'audio'))
    for source, kind in refs:
        require(not blocked(source), 'Forbidden reference/unnamed asset in manifest')
    return dict(refs)


def resolve_assets(manifest, mapping, root):
    """Map original logical paths; never fall back to /Users/... paths from a manifest."""
    root = root.resolve()
    result = {}
    for source, kind in asset_references(manifest).items():
        entry = mapping.get(source)
        require(isinstance(entry, dict), f'Missing asset mapping: {source}')
        require(not blocked(entry.get('path', '')), 'Forbidden mapped filename')
        require(kind != 'audio' or entry.get('authorized_for_this_draft') is True,
                f'Audio needs current draft authorization: {source}')
        relative = Path(entry['path'])
        require(not relative.is_absolute(), 'Asset map paths must be relative')
        candidate = root / relative
        require('..' not in relative.parts, 'Asset path traversal forbidden')
        for component in (candidate, *candidate.parents):
            if component == root:
                break
            require(not component.is_symlink(), 'Symlinks forbidden in asset paths')
        path = candidate.resolve()
        require(not blocked(path.name), 'Forbidden resolved filename')
        require(path.is_relative_to(root) and path.is_file(), 'Asset missing or outside asset root')
        sha = entry.get('sha256', '')
        require(len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'SHA256 required')
        require(digest(path) == sha, 'Asset SHA256 mismatch')
        result[source] = path
    return result


def plan(manifest):
    m = manifest
    duration = number(m['duration'], 'duration', 0.04)
    fps = number(m.get('fps', 25), 'fps', 1, 60)
    require(int(fps) == fps, 'Integer fps required')
    w, h = m.get('width', 720), m.get('height', 1280)
    require(all(isinstance(x, int) and 320 <= x <= 4096 and x % 2 == 0 for x in (w, h)), 'Invalid dimensions')
    def frame(t):
        number(t, 'timeline')
        require(abs(t * fps - round(t * fps)) < 0.001, 'Visual timeline must align to video frames')
        return round(t * fps)
    frame(duration)
    shots, cursor = [], 0
    for scene in m['scenes']:
        start, end = scene['start'], scene['end']
        require(frame(start) == cursor and frame(end) > cursor, 'Scenes must cover timeline without gaps')
        length = end - start
        require(not any(k in scene for k in ('light', 'motion')), 'Motion/light unsupported; use explicit still shots')
        require(scene.get('transition', {'kind': 'cut'}) == {'kind': 'cut'}, 'Only hard cuts supported')
        if scene.get('frames'):
            require(not scene.get('layers') and 'image' not in scene, 'Mixed frame/layer scenes unsupported')
            inner = 0
            for shot in scene['frames']:
                require(frame(shot['start']) == inner and frame(shot['end']) > inner, 'Frame coverage gap/overlap')
                require(not shot.get('dissolve', 0), 'Dissolve unsupported')
                shots.append({'image': shot['image'], 'start': start + shot['start'],
                              'end': start + shot['end'], 'crop': None, 'opacity': 1, 'fit': 'cover'})
                inner = frame(shot['end'])
            require(inner == frame(length), 'Frame sequence does not cover scene')
        elif scene.get('layers'):
            require(len(scene['layers']) == 1 and 'image' not in scene, 'Only one full-canvas static layer supported')
            layer = scene['layers'][0]
            require((layer.get('x'), layer.get('y'), layer.get('width'), layer.get('height')) == (0, 0, w, h),
                    'Layer must cover full canvas')
            require(not any(k in layer for k in ('from', 'to')) and layer.get('scale', 1) == 1, 'Moving layers unsupported')
            crop = layer.get('crop')
            if crop:
                for k in ('x', 'y', 'width', 'height'):
                    number(crop[k], 'crop.' + k, 0, 1)
                require(crop['width'] > 0 and crop['height'] > 0 and crop['x'] + crop['width'] <= 1
                        and crop['y'] + crop['height'] <= 1, 'Invalid crop rectangle')
            shots.append({'image': layer['image'], 'start': start, 'end': end, 'crop': crop,
                          'opacity': number(layer.get('opacity', 1), 'opacity', 0, 1), 'fit': 'stretch'})
        else:
            require('image' in scene, 'Scene has no image')
            shots.append({'image': scene['image'], 'start': start, 'end': end, 'crop': None, 'opacity': 1, 'fit': 'cover'})
        cursor = frame(end)
    require(cursor == frame(duration) and len(shots) >= 2, 'Need complete timeline and at least two shots')
    last = 0
    for caption in m.get('captions', []):
        text = caption['text']
        require(isinstance(text, str) and text.strip() and not any(c in text for c in '\r\n{}\\'),
                'Caption must be a single plain-text line')
        s, e = number(caption['start'], 'caption start'), number(caption['end'], 'caption end')
        require(last <= s < e <= duration, 'Caption overlap/out of range')
        require(round(s * 100) < round(e * 100), 'Caption disappears at ASS centisecond precision')
        last = e
    require(m.get('audio'), 'Draft must include explicitly authorized audio')
    for track in m['audio']:
        s = number(track['offset'], 'audio offset')
        number(track.get('sourceStart', 0), 'audio source start')
        d = number(track['duration'], 'audio duration', 0.001)
        number(track.get('volume', 1), 'audio volume', 0, 4)
        require(s + d <= duration + 0.00001, 'Audio exceeds video duration')
    badge = m.get('badge', '')
    require('AI' in badge and len(badge) <= 40 and not any(c in badge for c in '\r\n{}\\'), 'Visible AI badge required')
    font_size = number(m.get('fontSize', 29), 'fontSize', 8, 200)
    inset = number(m.get('safeInset', 54), 'safeInset', 0, w / 3)
    bottom = number(m.get('captionBottom', h * .2), 'captionBottom', h * .18, h * .7)
    require(bottom + font_size * 2 < h, 'Caption outside canvas')
    p = {'duration': duration, 'width': w, 'height': h, 'fps': int(fps), 'shots': shots,
         'font_size': font_size, 'inset': inset, 'caption_bottom': bottom}
    p['story_overlays'] = plan_story_overlays(m.get('story_overlays', []), p)
    return p


def plain_story_line(text):
    return (isinstance(text, str) and bool(text.strip()) and len(text) <= 60
            and not any(c in '{}\\' or unicodedata.category(c).startswith('C')
                        or unicodedata.category(c) in ('Zl', 'Zp') for c in text))


def plan_story_overlays(cues, p):
    require(isinstance(cues, list) and len(cues) <= 32, 'At most 32 story cards allowed')
    result, identifiers = [], set()
    # Coordinates use top-left origin. Reserve badge top and the entire lower
    # caption/platform band; this stays reserved even when no caption is visible.
    top = max(80, 40 + max(12, round(p['font_size'] * .65)) * 2)
    bottom = math.floor(p['height'] - p['caption_bottom'] - p['font_size'] * 3)
    for cue in cues:
        require(isinstance(cue, dict) and set(cue) <=
                {'id', 'start', 'end', 'x', 'y', 'width', 'height', 'fontSize', 'lines'}, 'Unknown story card field')
        identifier = cue.get('id', '')
        require(isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', identifier)
                and identifier not in identifiers, 'Story card needs a unique plain ID')
        identifiers.add(identifier)
        start = number(cue['start'], 'story start', 0, p['duration'])
        end = number(cue['end'], 'story end', 0, p['duration'])
        require(start < end and all(abs(t * p['fps'] - round(t * p['fps'])) < .001 for t in (start, end)),
                'Story timing must be nonempty and frame aligned')
        rect = [cue.get(k) for k in ('x', 'y', 'width', 'height')]
        require(all(isinstance(v, int) and not isinstance(v, bool) for v in rect), 'Story rectangle needs integer pixels')
        x, y, width, height = rect
        require(width > 0 and height > 0 and p['inset'] <= x and x + width <= p['width'] - p['inset']
                and top <= y and y + height <= bottom, 'Story card intersects reserved safe area or leaves canvas')
        require(width * height <= p['width'] * p['height'] * .35, 'Story card too large')
        lines = cue.get('lines')
        require(isinstance(lines, list) and 1 <= len(lines) <= 4 and all(plain_story_line(line) for line in lines),
                'Story card needs 1-4 short plain lines without controls')
        size = cue.get('fontSize', max(16, round(p['font_size'])))
        require(isinstance(size, int) and not isinstance(size, bool) and 12 <= size <= 100, 'Invalid story font size')
        planned = dict(cue, fontSize=size, start_frame=round(start * p['fps']), end_frame_exclusive=round(end * p['fps']))
        for other in result:
            time_overlap = start < other['end'] and end > other['start']
            space_overlap = (x < other['x'] + other['width'] and x + width > other['x']
                             and y < other['y'] + other['height'] and y + height > other['y'])
            require(not (time_overlap and space_overlap), 'Simultaneous story cards must not cover each other')
        result.append(planned)
    return result


def story_layout(cue, font):
    padding = max(8, cue['fontSize'] // 2)
    gap = max(4, cue['fontSize'] // 4)
    boxes = [font.getbbox(line) for line in cue['lines']]
    heights = [b[3] - b[1] for b in boxes]
    require(all(max(font.getlength(line), box[2] - box[0]) <= cue['width'] - 2 * padding
                for line, box in zip(cue['lines'], boxes)), 'Story text too wide; shorten the explicit text')
    require(sum(heights) + gap * (len(boxes) - 1) <= cue['height'] - 2 * padding,
            'Story text too tall; change the explicit card layout')
    positions, y = [], padding
    for box, height in zip(boxes, heights):
        positions.append((padding - box[0], y - box[1]))
        y += height + gap
    return positions


def write_story_cards(p, font_path, directory):
    from PIL import Image, ImageDraw, ImageFont
    cards = []
    for i, cue in enumerate(p['story_overlays']):
        font = ImageFont.truetype(str(font_path), cue['fontSize'])
        positions = story_layout(cue, font)
        image = Image.new('RGBA', (cue['width'], cue['height']), (12, 16, 20, 248))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, cue['width'] - 1, cue['height'] - 1), outline=(242, 190, 72, 255), width=2)
        for text, position in zip(cue['lines'], positions):
            draw.text(position, text, font=font, fill=(255, 255, 255, 255))
        path = directory / f'story-{i}.png'
        image.save(path)
        cards.append(path)
    return cards


def final_filter(p):
    filters, current = ['[0:v]setpts=PTS-STARTPTS[base]'], 'base'
    for i, cue in enumerate(p['story_overlays']):
        filters.append(f'[{i + 2}:v]format=rgba,setpts=PTS-STARTPTS[card{i}]')
        filters.append(f"[{current}][card{i}]overlay=x={cue['x']}:y={cue['y']}:format=auto:alpha=straight:"
                       f"shortest=1:enable='gte(n,{cue['start_frame']})*lt(n,{cue['end_frame_exclusive']})'[story{i}]")
        current = f'story{i}'
    filters.append(f'[{current}]ass=captions.ass:fontsdir=fonts,format=yuv420p[out]')
    return ';\n'.join(filters)



def ass_time(t):
    centi = round(t * 100)
    return f'{centi // 360000}:{centi // 6000 % 60:02}:{centi // 100 % 60:02}.{centi % 100:02}'


def write_ass(m, p, font_path, target):
    from PIL import ImageFont
    font = ImageFont.truetype(str(font_path), round(p['font_size']))
    badge_size = max(12, round(p['font_size'] * .65))
    badge_font = ImageFont.truetype(str(font_path), badge_size)
    family = font.getname()[0]
    require(all(font.getlength(c['text']) <= p['width'] - 2 * p['inset'] for c in m.get('captions', [])),
            'Caption too wide; split against real audio timing before rendering')
    require(badge_font.getlength(m['badge']) <= p['width'] - 2 * p['inset'], 'AI badge too wide')
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {p['width']}
PlayResY: {p['height']}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{family},{p['font_size']},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,2,{p['inset']},{p['inset']},{p['caption_bottom']},1
Style: Badge,{family},{badge_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,1,1,8,{p['inset']},{p['inset']},40,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = [f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Caption,,0,0,0,,{c['text']}" for c in m.get('captions', [])]
    events.append(f"Dialogue: 1,0:00:00.00,{ass_time(p['duration'])},Badge,,0,0,0,,{m['badge']}")
    target.write_text(header + '\n'.join(events) + '\n', encoding='utf-8')


def run(args, cwd=None):
    # Never print commands, paths or service responses; no shell interpolation.
    r = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(r.returncode == 0, f'{Path(args[0]).name} failed (diagnostics withheld; inspect local inputs)')
    return r.stdout


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))


def qc(path, p):
    data = probe(path)
    video = [s for s in data['streams'] if s['codec_type'] == 'video']
    audio = [s for s in data['streams'] if s['codec_type'] == 'audio']
    require(len(video) == len(audio) == 1, 'Expected one video and one audio stream')
    v, a = video[0], audio[0]
    require((v['codec_name'], v['width'], v['height'], v['pix_fmt']) ==
            ('h264', p['width'], p['height'], 'yuv420p'), 'Video encoding mismatch')
    require(a['codec_name'] == 'aac', 'Expected AAC')
    require(abs(float(data['format']['duration']) - p['duration']) < .1, 'Container duration mismatch')
    for stream in (v, a):
        require(abs(float(stream.get('start_time', 0))) < .1, 'Stream start mismatch')
        require(abs(float(stream['duration']) - p['duration']) < .1, 'Stream duration mismatch')
    require(v['avg_frame_rate'] == f"{p['fps']}/1", 'Frame rate mismatch')
    count = int(v.get('nb_frames', 0))
    require(count == round(p['duration'] * p['fps']), 'Video frame count mismatch')
    # Decode entire result. Metadata alone is not a successful decoding test.
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'])
    return {'structural_pass': True, 'decoded_to_end': True, 'video_frames': count,
            'video_duration': float(v['duration']), 'audio_duration': float(a['duration']),
            'width': v['width'], 'height': v['height'], 'codecs': ['h264', 'aac'],
            'human_visual_and_listening_review': 'pending', 'voice_acceptance': 'not_assessed'}


def shot_filter(shot, p):
    # Preserve source alpha through crop/scale. Layer rectangles stretch the entire
    # cropped source; frame/image backgrounds retain centered aspect-fill semantics.
    foreground = ['format=rgba']
    crop = shot['crop']
    if crop:
        foreground.append(f"crop=iw*{crop['width']}:ih*{crop['height']}:iw*{crop['x']}:ih*{crop['y']}")
    if shot['fit'] == 'stretch':
        foreground.append(f"scale={p['width']}:{p['height']}")
    else:
        foreground += [f"scale={p['width']}:{p['height']}:force_original_aspect_ratio=increase",
                       f"crop={p['width']}:{p['height']}"]
    foreground += ['setsar=1', 'format=rgba', f"colorchannelmixer=aa={shot['opacity']}"]
    return ('[0:v]' + ','.join(foreground) + '[foreground];'
            f"color=c=black:s={p['width']}x{p['height']}:r={p['fps']},format=rgba[black];"
            '[black][foreground]overlay=0:0:format=auto:alpha=straight:shortest=1,'
            'format=yuv420p[out]')


def encode_shot(image, shot, p, output, work):
    run(['ffmpeg', '-v', 'error', '-nostdin', '-loop', '1', '-framerate', str(p['fps']),
         '-i', str(image), '-filter_complex_threads', '1', '-filter_complex', shot_filter(shot, p),
         '-map', '[out]', '-frames:v', str(round((shot['end'] - shot['start']) * p['fps'])),
         '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '2', str(output)], work)


def render(m, assets, output_dir, font):
    p = plan(m)
    require(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg and ffprobe required')
    require(font.is_file(), 'CJK font file required')
    require(not output_dir.exists(), 'Output directory must not already exist')
    output_dir.mkdir(parents=True)
    with contextlib.nullcontext(tempfile.mkdtemp(prefix='ep01-render-')) as temporary:
        work = Path(temporary)
        write_ass(m, p, font, work / 'captions.ass')
        # A private work directory also makes filter paths independent of user filenames.
        for i, shot in enumerate(p['shots']):
            image = work / f'input-{i}{assets[shot["image"]].suffix}'
            image.symlink_to(assets[shot['image']])
            encode_shot(image.name, shot, p, f'shot-{i}.mp4', work)
        (work / 'concat.txt').write_text(''.join(f"file 'shot-{i}.mp4'\n" for i in range(len(p['shots']))))
        run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-i', 'concat.txt',
             '-c', 'copy', 'picture.mp4'], work)
        args = ['ffmpeg', '-v', 'error', '-nostdin']
        filters, labels, tracks_report = [], [], []
        for i, track in enumerate(m['audio']):
            source = assets[track['file']]
            streams = [s for s in probe(source)['streams'] if s['codec_type'] == 'audio']
            require(len(streams) == 1, 'Source must have exactly one audio stream')
            source_duration = float(streams[0].get('duration', probe(source)['format']['duration']))
            start, length = track.get('sourceStart', 0), track['duration']
            require(start + length <= source_duration + .01, 'Audio slice exceeds source; no silent truncation')
            args += ['-i', str(source)]
            delay = round(track['offset'] * 48000)
            filters.append(f'[{i}:a]atrim=start={start}:duration={length},asetpts=PTS-STARTPTS,'
                           f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={track.get('volume', 1)},"
                           f'adelay={delay}S:all=1[a{i}]')
            labels.append(f'[a{i}]')
            tracks_report.append({'index': i, 'source_sha256': digest(source), 'source_duration': source_duration,
                                  'source_start': start, 'duration': length, 'offset': track['offset'], 'speed': 1})
        filters.append(''.join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
                       f"apad,atrim=duration={p['duration']}[mix]")
        (work / 'audio.filters').write_text(';\n'.join(filters))
        run(args + ['-filter_complex_script', 'audio.filters', '-map', '[mix]', '-c:a', 'pcm_s24le', 'mix.wav'], work)
        # Subtitle filename is fixed and safe; fontsdir ensures the measured CJK family is installed for libass.
        (work / 'fonts').mkdir()
        shutil.copyfile(font, work / 'fonts' / font.name)
        cards = write_story_cards(p, font, work)
        candidate = work / 'draft.mp4'
        final_inputs = ['ffmpeg', '-v', 'error', '-nostdin', '-i', 'picture.mp4', '-i', 'mix.wav']
        for card in cards:
            final_inputs += ['-loop', '1', '-framerate', str(p['fps']), '-i', card.name]
        (work / 'final.filters').write_text(final_filter(p))
        if cards:
            filter_options = ['-filter_complex_threads', '1', '-filter_complex_script', 'final.filters',
                              '-map', '[out]', '-map', '1:a']
        else:
            # Preserve the already exercised no-card path for existing manifests.
            filter_options = ['-map', '0:v', '-map', '1:a', '-vf', 'ass=captions.ass:fontsdir=fonts']
        run(final_inputs + filter_options + ['-t', str(p['duration']), '-c:v', 'libx264', '-preset', 'fast',
             '-crf', '18', '-pix_fmt', 'yuv420p', '-threads', '2', '-c:a', 'aac', '-b:a', '192k',
             '-movflags', '+faststart', candidate.name], work)
        report = qc(candidate, p)
        report['source_tracks'] = tracks_report
        report['shot_timeline'] = [{k: s[k] for k in ('start', 'end')} for s in p['shots']]
        report['caption_timeline'] = m.get('captions', [])
        report['story_overlay_timeline'] = [dict(cue, png_sha256=digest(card))
                                            for cue, card in zip(p['story_overlays'], cards)]
        report['silent_story_comprehension'] = 'not_assessed'
        if cards:
            (output_dir / 'story-cards').mkdir()
            for card in cards:
                shutil.copyfile(card, output_dir / 'story-cards' / card.name)
        report['output_sha256'] = digest(candidate)
        shutil.copyfile(candidate, output_dir / 'draft.mp4')
        shutil.copyfile(work / 'captions.ass', output_dir / 'captions.ass')
        (output_dir / 'qc.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--asset-map', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        assets = resolve_assets(manifest, json.loads(args.asset_map.read_text()), args.asset_root)
        p = plan(manifest)
        if args.validate_only:
            print(json.dumps({'timeline_valid': True, 'shots': len(p['shots']), 'duration': p['duration'],
                              'media_decoding': 'not_run', 'font_layout': 'not_run'}))
        else:
            render(manifest, assets, args.output_dir.resolve(), args.font.resolve())
            print('Draft rendered; structural QC passed. Human review pending.')
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as e:
        raise SystemExit(f'Render stopped: {e}') from None


if __name__ == '__main__':
    main()
