"""Publish a separate, checked corridor-limited copy of positions and ID proposals."""
import argparse
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.prepare_group004_005_bundle import scope_calibration
from corridor_tracking.spatial_filter import corridor_bounds, filter_frames
from depth_person_prototype import digest


def read_packet(folder, status):
    if {p.name for p in folder.iterdir()} != {'positions.json', 'manifest.json'}:
        raise ValueError(f'unexpected coordinate files: {folder}')
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('status') != status or manifest.get('positions_sha256') != digest(folder/'positions.json'):
        raise ValueError(f'invalid coordinate packet: {folder}')
    return json.loads((folder/'positions.json').read_text(encoding='utf-8-sig')), manifest


def validate_frames(data, manifest):
    frames = data['frames']
    if not frames or len(frames) != manifest['frame_count'] or [f['frame_index'] for f in frames] != list(range(len(frames))):
        raise ValueError('recording frames missing or unordered')
    if any(int(b['timestamp_ns']) <= int(a['timestamp_ns']) or b['elapsed_s'] <= a['elapsed_s'] for a,b in zip(frames,frames[1:])):
        raise ValueError('non-monotonic timeline')


def save_packet(output, payload, record):
    if output.exists():
        old = json.loads((output/'manifest.json').read_text(encoding='utf-8-sig'))
        if (old.get('source_positions_sha256') != record['source_positions_sha256'] or
                old.get('bounds') != record['bounds'] or old.get('positions_sha256') != digest(output/'positions.json') or
                old.get('status') != record['status'] or old.get('source_candidate_sha256') != record.get('source_candidate_sha256')):
            raise ValueError(f'existing filtered result differs: {output}')
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name('.'+output.name+'.partial-'+uuid.uuid4().hex[:12])
    temp.mkdir()
    (temp/'positions.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    record['positions_sha256'] = digest(temp/'positions.json')
    (temp/'manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.rename(output)
    return True


def filter_original(source, output, bounds, expected_setup, expected_bundle=None, group4_row=None, template=None, calibration=None, cal_path=None):
    data, manifest = read_packet(source, 'complete')
    validate_frames(data, manifest)
    meta = data['metadata']
    if meta.get('setup_id') != expected_setup or str(meta.get('group')) not in ('4','5'):
        raise ValueError(f'setup or group mismatch: {source}')
    if str(meta['group']) == '5' and meta.get('bundle_manifest_sha256') != expected_bundle:
        raise ValueError(f'group 5 not from the known group 4/5 batch: {source}')
    if (meta.get('source_svo_sha256') != manifest.get('source_svo_sha256') or
            meta.get('recording') != manifest.get('recording') or meta.get('group') != manifest.get('group')):
        raise ValueError(f'source metadata differs: {source}')
    if str(meta['group']) == '4':
        if not group4_row or meta['recording'] != group4_row['recording']:
            raise ValueError('group 4 recording is missing from verified inventory')
        for key in ('source_svo_sha256', 'setup_id', 'body_manifest_sha256'):
            if meta.get(key) != group4_row[key]:
                raise ValueError(f'group 4 source mismatch: {key}')
        timeline = json.loads((template/group4_row['timeline']).read_text(encoding='utf-8'))
        if len(data['frames']) != len(timeline['frames']) or any(
                str(f['timestamp_ns']) != t['image_timestamp_ns'] or int(f['frame_index']) != int(t['frame_index'])
                for f,t in zip(data['frames'], timeline['frames'])):
            raise ValueError('group 4 source timeline mismatch')
        scoped = scope_calibration(calibration, timeline['camera'], digest(cal_path))
        raw = cal_path.read_bytes() if scoped is None else (json.dumps(scoped, ensure_ascii=False, indent=2, allow_nan=False)+'\n').replace('\n','\r\n').encode('utf-8')
        if hashlib.sha256(raw).hexdigest() != meta.get('calibration_sha256'):
            raise ValueError('group 4 scoped calibration hash mismatch')
    frames, _, stats = filter_frames(data['frames'], bounds)
    result = copy.deepcopy(data)
    result['frames'] = frames
    result['walls'] = {'visible': bounds['visible_wall_y_m'], 'opposite': bounds['opposite_wall_y_m']}
    result['spatial_filter'] = {'bounds': bounds, 'source_positions_sha256': digest(source/'positions.json'),
                                'source_manifest_sha256': digest(source/'manifest.json'), 'counts': stats,
                                'position_semantics': 'bounds apply to measured visible surface, not true person centre',
                                'calibration': 'provisional floor/wall; group 4/5 assumed same corridor width and camera pose'}
    record = {'status': 'complete', 'source_positions_sha256': digest(source/'positions.json'),
              'source_manifest_sha256': digest(source/'manifest.json'), 'bounds': bounds, 'counts': stats,
              'group': meta['group'], 'recording': meta['recording'], 'frame_count': len(frames),
              'allowed_files': ['positions.json', 'manifest.json']}
    created = save_packet(output, result, record)
    return created, stats


def filter_candidate(source_original, source_candidate, filtered_original, output, bounds):
    original, orig_manifest = read_packet(source_original, 'complete')
    candidate, candidate_manifest = read_packet(source_candidate, 'proposed_not_verified')
    validate_frames(original, orig_manifest)
    if candidate_manifest.get('source_positions_sha256') != digest(source_original/'positions.json'):
        raise ValueError('candidate does not reference source original')
    if validate_candidate(original, candidate, digest(source_original/'positions.json')) != candidate_manifest.get('proposed_count'):
        raise ValueError('candidate count differs')
    filtered, fm = read_packet(filtered_original, 'complete')
    if fm.get('source_positions_sha256') != digest(source_original/'positions.json') or fm.get('bounds') != bounds:
        raise ValueError('filtered original does not match candidate source/bounds')
    frames, _, stats = filter_frames(candidate['frames'], bounds)
    result = copy.deepcopy(candidate)
    result['frames'] = frames
    result['walls'] = {'visible': bounds['visible_wall_y_m'], 'opposite': bounds['opposite_wall_y_m']}
    result['spatial_filter'] = copy.deepcopy(filtered['spatial_filter'])
    result['spatial_filter']['candidate_source_positions_sha256'] = digest(source_candidate/'positions.json')
    result['reassignment_candidate']['source_positions_sha256'] = digest(filtered_original/'positions.json')
    try:
        changes = validate_candidate(filtered, result, digest(filtered_original/'positions.json'))
    except ValueError as exc:
        if str(exc) == 'candidate has no proposed assignments':
            return False, 0
        raise
    record = {'status': 'proposed_not_verified', 'source_positions_sha256': digest(filtered_original/'positions.json'),
              'source_candidate_sha256': digest(source_candidate/'positions.json'), 'bounds': bounds, 'counts': stats,
              'proposed_count': changes, 'group': original['metadata']['group'], 'recording': original['metadata']['recording'],
              'frame_count': len(frames), 'allowed_files': ['positions.json', 'manifest.json']}
    created = save_packet(output, result, record)
    return created, changes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', required=True, type=Path)
    p.add_argument('--candidate-root', required=True, type=Path)
    p.add_argument('--output-root', required=True, type=Path)
    p.add_argument('--calibration', required=True, type=Path)
    p.add_argument('--group4-template', required=True, type=Path)
    p.add_argument('--fallback-width-m', type=float, required=True)
    p.add_argument('--expected-bundle-sha256', required=True)
    p.add_argument('--watch', action='store_true')
    p.add_argument('--interval-seconds', type=float, default=180.)
    a = p.parse_args()
    if not re.fullmatch(r'[0-9a-f]{64}', a.expected_bundle_sha256) or a.interval_seconds < 5:
        p.error('invalid expected bundle hash or watch interval')
    cal = json.loads(a.calibration.read_text(encoding='utf-8-sig'))
    bounds = corridor_bounds(cal, fallback_width_m=a.fallback_width_m)
    template_manifest = json.loads((a.group4_template/'template_manifest.json').read_text(encoding='utf-8'))
    group4_inventory = a.group4_template/'group4_inventory.json'
    if digest(group4_inventory) != template_manifest['files_sha256']['group4_inventory.json']:
        raise ValueError('group 4 inventory hash mismatch')
    rows = {r['recording']:r for r in json.loads(group4_inventory.read_text(encoding='utf-8'))}
    group5_path = a.group4_template/'group5_recordings.json'
    if digest(group5_path) != template_manifest['files_sha256']['group5_recordings.json']:
        raise ValueError('group 5 recording list hash mismatch')
    expected = {('4', rec) for rec in rows} | {('5', rec) for rec in json.loads(group5_path.read_text(encoding='utf-8'))}
    for row in rows.values():
        if digest(a.group4_template/row['timeline']) != template_manifest['files_sha256'][row['timeline']]:
            raise ValueError('group 4 timeline hash mismatch')
    originals, candidates = a.output_root/'originals', a.output_root/'candidates'
    a.output_root.mkdir(parents=True, exist_ok=True)
    lock = (a.output_root/'.filter.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError('another spatial filtering process is running') from exc
    while True:
        sources = sorted(p for p in a.source_root.iterdir() if p.is_dir() and re.fullmatch(r'g00[45]_recording_\d{3}_[A-Za-z0-9_]+', p.name))
        unique = {}
        for source in sources:
            data, manifest = read_packet(source, 'complete')
            key = (str(manifest.get('group')), manifest.get('recording'))
            if key not in expected:
                raise ValueError(f'unexpected recording in source: {key}')
            if key in unique:
                raise ValueError(f'multiple original results need review: {key}')
            unique[key] = source
            output = originals/source.name
            source_manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'))
            if output.exists():
                existing = json.loads((output/'manifest.json').read_text(encoding='utf-8-sig'))
                if (existing.get('source_positions_sha256') != source_manifest.get('positions_sha256') or
                        existing.get('bounds') != bounds or existing.get('positions_sha256') != digest(output/'positions.json')):
                    raise ValueError(f'published filtered result changed: {output}')
                continue
            made, stats = filter_original(source, output, bounds, cal['setup_id'], a.expected_bundle_sha256,
                                          rows.get(manifest.get('recording')), a.group4_template, cal, a.calibration)
            if made:
                print(f'[範囲除外] {source.name}: 除外 {stats["outside_any"]} 観測', flush=True)
        for candidate in sorted(a.candidate_root.glob('g004_recording_*_temporal_20261106_01')):
            rec = candidate.name[5:18]
            source = unique.get(('4', rec))
            if source is None:
                continue
            output = candidates/candidate.name
            if output.exists():
                existing = json.loads((output/'manifest.json').read_text(encoding='utf-8-sig'))
                source_candidate = json.loads((candidate/'manifest.json').read_text(encoding='utf-8-sig'))
                if (existing.get('source_candidate_sha256') != source_candidate.get('positions_sha256') or
                        existing.get('bounds') != bounds or existing.get('positions_sha256') != digest(output/'positions.json')):
                    raise ValueError(f'published filtered candidate changed: {output}')
                continue
            made, count = filter_candidate(source, candidate, originals/source.name, output, bounds)
            if made:
                print(f'[範囲除外] {candidate.name}: 仮割当て {count} 観測を保持', flush=True)
        print(f'[範囲除外] グループ4/5の座標 {len(unique)} 録画を確認済み', flush=True)
        if not a.watch or set(unique) == expected:
            break
        time.sleep(a.interval_seconds)


if __name__ == '__main__':
    main()
