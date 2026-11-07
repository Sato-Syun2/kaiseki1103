#!/usr/bin/env python3
"""Compare body-only and body+head runs on the exact same SVO timeline.

Head-box overlaps are review candidates, not validated detections or person
identities. Interpolation and prediction are excluded from supported counts.
"""
import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from corridor_tracking.data import load_export,sha256
from body.corridor_tracking.evaluation import diagnostics
from body.corridor_tracking.replay import write_replay
from body.corridor_tracking.tracker import Config,run_tracker


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def box_bounds(value):
    try:
        points=np.asarray(json.loads(value),dtype=float)
        if points.shape!=(4,2) or not np.isfinite(points).all():return None
        x0,y0=points.min(axis=0);x1,y1=points.max(axis=0)
        if x1<=x0 or y1<=y0:return None
        return [float(x0),float(y0),float(x1),float(y1)]
    except (TypeError,ValueError,json.JSONDecodeError):
        return None


def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['body','heads','calibration','config','annotations','output']:
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--recording',default='recording_001')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    calibration=json.loads(a.calibration.read_text());cfg=Config.from_dict(json.loads(a.config.read_text()))
    annotations=json.loads(a.annotations.read_text());checkpoints=annotations.get('checkpoints',[])
    if not checkpoints:raise ValueError('No image-reviewed head checkpoints')
    if len({c['timestamp_ns'] for c in checkpoints})!=len(checkpoints):
        raise ValueError('Duplicate annotated checkpoint timestamp')
    # load_export validates both complete exports, source hash, camera metadata,
    # and all timestamps/SVO indices before any comparison is written.
    merged=load_export(a.body,calibration,with_appearance=cfg.appearance_weight>0,heads_folder=a.heads)
    body=load_export(a.body,calibration,with_appearance=cfg.appearance_weight>0)
    frames={f['timestamp_ns']:f for f in body['frames']}
    for c in checkpoints:
        frame=frames.get(c['timestamp_ns'])
        if frame is None or not frame['image_path'] or sha256(Path(frame['image_path']))!=c['image_sha256']:
            raise ValueError('Annotated image missing or changed')
        if int(c['frame_index'])!=frame['frame_index']:raise ValueError('Annotation frame/timestamp mismatch')
        box=c['visible_head_bbox']
        if len(box)!=4 or not all(np.isfinite(v) for v in box) or box[2]<=box[0] or box[3]<=box[1]:
            raise ValueError('Invalid annotated head region')
    without=run_tracker(body,cfg);with_heads=run_tracker(merged,cfg)
    metrics_without=diagnostics(body,without);metrics_with=diagnostics(merged,with_heads)
    body_result={o['obs_id']:o for o in without['observations']}
    head_result={o['obs_id']:o for o in with_heads['observations']}
    if set(body_result)!={o['obs_id'] for o in merged['observations'] if o['kind']=='body'}:
        raise ValueError('Body observation IDs differ between comparison runs')
    body_changed=sum(body_result[k]['track_id']!=head_result[k]['track_id'] for k in body_result)
    by_stamp=defaultdict(list)
    for o in merged['observations']:
        if o['kind']=='head':by_stamp[o['timestamp_ns']].append(o)
    rows=[]
    for c in checkpoints:
        head_candidates=[]
        for o in by_stamp[c['timestamp_ns']]:
            bounds=box_bounds(o['raw']['bounding_box_2d_json']);decision=head_result[o['obs_id']]
            head_candidates.append(dict(obs_id=o['obs_id'],sdk_id=o['sdk_id'],current_support=o['current_support'],
                confidence=o['confidence'],bbox=bounds,overlaps_annotated_region=bool(bounds and overlap(bounds,c['visible_head_bbox'])>0),
                track_id=decision['track_id'],id_status=decision['id_status'],position_source=decision['position_source'],
                association_reason=decision['association_reason'],
                supported_position=decision['xyz'] is not None and decision['position_source'] in ['sdk_estimate','partial_observation_estimate']))
        rows.append(dict(frame_index=c['frame_index'],timestamp_ns=c['timestamp_ns'],t=c['t'],
            person=c.get('person'),annotated_head_bbox=c['visible_head_bbox'],head_candidates=head_candidates))
    a.output.mkdir(parents=True,exist_ok=False)
    for name,data,tracking,metrics in [('body_only',body,without,metrics_without),('body_plus_heads',merged,with_heads,metrics_with)]:
        target=a.output/name;target.mkdir()
        dump(target/'tracking.json',tracking);dump(target/'metrics.json',metrics)
        write_replay(target,data,tracking,calibration,a.recording)
    with (a.output/'checkpoint_candidates.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['frame_index','timestamp_ns','t','person','head_candidates']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(row[k],ensure_ascii=False) if isinstance(row[k],list) else row[k] for k in fields})
    summary=dict(scope='Same SVO and full verified timeline; head box overlaps are unconfirmed visual-review candidates',
        adoption='not_adopted_pending_independent_identity_and_position_evaluation',
        body_only=metrics_without,body_plus_heads=metrics_with,
        head_observations_with_valid_boxes=sum(o['kind']=='head' for o in merged['observations']),
        head_position_sources=dict(Counter(head_result[o['obs_id']]['position_source'] for o in merged['observations'] if o['kind']=='head')),
        body_observation_track_id_differences=body_changed,reviewed_checkpoints=rows,
        input_hashes=merged['input_hashes'],image_hashes=merged['image_hashes'],
        calibration_sha256=sha256(a.calibration),config_sha256=sha256(a.config),annotations_sha256=sha256(a.annotations),
        code_sha256={str(x):sha256(x) for x in [Path(__file__),Path('corridor_tracking/data.py'),
            Path('body/corridor_tracking/tracker.py'),Path('body/corridor_tracking/evaluation.py'),Path('body/corridor_tracking/replay_template.html')]},
        configuration=asdict(cfg),
        limitations=['Head box overlap must be visually reviewed; it is not identity truth or recall.',
            'Head detections with malformed 2D boxes are skipped by the input adapter and are not counted as observations.',
            'Head-only detections are retained for 2D association but cannot directly yield a pelvis estimate without a validated cross-model landmark calibration.',
            'SDK-estimated keypoints and partial estimates are not independent surveyed 3D positions.',
            'Changes in track ID numbers and observation counts are diagnostics, not ID accuracy.',
            'No conclusion is made for unseen or fully occluded persons.'])
    dump(a.output/'summary.json',summary)
    (a.output/'report.md').write_text('# 同一SVOの骨格・頭部比較\n\n'
        '[骨格のみ再生](body_only/index.html) / [骨格と頭部の再生](body_plus_heads/index.html) / '
        '[画像確認候補](checkpoint_candidates.csv) / [機械可読集計](summary.json)\n\n'
        '画像枠の重なりは人物の正解や検出率ではなく、元画像で確認する候補。'
        '位置推定は測量値ではない。補間と予測は支持位置数に含めない。設定は未採用。\n',encoding='utf-8')
    print(a.output/'summary.json')


if __name__=='__main__':main()
