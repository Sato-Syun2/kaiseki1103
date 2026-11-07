"""Retain portable results, then remove this newly completed run's verified bulky intermediates."""
import csv
import json
from pathlib import Path

from corridor_tracking.depth_person_comparison import load_run
from corridor_tracking.portable_depth_replay import create_replay, joined_frames
from depth_person_prototype import digest, safe_asset


def compact_completed_run(*, root, bundle, shared, row, group, recording, run_id, clips):
    root, bundle, shared = Path(root).resolve(), Path(bundle).resolve(), Path(shared).resolve()
    tag = f'g{group:03d}_{recording}_{run_id}'
    work, merged = root/'analysis'/tag, root/'analysis'/tag/'merged'
    local_coords, share_coords = root/'coordinates'/tag, shared/tag
    source = Path(row['svo_path'])
    if not source.is_file() or digest(source) != row['source_svo_sha256']:
        raise ValueError('original SVO is missing or differs; no intermediates removed')
    local_manifest = json.loads((local_coords/'manifest.json').read_text(encoding='utf-8-sig'))
    shared_manifest = json.loads((share_coords/'manifest.json').read_text(encoding='utf-8-sig'))
    local_positions, shared_positions = local_coords/'positions.json', share_coords/'positions.json'
    pos_hash = digest(local_positions)
    if (local_manifest.get('status') != 'complete' or shared_manifest.get('status') != 'complete'
            or local_manifest.get('positions_sha256') != pos_hash or shared_manifest.get('positions_sha256') != pos_hash
            or digest(shared_positions) != pos_hash or local_manifest.get('source_svo_sha256') != row['source_svo_sha256']
            or shared_manifest.get('source_svo_sha256') != row['source_svo_sha256']):
        raise ValueError('local/shared coordinates differ; no intermediates removed')
    positions = json.loads(local_positions.read_text(encoding='utf-8-sig'))
    if positions['metadata'].get('person_run_manifest_sha256') != digest(merged/'manifest.json'):
        raise ValueError('merged result provenance differs; no intermediates removed')
    person = load_run(merged)
    merged_manifest = json.loads((merged/'manifest.json').read_text(encoding='utf-8-sig'))
    frames = joined_frames(person['frames'], positions['frames'])
    if len(frames) != int(row['frame_count']):
        raise ValueError('incomplete final frames; no intermediates removed')
    page = merged/'portable_replay.html'
    if not page.is_file() or not (merged/'portable_replay_manifest.json').is_file():
        raise ValueError('portable replay not complete; no intermediates removed')
    create_replay(root, bundle, group, recording, run_id)
    candidates = []
    def add(base, name, expected):
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'unsafe intermediate path: {name}')
        path = base/rel
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f'unsafe intermediate asset: {path}')
        path = safe_asset(base, name)
        if digest(path) != expected:
            raise ValueError(f'intermediate hash mismatch; no intermediates removed: {path}')
        candidates.append({'path': path.relative_to(root).as_posix(), 'sha256': expected, 'bytes': path.stat().st_size})
    for start, length, clip_tag in clips:
        clip = root/'depth_clips'/clip_tag
        batch = json.loads((clip/'batch_summary.json').read_text(encoding='utf-8-sig'))
        depth = clip/'depth'
        manifest = json.loads((depth/'manifest.json').read_text(encoding='utf-8-sig'))
        if (batch.get('status') != 'validated' or batch.get('source_svo_sha256') != row['source_svo_sha256']
                or batch.get('first_frame') != start or batch.get('frame_count') != length
                or manifest.get('status') != 'complete' or manifest.get('source_svo_sha256') != row['source_svo_sha256']
                or manifest.get('sample_count') != length):
            raise ValueError(f'clip metadata not validated: {clip_tag}')
        hashes = manifest['files_sha256']
        with (depth/'frames.csv').open(newline='', encoding='utf-8-sig') as stream:
            clip_frames = list(csv.DictReader(stream))
        if [int(f['frame_index']) for f in clip_frames] != list(range(start, start+length)):
            raise ValueError(f'clip frames differ: {clip_tag}')
        removable = ['zed_depth_points.npz'] + [f['image_file'] for f in clip_frames]
        if len(removable) != len(set(removable)) or any(not x.startswith('images/') for x in removable[1:]):
            raise ValueError(f'unsafe clip image list: {clip_tag}')
        for name in removable:
            if name not in hashes:
                raise ValueError(f'clip asset missing from manifest: {clip_tag}/{name}')
            add(depth, name, hashes[name])
        part = work/f'part_{start:06d}'
        part_data = load_run(part)
        if part_data['frames'] != person['frames'][start:start+length]:
            raise ValueError(f'merged frames differ from source part: {clip_tag}')
        part_manifest = json.loads((part/'manifest.json').read_text(encoding='utf-8-sig'))
        for name, expected in part_manifest['files_sha256'].items():
            if name.startswith(('images/', 'masks/')):
                if merged_manifest.get('files_sha256', {}).get(name) != expected:
                    raise ValueError(f'merged asset differs from source part: {clip_tag}/{name}')
                add(part, name, expected)
    names = [item['path'] for item in candidates]
    if not candidates or len(names) != len(set(names)):
        raise ValueError('intermediate files are missing or duplicated; nothing removed')
    receipt_path = work/'storage_retention.json'
    if receipt_path.exists():
        raise FileExistsError('storage retention receipt already exists')
    receipt = {'status': 'prepared', 'tag': tag, 'source_svo_path': str(source.resolve()),
               'source_svo_sha256': row['source_svo_sha256'], 'positions_sha256': pos_hash,
               'merged_manifest_sha256': digest(merged/'manifest.json'), 'replay_sha256': digest(page),
               'files_removed': candidates, 'planned_bytes': sum(x['bytes'] for x in candidates),
               'limits': ['Intermediate files are no longer available despite historical SDK and part manifests.',
                          'Rerun the SDK from the original SVO to recompute depth; exact reproduction is not guaranteed.']}
    with receipt_path.open('x', encoding='utf-8') as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2); f.write('\n')
    for item in candidates:
        (root/Path(item['path'])).unlink()
    receipt['status'] = 'complete'
    temporary = work/'storage_retention.json.tmp'
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(receipt_path)
    print(f'[Compact] Removed {receipt["planned_bytes"]/1e9:.2f} GB of verified intermediates for {tag}.', flush=True)
    return receipt
