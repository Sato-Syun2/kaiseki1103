"""Verify BODY and depth exports come from the same SVO and image timeline."""
import argparse
import csv
import json
from pathlib import Path

from depth_person_prototype import digest, load_depth_export
from zed_sdk_package.tracking_v2.validate_export import validate_export


def verify_metadata(depth_camera, body_camera, depth_frames, body_frames, *, first=None, count=None):
    for key in ('source_svo_sha256','setup_id','serial_number','width','height','depth_mode','coordinate_units','intrinsics_left'):
        if depth_camera.get(key) is None or depth_camera.get(key)!=body_camera.get(key):
            raise ValueError(f'depth and BODY camera differ: {key}')
    if not str(depth_camera.get('coordinate_system','')).startswith('IMAGE') or not str(body_camera.get('coordinate_system','')).startswith('IMAGE'):
        raise ValueError('depth and BODY must use IMAGE coordinates')
    body_by_index={int(f['frame_index']):f for f in body_frames}
    if len(body_by_index)!=len(body_frames):raise ValueError('duplicate BODY frame')
    for depth in depth_frames:
        idx=int(depth['frame_index']); body=body_by_index.get(idx)
        if body is None or depth['image_timestamp_ns']!=body['image_timestamp_ns'] or depth['svo_frame_index']!=body['svo_frame_index']:
            raise ValueError(f'depth/BODY timeline differs at frame {idx}')
    indices=[int(f['frame_index']) for f in depth_frames]
    if (first is None) != (count is None):raise ValueError('specify both first and count')
    if first is not None:
        if first < 0 or count < 1 or indices != list(range(first, first+count)):
            raise ValueError('depth frames are not the requested continuous range')
    return {'status':'matched','source_svo_sha256':depth_camera['source_svo_sha256'],
            'setup_id':depth_camera['setup_id'],'depth_frames':len(depth_frames),
            'body_frames':len(body_frames),'first_frame':indices[0],'last_frame':indices[-1],
            'continuous':indices==list(range(indices[0],indices[-1]+1)),
            'interpretation':'same recording and image timestamps; separate SDK passes do not prove depth maps are identical'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth',type=Path,required=True);p.add_argument('--body',type=Path,required=True)
    p.add_argument('--first-frame',type=int);p.add_argument('--frame-count',type=int);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('output already exists')
    _,dc,frames,_,_,dh=load_depth_export(a.depth)
    validate_export(a.body)
    bc=json.loads((a.body/'camera.json').read_text(encoding='utf-8-sig'))
    with (a.body/'frames.csv').open(newline='',encoding='utf-8-sig') as f:body_frames=list(csv.DictReader(f))
    report=verify_metadata(dc,bc,frames,body_frames,first=a.first_frame,count=a.frame_count)
    if dc.get('total_svo_frames_read')!=len(body_frames):raise ValueError('depth pass did not read the full BODY timeline')
    report.update(depth_manifest_sha256=dh,body_manifest_sha256=digest(a.body/'manifest.json'))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
