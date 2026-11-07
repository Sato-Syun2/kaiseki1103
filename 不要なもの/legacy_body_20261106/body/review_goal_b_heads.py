#!/usr/bin/env python3
"""Prepare an image-based review of head detections at labelled checkpoints.

The overlaid boxes are candidates for human review, not automatically
asserted matches or 3D position measurements.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from corridor_tracking.data import load_export,sha256
from zed_sdk_package.tracking_v2.validate_export import validate_export


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body',required=True,type=Path)
    p.add_argument('--heads',required=True,type=Path)
    p.add_argument('--calibration',required=True,type=Path)
    p.add_argument('--annotations',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    validate_export(a.body);validate_export(a.heads)
    data=load_export(a.body,json.loads(a.calibration.read_text()),with_appearance=False,heads_folder=a.heads)
    ann=json.loads(a.annotations.read_text());by_stamp={f['timestamp_ns']:f for f in data['frames']}
    detections=defaultdict(list)
    for o in data['observations']:
        if o['kind']=='head':detections[o['timestamp_ns']].append(o)
    a.output.mkdir(parents=True,exist_ok=False)
    width=400;height=450;columns=5
    sheet=Image.new('RGB',(width*columns,height*((len(ann['checkpoints'])+columns-1)//columns)),'white')
    draw=ImageDraw.Draw(sheet);details=[]
    for index,c in enumerate(ann['checkpoints']):
        f=by_stamp.get(c['timestamp_ns'])
        if f is None or not f['image_path'] or sha256(Path(f['image_path']))!=c['image_sha256']:
            raise ValueError('Annotated image missing or changed')
        img=Image.open(f['image_path']).convert('RGB');d=ImageDraw.Draw(img)
        x0,y0,x1,y1=c['visible_head_bbox'];d.rectangle((x0,y0,x1,y1),outline='red',width=3)
        candidates=[]
        for o in detections[c['timestamp_ns']]:
            try:
                box=np.asarray(json.loads(o['raw']['bounding_box_2d_json']),dtype=float)
                if box.ndim!=2 or box.shape[1]!=2 or not np.isfinite(box).all():raise ValueError('invalid box')
                bounds=[float(box[:,0].min()),float(box[:,1].min()),float(box[:,0].max()),float(box[:,1].max())]
                d.rectangle(bounds,outline='cyan',width=2)
                candidates.append(dict(object_id=o['sdk_id'],bounds=bounds,state=o['state'],
                    current_support=o['current_support'],confidence=o['confidence']))
            except (TypeError,ValueError,json.JSONDecodeError):
                candidates.append(dict(object_id=o['sdk_id'],bounds=None,state=o['state'],current_support=o['current_support']))
        cx=(x0+x1)//2;cy=(y0+y1)//2
        crop=img.crop((cx-100,cy-90,cx+100,cy+110)).resize((width,400))
        x=index%columns*width;y=index//columns*height;sheet.paste(crop,(x,y+40))
        draw.text((x+3,y+4),f"frame={c['frame_index']} t={c['t']:.3f} detections={len(candidates)}",fill='black')
        details.append(dict(frame_index=c['frame_index'],timestamp_ns=c['timestamp_ns'],
                            annotated_head_bbox=c['visible_head_bbox'],head_detections=candidates))
    sheet.save(a.output/'head_candidates_review.jpg',quality=90)
    report=dict(scope='Development checkpoints. Red=visually labelled rear head; cyan=SDK head detector boxes. Manual review is required; no automatic truth matches.',
        checkpoints=details,body_camera_sha256=sha256(a.body/'camera.json'),
        heads_manifest_sha256=sha256(a.heads/'manifest.json'),annotations_sha256=sha256(a.annotations),
        calibration_sha256=sha256(a.calibration),script_sha256=sha256(Path(__file__)))
    (a.output/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(a.output/'head_candidates_review.jpg')


if __name__=='__main__':main()
