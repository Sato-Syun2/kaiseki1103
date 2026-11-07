#!/usr/bin/env python3
"""Fit camera-to-corridor pose from surveyed points without altering existing calibration."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from corridor_tracking.calibration import robust_fit,apply_transform,evaluate_groups
from corridor_tracking.data import sha256,transform


FIELDS=['point_id','capture_id','split','camera_x_m','camera_y_m','camera_z_m','target_X_m','target_Y_m','target_Z_m']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('points',type=Path)
    p.add_argument('--camera',type=Path,required=True,help='camera.json for this setup/resolution/depth mode')
    p.add_argument('--setup-id',required=True)
    p.add_argument('--output',type=Path,required=True,help='New output directory')
    p.add_argument('--baseline',type=Path)
    p.add_argument('--inlier-threshold-m',type=float,default=.12)
    a=p.parse_args()
    with a.points.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if not set(FIELDS)<=set(reader.fieldnames or []):
            p.error('Point CSV does not contain required metre-coordinate fields')
        rows=list(reader)
    if not rows or any(r['split'] not in ['calibration','validation'] for r in rows):
        p.error('Every point must have split=calibration or validation')
    if any(not r['point_id'] or not r['capture_id'] for r in rows):
        p.error('Point and capture identifiers are required')
    all_rows=rows
    if any(r.get('status','valid') not in ['valid','missing'] for r in rows):
        p.error('Optional status must be valid or missing')
    rows=[r for r in all_rows if r.get('status','valid')=='valid']
    if not rows:
        p.error('No valid camera observations')
    try:
        camera=np.array([[float(r[k]) for k in FIELDS[3:6]] for r in rows])
        target=np.array([[float(r[k]) for k in FIELDS[6:9]] for r in rows])
    except ValueError:
        p.error('All coordinates must be numeric; template placeholders are not measurements')
    if not np.isfinite([camera,target]).all():
        p.error('All coordinates must be finite')
    train=np.array([r['split']=='calibration' for r in rows]);validation=~train
    if train.sum()<6:
        p.error('At least six calibration points are required for a robust fit')
    ids=[{r['point_id'] for r in rows if r['split']==s} for s in ['calibration','validation']]
    if ids[0]&ids[1]:
        p.error('Calibration and validation point IDs must be disjoint')
    captures=[{r['capture_id'] for r in rows if r['split']==s} for s in ['calibration','validation']]
    if captures[0]&captures[1]:
        p.error('Calibration and validation must use separate capture IDs')
    if validation.any() and np.min(np.linalg.norm(target[train,None,:]-target[None,validation,:],axis=2))<.01:
        p.error('Validation must use independent locations, not repeated calibration targets')
    M,inliers=robust_fit(camera[train],target[train],a.inlier_threshold_m)
    predicted=apply_transform(camera,M)
    metadata=json.loads(a.camera.read_text())
    scope={k:metadata.get(k) for k in ['serial_number','width','height','depth_mode','coordinate_system','coordinate_units','intrinsics_left']}
    if metadata.get('setup_id')!=a.setup_id:
        p.error('camera.json setup_id must match --setup-id; do not apply a new setup to old recordings')
    result=dict(schema_version=2,method='surveyed_3d_rigid_ransac',provisional=True,
                setup_id=a.setup_id,applies_to=scope,transform_camera_to_corridor=M.tolist(),
                coordinate_units='meter',calibration_inliers=inliers.tolist(),
                input_hashes={'points':sha256(a.points),'camera':sha256(a.camera)},
                calibration_errors=evaluate_groups(predicted[train],target[train]),
                validation_errors=evaluate_groups(predicted[validation],target[validation]),
                validation_status='evaluated' if validation.any() else 'not_evaluated_no_independent_points',
                adoption='requires_review_of_independent_errors_and_recording_setup',
                missing_point_rate={s:dict(planned=sum(r['split']==s for r in all_rows),
                    missing=sum(r['split']==s and r.get('status','valid')=='missing' for r in all_rows),
                    rate=sum(r['split']==s and r.get('status','valid')=='missing' for r in all_rows)/sum(r['split']==s for r in all_rows)
                    if any(r['split']==s for r in all_rows) else None)
                    for s in ['calibration','validation']},
                missing_rate_scope='Only planned targets listed in input CSV; unlisted failures are unknown')
    if a.baseline:
        baseline=json.loads(a.baseline.read_text())
        old=np.array([transform(v,baseline) for v in camera])
        result['baseline_validation_errors']=evaluate_groups(old[validation],target[validation])
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'calibration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (a.output/'residuals.csv').open('w',newline='') as f:
        fields=['point_id','capture_id','split','error_X_m','error_Y_m','error_Z_m','error_norm_m']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r,delta in zip(rows,predicted-target):
            w.writerow(dict(point_id=r['point_id'],capture_id=r['capture_id'],split=r['split'],
                            **dict(zip(fields[3:6],delta)),error_norm_m=np.linalg.norm(delta)))
    print(json.dumps(result['validation_errors'],ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
