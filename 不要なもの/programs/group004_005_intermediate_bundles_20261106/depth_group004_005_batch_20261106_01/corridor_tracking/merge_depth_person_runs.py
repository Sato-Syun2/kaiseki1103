"""Join validated, consecutive per-frame person/depth analyses before tracking."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil

from corridor_tracking.depth_person_comparison import load_run
from depth_person_prototype import digest, manifest_relative_path, safe_asset


SETTINGS = ('method','source_svo_sha256','setup_id','calibration_sha256','selection',
            'model_sha256','model_task','ultralytics_version','confidence','imgsz','device')
CODE_HASHES = ('script_sha256','transform_code_sha256')


def validate_parts(parts, first_frame, frame_count, *, require_full_svo=False):
    if not parts or first_frame < 0 or frame_count < 1:
        raise ValueError('a valid expected frame range and at least one part are required')
    reference=parts[0]
    metadata=reference['data']['metadata']
    if metadata.get('method') != 'mask':
        raise ValueError('only matching instance-mask runs can be joined')
    if any(k not in metadata for k in SETTINGS) or any(k not in reference['manifest'] for k in CODE_HASHES):
        raise ValueError('part is missing model, configuration, or analysis provenance')
    reference_key = 'timeline_sha256' if reference['alignment'].get('reference_kind') == 'svo_sdk_timeline_no_body' else 'body_manifest_sha256'
    body_hash=reference['alignment'].get(reference_key)
    if not body_hash:
        raise ValueError('alignment must identify the verified reference timeline')
    count_key = 'reference_frames' if reference_key == 'timeline_sha256' else 'body_frames'
    body_frame_count=reference['alignment'].get(count_key)
    if not isinstance(body_frame_count, int) or body_frame_count < 1:
        raise ValueError('alignment must record the full reference frame count')
    if require_full_svo and (first_frame != 0 or frame_count != body_frame_count):
        raise ValueError('requested range does not cover the full SVO')
    parts=sorted(parts,key=lambda p:int(p['data']['frames'][0]['frame_index']) if p['data']['frames'] else -1)
    all_frames=[]; last_stamp=None
    for part in parts:
        m=part['data']['metadata']; alignment=part['alignment']; manifest=part['manifest']
        if any(m.get(k)!=metadata.get(k) for k in SETTINGS) or any(manifest.get(k)!=reference['manifest'].get(k) for k in CODE_HASHES):
            raise ValueError('part model, configuration, calibration, or analysis code differs')
        if alignment.get('status')!='matched' or not alignment.get('continuous'):
            raise ValueError('part has no validated continuous depth/BODY alignment')
        if alignment.get('depth_manifest_sha256')!=m.get('depth_manifest_sha256') or alignment.get(reference_key)!=body_hash or alignment.get(count_key)!=body_frame_count or alignment.get('reference_kind')!=reference['alignment'].get('reference_kind'):
            raise ValueError('alignment belongs to different depth or BODY input')
        if alignment.get('source_svo_sha256')!=m.get('source_svo_sha256') or alignment.get('setup_id')!=m.get('setup_id'):
            raise ValueError('alignment source or setup differs')
        frames=part['data']['frames']
        if not frames:
            raise ValueError('part contains no frames')
        indices=[int(f['frame_index']) for f in frames]
        if indices!=list(range(indices[0],indices[-1]+1)) or len(indices)!=alignment.get('depth_frames') or indices[0]!=alignment.get('first_frame') or indices[-1]!=alignment.get('last_frame'):
            raise ValueError('part frames disagree with its alignment')
        for frame in frames:
            stamp=int(frame['timestamp_ns'])
            if last_stamp is not None and stamp<=last_stamp:
                raise ValueError('frame timestamps are not strictly increasing across parts')
            last_stamp=stamp
        all_frames.extend(frames)
    if [int(f['frame_index']) for f in all_frames]!=list(range(first_frame,first_frame+frame_count)):
        raise ValueError('parts overlap, have missing frames, or do not cover the expected range')
    origin_stamp=int(all_frames[0]['timestamp_ns']);origin_elapsed=float(all_frames[0]['elapsed_s'])
    for frame in all_frames:
        if abs((int(frame['timestamp_ns'])-origin_stamp)/1e9-(float(frame['elapsed_s'])-origin_elapsed))>1e-5:
            raise ValueError('elapsed time differs from timestamps across parts')
    return parts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--part',action='append',nargs=2,required=True,metavar=('RESULT_DIR','ALIGNMENT_JSON'))
    p.add_argument('--first-frame',type=int,required=True)
    p.add_argument('--frame-count',type=int,required=True)
    p.add_argument('--require-full-svo',action='store_true',help='require the entire verified BODY timeline')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('output already exists')
    parts=[]
    for raw_root,raw_alignment in args.part:
        root=Path(raw_root).resolve(); alignment_path=Path(raw_alignment).resolve()
        data=load_run(root)
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        alignment=json.loads(alignment_path.read_text(encoding='utf-8'))
        parts.append({'root':root,'data':data,'manifest':manifest,'alignment':alignment,'alignment_path':alignment_path})
    parts=validate_parts(parts,args.first_frame,args.frame_count,require_full_svo=args.require_full_svo)
    # Verify each copied asset is included in its validated source manifest.
    for part in parts:
        hashes=part['manifest']['files_sha256']
        for frame in part['data']['frames']:
            assets=[frame['review_image']]+[person['region_mask'] for person in frame['people']]
            for name in assets:
                if name not in hashes:raise ValueError(f'asset is not covered by source manifest: {name}')
                safe_asset(part['root'],name)
    args.output.mkdir(parents=True,exist_ok=False)
    frames=[]; source_records=[]
    for part in parts:
        root=part['root']; alignment=part['alignment']
        source_records.append({'result_manifest_sha256':digest(root/'manifest.json'),
            'depth_manifest_sha256':part['data']['metadata']['depth_manifest_sha256'],
            'alignment_sha256':digest(part['alignment_path']), 'first_frame':alignment['first_frame'],'last_frame':alignment['last_frame']})
        for old_frame in part['data']['frames']:
            frame=copy.deepcopy(old_frame)
            assets=[frame['review_image']]+[person['region_mask'] for person in frame['people']]
            for name in assets:
                target=args.output/name
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():raise ValueError(f'duplicate output asset: {name}')
                shutil.copyfile(safe_asset(root,name),target)
            frames.append(frame)
    metadata=copy.deepcopy(parts[0]['data']['metadata'])
    metadata['depth_manifest_sha256']=None
    metadata['source_parts']=source_records
    metadata['merged_frame_range']={'first_frame':args.first_frame,'frame_count':args.frame_count,'full_svo_verified':args.require_full_svo}
    metadata['processing_seconds']=sum(p['data']['metadata'].get('processing_seconds',0) for p in parts)
    reference_label = 'SVO SDK timeline (no BODY)' if parts[0]['alignment'].get('reference_kind') == 'svo_sdk_timeline_no_body' else 'BODY timeline'
    metadata['limits'].append(f'merged only after independent depth/{reference_label} validation; tracking is recalculated across part boundaries')
    payload={'metadata':metadata,'frames':frames}
    (args.output/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    files=sorted(x for x in args.output.rglob('*') if x.is_file())
    manifest={'status':'complete','merge_script_sha256':digest(Path(__file__)),
              'part_manifests_sha256':[r['result_manifest_sha256'] for r in source_records],
              'files_sha256':{manifest_relative_path(x, args.output):digest(x) for x in files}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Validated and merged {len(frames)} frames from {len(parts)} parts: {args.output}')


if __name__=='__main__':main()
