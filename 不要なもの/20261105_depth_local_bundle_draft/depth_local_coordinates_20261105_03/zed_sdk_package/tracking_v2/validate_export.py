#!/usr/bin/env python3
"""Validate a full-frame export without pyzed or a GPU. Nonzero exit means reject."""
from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def csv_rows(path):
    with path.open(newline='',encoding='utf-8-sig') as f:
        yield from csv.DictReader(f)


def inside(root,name):
    path=(root/name).resolve()
    if not name or not path.is_relative_to(root.resolve()):
        raise ValueError(f'Asset path escapes export: {name}')
    return path


def validate_export(root,allow_limited=False,verify_assets=True):
    root=Path(root)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
    camera=json.loads((root/'camera.json').read_text(encoding='utf-8-sig'))
    if manifest.get('status')!='complete' or manifest.get('errors'):
        raise ValueError('Export is not complete or contains errors')
    if manifest.get('schema_version')!=2 or camera.get('schema_version')!=2:
        raise ValueError('Expected schema_version=2')
    if manifest['completion_scope'] not in ['full_svo_eof','requested_frame_limit']:
        raise ValueError('Unknown completion scope')
    if manifest['completion_scope']!='full_svo_eof' and not allow_limited:
        raise ValueError('Limited smoke test is not a full SVO; use --allow-limited only to inspect it')
    if manifest['completion_scope']=='full_svo_eof' and manifest['planned_frames']!=manifest['total_svo_frames']:
        raise ValueError('Full-SVO export does not cover the planned recording')
    if not camera.get('source_svo_sha256') or camera['source_svo_sha256']!=manifest['source_svo_sha256']:
        raise ValueError('Source SVO hashes disagree')
    kind=manifest['mode']
    if kind not in ['body','body18','heads'] or camera['detection_kind']!=kind:
        raise ValueError('Detection kind mismatch')
    if kind in ['body','body18'] and camera.get('body_format')!=('BODY_18' if kind=='body18' else 'BODY_34'):
        raise ValueError('Body format metadata does not match mode')
    data_name='bodies.csv' if kind in ['body','body18'] else 'heads.csv'
    required={'camera.json','frames.csv',data_name,'assets.csv'}
    if set(manifest.get('file_hashes',{}))!=required:
        raise ValueError('Manifest file hash list is incomplete')
    for name,expected in manifest['file_hashes'].items():
        if sha256(root/name)!=expected:
            raise ValueError('Hash mismatch: '+name)
    frames={}
    last_stamp=last_svo=first_stamp=None
    images={}
    for idx,row in enumerate(csv_rows(root/'frames.csv')):
        stamp=int(row['image_timestamp_ns'])
        svo=int(row['svo_frame_index'])
        if first_stamp is None:
            first_stamp=stamp
        if abs(float(row['elapsed_s'])-(stamp-first_stamp)/1e9)>1e-8:
            raise ValueError('Elapsed time differs from nanosecond timestamp')
        if int(row['frame_index'])!=idx or (last_stamp is not None and stamp<=last_stamp):
            raise ValueError('Missing frame or non-increasing timestamp')
        if last_svo is not None and svo!=last_svo+1:
            raise ValueError('Missing SVO frame')
        if row['retrieve_status']!='SUCCESS' or row['is_new'] not in ['true','false']:
            raise ValueError('Retrieval failed or newness not recorded')
        int(row['detection_timestamp_ns'])
        frames[idx]=row
        if row['image_file']:
            if row['image_file'] in images:
                raise ValueError('Image reused across frames')
            images[row['image_file']]=(idx,str(stamp))
        last_stamp,last_svo=stamp,svo
    if not frames or len(frames)!=manifest['saved_frames'] or len(frames)!=manifest['planned_frames'] or len(frames)!=manifest['acquired_frames']:
        raise ValueError('Frame counts disagree with manifest')
    if len(images)!=manifest['saved_images']:
        raise ValueError('Image count mismatch')
    if str(first_stamp)!=manifest['first_image_timestamp_ns'] or str(last_stamp)!=manifest['last_image_timestamp_ns']:
        raise ValueError('Manifest timestamp endpoints disagree')
    counts=Counter()
    mask_files={}
    for row in csv_rows(root/data_name):
        idx=int(row['frame_index'])
        if idx not in frames:
            raise ValueError('Detection refers to absent frame')
        for field in ['image_timestamp_ns','detection_timestamp_ns','is_new']:
            if row[field]!=frames[idx][field]:
                raise ValueError('Detection/frame metadata mismatch: '+field)
        if kind in ['body','body18']:
            for field in ['keypoints_2d_json','keypoints_3d_camera_json','keypoint_confidence_json']:
                expected=18 if kind=='body18' else 34
                if len(json.loads(row[field]))!=expected:
                    raise ValueError(f'{camera["body_format"]} joint count mismatch')
        if row.get('mask_file'):
            if row['mask_file'] in mask_files:
                raise ValueError('Mask reused across detections')
            mask_files[row['mask_file']]=(idx,row['image_timestamp_ns'])
        counts[idx]+=1
    count_field='body_count' if kind in ['body','body18'] else 'object_count'
    if any(counts[idx]!=int(f[count_field]) for idx,f in frames.items()) or sum(counts.values())!=manifest['saved_observations']:
        raise ValueError('Detection counts disagree')
    seen=set()
    for asset in csv_rows(root/'assets.csv'):
        name=asset['path']
        expected=images.get(name) if asset['kind']=='image' else mask_files.get(name)
        if expected!=(int(asset['frame_index']),asset['image_timestamp_ns']) or name in seen:
            raise ValueError('Asset/frame mismatch or duplicate: '+name)
        seen.add(name)
        path=inside(root,name)
        if verify_assets and sha256(path)!=asset['sha256']:
            raise ValueError('Asset hash mismatch: '+name)
        if verify_assets and asset['kind']=='image':
            import cv2
            image=cv2.imread(str(path))
            if image is None or image.shape[:2]!=(camera['height'],camera['width']):
                raise ValueError('Image resolution mismatch: '+name)
    if seen!=set(images)|set(mask_files):
        raise ValueError('Missing asset hash entries')
    return dict(status='valid',scope=manifest['completion_scope'],mode=kind,frames=len(frames),
                observations=sum(counts.values()),images=len(images),assets_verified=verify_assets,
                source_svo_sha256=camera['source_svo_sha256'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('export',type=Path)
    p.add_argument('--allow-limited',action='store_true')
    a=p.parse_args()
    print(json.dumps(validate_export(a.export,a.allow_limited),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
