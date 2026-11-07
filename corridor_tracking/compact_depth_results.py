"""Create a separately verified, portable replay archive without copying intermediate depth."""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil

from corridor_tracking.depth_person_comparison import load_run
from corridor_tracking.portable_depth_replay import joined_frames, update_index
from depth_person_prototype import digest, safe_asset

TAG = re.compile(r'^g(002|003)_(recording_\d{3})_([A-Za-z0-9_]+)$')


def copy_verified(source, dest, expected=None):
    expected = expected or digest(source)
    if digest(source) != expected:
        raise ValueError(f'source changed or hash mismatch: {source}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f'destination already exists: {dest}')
    shutil.copyfile(source, dest)
    if digest(dest) != expected:
        raise OSError(f'copied file differs: {dest}')
    return expected


def compact_one(source, bundle, output, tag, rows):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f'invalid tag: {tag}')
    group, recording = int(match.group(1)), match.group(2)
    matches = [row for row in rows if row['group'] == str(group) and row['recording'] == recording]
    if len(matches) != 1:
        raise ValueError(f'inventory row missing or duplicated: {tag}')
    row = matches[0]
    merged = source/'analysis'/tag/'merged'
    coords = source/'coordinates'/tag
    coord_file, coord_manifest = coords/'positions.json', coords/'manifest.json'
    if {p.name for p in coords.iterdir()} != {'positions.json', 'manifest.json'}:
        raise ValueError(f'coordinate files incomplete or unexpected: {tag}')
    cm = json.loads(coord_manifest.read_text(encoding='utf-8-sig'))
    if cm.get('status') != 'complete' or digest(coord_file) != cm.get('positions_sha256'):
        raise ValueError(f'coordinate hash or completion failed: {tag}')
    positions = json.loads(coord_file.read_text(encoding='utf-8-sig'))
    metadata = positions['metadata']
    for key in ('recording', 'source_svo_sha256', 'setup_id', 'calibration_sha256', 'body_manifest_sha256'):
        if metadata.get(key) != row[key]:
            raise ValueError(f'coordinate provenance differs for {tag}: {key}')
    if str(metadata.get('group')) != str(group) or digest(merged/'manifest.json') != metadata.get('person_run_manifest_sha256'):
        raise ValueError(f'coordinate group or source person manifest differs: {tag}')
    person = load_run(merged)
    if person['metadata'].get('source_svo_sha256') != row['source_svo_sha256'] or person['metadata'].get('calibration_sha256') != row['calibration_sha256']:
        raise ValueError(f'person output provenance differs: {tag}')
    frames = joined_frames(person['frames'], positions['frames'])
    if len(frames) != int(row['frame_count']):
        raise ValueError(f'incomplete recording: {tag}')
    manifest = json.loads((merged/'manifest.json').read_text(encoding='utf-8-sig'))
    assets = manifest['files_sha256']
    for frame in frames:
        if frame['review_image'] not in assets:
            raise ValueError(f'replay image missing from manifest: {tag}/{frame["review_image"]}')
    replay = merged/'portable_replay.html'
    replay_record_file = merged/'portable_replay_manifest.json'
    replay_record = json.loads(replay_record_file.read_text(encoding='utf-8-sig'))
    if (replay_record.get('status') != 'complete' or replay_record.get('replay_sha256') != digest(replay)
            or replay_record.get('positions_sha256') != digest(coord_file)
            or replay_record.get('person_manifest_sha256') != digest(merged/'manifest.json')
            or replay_record.get('frame_count') != len(frames)):
        raise ValueError(f'replay metadata mismatch: {tag}')
    cal = safe_asset(bundle, row['calibration'])
    timeline = safe_asset(bundle, row['timeline'])
    if digest(cal) != row['calibration_sha256']:
        raise ValueError(f'calibration differs: {tag}')
    timeline_json = json.loads(timeline.read_text(encoding='utf-8-sig'))
    if timeline_json.get('body_manifest_sha256') != row['body_manifest_sha256'] or len(timeline_json.get('frames', [])) != int(row['frame_count']):
        raise ValueError(f'timeline differs: {tag}')
    for observed, expected in zip(positions['frames'], timeline_json['frames']):
        if (str(observed['frame_index']) != str(expected['frame_index']) or
                str(observed['timestamp_ns']) != str(expected['image_timestamp_ns'])):
            raise ValueError(f'coordinate and original timeline differ: {tag}')
    destination = output/'analysis'/tag/'merged'
    for name, expected in assets.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError(f'unsafe manifest path: {name}')
        copy_verified(safe_asset(merged, name), destination/name, expected)
    copy_verified(merged/'manifest.json', destination/'manifest.json')
    copy_verified(replay, destination/replay.name, replay_record['replay_sha256'])
    copy_verified(replay_record_file, destination/replay_record_file.name)
    candidate = merged/'portable_candidate_replay.html'
    candidate_record = merged/'portable_candidate_replay_manifest.json'
    if candidate.exists() or candidate_record.exists():
        if not candidate.is_file() or not candidate_record.is_file():
            raise ValueError(f'incomplete candidate replay: {tag}')
        cr = json.loads(candidate_record.read_text(encoding='utf-8-sig'))
        if cr.get('status') != 'complete' or cr.get('replay_sha256') != digest(candidate) or cr.get('person_manifest_sha256') != digest(merged/'manifest.json'):
            raise ValueError(f'candidate replay mismatch: {tag}')
        copy_verified(candidate, destination/candidate.name, cr['replay_sha256'])
        copy_verified(candidate_record, destination/candidate_record.name)
    copy_verified(coord_file, output/'coordinates'/tag/'positions.json', cm['positions_sha256'])
    copy_verified(coord_manifest, output/'coordinates'/tag/'manifest.json')
    copy_verified(cal, output/'calibrations'/f'{tag}.json', row['calibration_sha256'])
    copy_verified(timeline, output/'timelines'/f'{tag}.json')
    for name in ('timing.json',):
        path = source/'analysis'/tag/name
        if path.is_file():
            copy_verified(path, output/'analysis'/tag/name)
    for path in sorted((source/'analysis'/tag).glob('alignment_*.json')):
        copy_verified(path, output/'analysis'/tag/path.name)
    clip_records = []
    clip_pattern = re.compile(re.escape(tag) + r'_\d{6}_\d{6}$')
    clips_root = source/'depth_clips'
    for clip in sorted(clips_root.glob(tag + '_*')) if clips_root.is_dir() else []:
        if not clip.is_dir() or not clip_pattern.fullmatch(clip.name):
            continue
        names = ('batch_summary.json', 'export.log', 'validation.log', 'depth/camera.json', 'depth/frames.csv', 'depth/manifest.json')
        present = []
        for name in names:
            path = clip/name
            if path.is_file():
                copy_verified(path, output/'depth_clip_records'/clip.name/name)
                present.append(name)
        clip_records.append({'clip': clip.name, 'files': present, 'metadata_complete': len(present) == len(names)})
    copied_person = load_run(destination)
    joined_frames(copied_person['frames'], positions['frames'])
    return {'tag': tag, 'frame_count': len(frames), 'source_svo_path': row['svo_path'],
            'source_svo_sha256': row['source_svo_sha256'], 'calibration_sha256': row['calibration_sha256'],
            'body_manifest_sha256': row['body_manifest_sha256'], 'setup_id': row['setup_id'],
            'person_manifest_sha256': digest(destination/'manifest.json'),
            'replay_sha256': replay_record['replay_sha256'], 'positions_sha256': cm['positions_sha256'],
            'candidate_replay_included': candidate.is_file(), 'clip_metadata': clip_records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--tag', action='append', help='specific completed tag; repeat for more recordings')
    choice.add_argument('--all-complete', action='store_true', help='include recordings whose local replay is complete')
    a = parser.parse_args()
    source, bundle, output = a.source.resolve(), a.bundle.resolve(), a.output.resolve()
    if source == output or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error('output must be a new folder outside the source tree')
    if output.exists():
        parser.error('output already exists; choose a new folder')
    if not (source/'coordinates').is_dir() or not (source/'analysis').is_dir():
        parser.error('source must contain the original coordinates and analysis folders')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if a.all_complete:
        tags = sorted(p.name for p in (source/'coordinates').iterdir() if p.is_dir() and TAG.fullmatch(p.name)
                      and (source/'analysis'/p.name/'merged'/'portable_replay_manifest.json').is_file())
    else:
        tags = a.tag
    if not tags or len(tags) != len(set(tags)) or any(not TAG.fullmatch(tag) for tag in tags):
        parser.error('no completed recordings or invalid/duplicated tags')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for tag in tags:
        print(f'[Compact] Validating and copying {tag}', flush=True)
        records.append(compact_one(source, bundle, output, tag, rows))
    update_index(output)
    files = sorted(p for p in output.rglob('*') if p.is_file())
    hashes = {p.relative_to(output).as_posix(): digest(p) for p in files}
    report = {'status': 'complete', 'recording_count': len(records), 'recordings': records,
              'files_sha256': hashes, 'total_bytes': sum(p.stat().st_size for p in files),
              'scope': 'portable replay, merged person results and masks, positions, calibration, timeline, clip metadata and provenance',
              'excluded': ['SVO originals', 'per-clip depth point archives and source images', 'per-part duplicate outputs', 'benchmark data'],
              'limits': ['Source results were not deleted or changed.', 'Exact depth points require the original archives; regeneration from SVO requires ZED SDK and is not guaranteed bit-identical.', 'Candidate replay pages are retained when present; external candidate coordinate packets are not collected.']}
    (output/'compact_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'[Compact] {len(records)} recordings; {report["total_bytes"]/1e9:.2f} GB at {output}', flush=True)
    print('[Compact] The original analysis was not modified. Verify this replay before considering any cleanup.', flush=True)


if __name__ == '__main__':
    main()
