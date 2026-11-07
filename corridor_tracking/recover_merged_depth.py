"""Recover a fully merged local depth run into a new run without rerunning the SDK."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def verify_bundle(bundle):
    manifest = json.loads((bundle/'bundle_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'prepared_not_windows_validated' or not manifest.get('files_sha256'):
        raise ValueError('invalid bundle manifest')
    for name, expected in manifest['files_sha256'].items():
        path = (bundle/name).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or sha256(path) != expected:
            raise ValueError(f'changed or missing bundle file: {name}')


def copy_manifest_assets(source, destination, manifest):
    """Copy only verified merged assets; hardlinks are safe because assets stay read-only."""
    hashes = manifest.get('files_sha256', {})
    if not hashes or 'results.json' not in hashes:
        raise ValueError('merged manifest is missing assets')
    destination.mkdir(parents=True, exist_ok=False)
    hardlinked = copied = 0
    for name, expected in hashes.items():
        path = (source/name).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file() or sha256(path) != expected:
            raise ValueError(f'unsafe or changed source asset: {name}')
        dst = destination/name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, dst)
            hardlinked += 1
        except OSError:
            shutil.copyfile(path, dst)
            copied += 1
        if sha256(dst) != expected:
            raise OSError(f'copied merged asset differs: {name}')
    shutil.copyfile(source/'manifest.json', destination/'manifest.json')
    if sha256(source/'manifest.json') != sha256(destination/'manifest.json'):
        raise OSError('copied merged manifest differs')
    return hardlinked, copied


def recover(bundle, root, shared, group, recording, old_run, prefix):
    bundle, root, shared = bundle.resolve(), root.resolve(), shared.resolve()
    if group not in (4,5) or not re.fullmatch(r'recording_\d{3}', recording) or not re.fullmatch(r'compact_[A-Za-z0-9_]+', old_run) or not re.fullmatch(r'compact_[A-Za-z0-9_]+', prefix):
        raise ValueError('invalid group, recording or run ID')
    if not root.is_dir() or not shared.is_dir():
        raise FileNotFoundError('SSD root or shared coordinate folder unavailable; existing files preserved')
    print('[Recovery] Verifying the original analysis bundle...', flush=True)
    verify_bundle(bundle)
    sys.path.insert(0, str(bundle))
    from corridor_tracking.compact_batch import fresh_run, tag_for
    from corridor_tracking.depth_person_comparison import load_run
    from corridor_tracking.depth_tracking import associate_frames
    from corridor_tracking.local_depth_pipeline import coordinates
    from corridor_tracking.merge_depth_person_runs import validate_parts
    from corridor_tracking.portable_depth_replay import create_replay
    from zed_sdk_package.tracking_v2.exchange_copy import copy_batch
    if importlib.metadata.version('ultralytics') != '8.4.89':
        raise ValueError('expected the original analysis environment (Ultralytics 8.4.89)')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as stream:
        matches = [r for r in csv.DictReader(stream) if r['group'] == str(group) and r['recording'] == recording]
    if len(matches) != 1:
        raise ValueError('recording missing or duplicated in inventory')
    row = matches[0]
    old_tag = tag_for(row, old_run)
    work = root/'analysis'/old_tag
    merged = work/'merged'
    if not merged.is_dir() or (root/'coordinates'/old_tag).exists() or (shared/old_tag).exists():
        raise ValueError('expected a merged run that failed before coordinate publication; inspect existing files')
    print('[Recovery] Verifying the original SVO, timeline, and merged results...', flush=True)
    svo = Path(row['svo_path'])
    if not svo.is_file() or sha256(svo) != row['source_svo_sha256']:
        raise ValueError('source SVO is missing or changed')
    timeline_file = bundle/row['timeline']
    timeline = json.loads(timeline_file.read_text(encoding='utf-8-sig'))
    reference_key = 'timeline_sha256' if row.get('timeline_sha256') else 'body_manifest_sha256'
    reference_hash = row[reference_key]
    if (sha256(timeline_file) if reference_key == 'timeline_sha256' else timeline.get('body_manifest_sha256')) != reference_hash:
        raise ValueError('reference timeline provenance differs')
    if reference_key == 'timeline_sha256' and timeline.get('kind') != 'svo_sdk_timeline_no_body':
        raise ValueError('unexpected reference timeline type')
    cal, model = bundle/row['calibration'], bundle/'models/yolov8n-seg.pt'
    if sha256(cal) != row['calibration_sha256']:
        raise ValueError('calibration changed')
    count = int(row['frame_count'])
    data = load_run(merged)
    meta, frames = data['metadata'], data['frames']
    if (len(frames) != count or len(timeline['frames']) != count or
            any(int(f['frame_index']) != i or str(f['timestamp_ns']) != str(t['image_timestamp_ns']) or int(t['svo_frame_index']) != i
                for i, (f,t) in enumerate(zip(frames,timeline['frames'])))):
        raise ValueError('merged frames do not match the full SVO timeline')
    if (meta.get('source_svo_sha256') != row['source_svo_sha256'] or meta.get('setup_id') != row['setup_id'] or
            meta.get('calibration_sha256') != row['calibration_sha256'] or meta.get('model_sha256') != sha256(model) or
            meta.get('ultralytics_version') != '8.4.89' or
            meta.get('merged_frame_range') != {'first_frame':0,'frame_count':count,'full_svo_verified':True}):
        raise ValueError('merged recording, model, calibration or frame coverage differs')
    timing = json.loads((work/'timing.json').read_text(encoding='utf-8-sig'))
    clip_size, mode = int(timing['clip_frames']), timing['point_archive_mode']
    if not 1 <= clip_size <= 90 or mode not in ('compressed','stored'):
        raise ValueError('invalid saved clip settings')
    pieces = []
    source_records = meta.get('source_parts', [])
    ranges = [(i, min(clip_size, count-i)) for i in range(0,count,clip_size)]
    if len(source_records) != len(ranges):
        raise ValueError('merged part count differs')
    merged_manifest = json.loads((merged/'manifest.json').read_text(encoding='utf-8-sig'))
    if merged_manifest.get('merge_script_sha256') != sha256(bundle/'corridor_tracking/merge_depth_person_runs.py'):
        raise ValueError('merged output was created by a different merge program')
    for record, (start, length) in zip(source_records, ranges):
        part = work/f'part_{start:06d}'
        alignment_path = work/f'alignment_{start:06d}.json'
        part_data = load_run(part)
        part_manifest = json.loads((part/'manifest.json').read_text(encoding='utf-8-sig'))
        alignment = json.loads(alignment_path.read_text(encoding='utf-8-sig'))
        tag = f'{old_tag}_{start:06d}_{start+length-1:06d}'
        clip = root/'depth_clips'/tag
        summary = json.loads((clip/'batch_summary.json').read_text(encoding='utf-8-sig'))
        depth_manifest = clip/'depth/manifest.json'
        if (record.get('first_frame') != start or record.get('last_frame') != start+length-1 or
                part_manifest.get('script_sha256') != sha256(bundle/'depth_person_prototype.py') or
                part_manifest.get('transform_code_sha256') != sha256(bundle/'corridor_tracking/data.py') or
                record.get('result_manifest_sha256') != sha256(part/'manifest.json') or
                record.get('alignment_sha256') != sha256(alignment_path) or
                record.get('depth_manifest_sha256') != sha256(depth_manifest) or
                alignment.get('depth_manifest_sha256') != sha256(depth_manifest) or
                alignment.get(reference_key) != reference_hash or
                summary.get('status') != 'validated' or summary.get('source_svo_sha256') != row['source_svo_sha256'] or
                summary.get('first_frame') != start or summary.get('frame_count') != length or
                summary.get('point_archive_mode') != mode):
            raise ValueError(f'incomplete or mismatched part at frame {start}')
        pieces.append({'data':part_data, 'alignment':alignment, 'manifest':part_manifest})
    validate_parts(pieces, 0, count, require_full_svo=True)
    if [f for piece in pieces for f in piece['data']['frames']] != frames:
        raise ValueError('merged results differ from verified source parts')
    print('[Recovery] All source parts and times match. No SDK reprocessing is needed.', flush=True)
    if not shared.is_dir():
        raise FileNotFoundError('shared coordinate folder is unavailable')
    run_id = fresh_run(row, root, shared, prefix)
    tag = tag_for(row, run_id)
    new_work, new_coord, destination = root/'analysis'/tag, root/'coordinates'/tag, shared/tag
    print(f'[Recovery] Creating a separate output: {tag}', flush=True)
    links, copies = copy_manifest_assets(merged, new_work/'merged', merged_manifest)
    if sha256(new_work/'merged'/'manifest.json') != sha256(merged/'manifest.json'):
        raise ValueError('copied manifest mismatch')
    if load_run(new_work/'merged') != data:
        raise ValueError('copied merged content differs')
    tracked = associate_frames(frames)
    metadata = {'group':group, 'recording':recording, 'source_svo_sha256':row['source_svo_sha256'],
                'setup_id':row['setup_id'], 'calibration_sha256':sha256(cal), reference_key:reference_hash,
                'bundle_manifest_sha256':sha256(bundle/'bundle_manifest.json'), 'model_sha256':sha256(model),
                'person_run_manifest_sha256':sha256(new_work/'merged'/'manifest.json'),
                'tracking_code_sha256':sha256(bundle/'corridor_tracking/depth_tracking.py'),
                'ultralytics_version':'8.4.89', 'point_archive_mode':mode,
                'storage_policy':'recovered_merged_source_intermediates_retained',
                'position_semantics':'visible depth surface candidate in provisional corridor XYZ metres; not body centre',
                'limits':['IDs are provisional', 'missing positions not interpolated', 'separate depth SDK passes'],
                'recovery':{'source_run':old_tag, 'recovery_script_sha256':sha256(Path(__file__)),
                            'merged_manifest_sha256':sha256(merged/'manifest.json'), 'source_intermediates_retained':True}}
    if reference_key == 'timeline_sha256':
        metadata['reference_kind'] = 'svo_sdk_timeline_no_body'
    new_coord.mkdir(parents=True, exist_ok=False)
    payload = {'metadata':metadata, 'frames':coordinates(tracked)}
    (new_coord/'positions.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    coord_manifest = {'status':'complete','positions_sha256':sha256(new_coord/'positions.json'),
                      'allowed_files':['positions.json','manifest.json'],'source_svo_sha256':row['source_svo_sha256'],
                      'recording':recording,'group':group,'frame_count':len(tracked)}
    (new_coord/'manifest.json').write_text(json.dumps(coord_manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    create_replay(root,bundle,group,recording,run_id,update_gallery=False)
    retention = {'status':'complete','tag':tag,'policy':'recovered copy; no new depth intermediates created',
                 'source_run':old_tag,'source_intermediates_retained':True,'files_removed':[],
                 'merged_assets_hardlinked':links,'merged_assets_copied':copies,
                 'positions_sha256':coord_manifest['positions_sha256'],
                 'replay_sha256':sha256(new_work/'merged'/'portable_replay.html')}
    (new_work/'storage_retention.json').write_text(json.dumps(retention,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('[Recovery] Local coordinates and replay verified; publishing only coordinates...', flush=True)
    copied,message = copy_batch(new_coord,destination)
    print(message,flush=True)
    if not copied or sha256(destination/'positions.json') != coord_manifest['positions_sha256']:
        raise OSError('shared publication failed; original and new local files are retained')
    print(f'[Recovery] Complete: {tag}; previous large intermediates remain at {work}',flush=True)
    return tag


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True);p.add_argument('--local-root',type=Path,required=True)
    p.add_argument('--shared-root',type=Path,required=True);p.add_argument('--group',type=int,required=True)
    p.add_argument('--recording',required=True);p.add_argument('--old-run-id',required=True);p.add_argument('--run-prefix',required=True)
    a=p.parse_args()
    recover(a.bundle,a.local_root,a.shared_root,a.group,a.recording,a.old_run_id,a.run_prefix)


if __name__=='__main__':
    main()
