#!/usr/bin/env python3
"""Repeat the previously selected, visually reviewed pole pixels over time.

These selected pixels are not an unbiased sample, and are not surveyed 3D
correspondences. This is a stability diagnostic, not a calibration fit.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from corridor_tracking.data import sha256, transform
from inspect_group002_pole import select_sample_points


STATIONS = [
    dict(distance_m=3, start_s=2, end_s=8, u=920, v=608),
    dict(distance_m=5, start_s=15, end_s=19, u=1048, v=528),
    dict(distance_m=7, start_s=26, end_s=30, u=1128, v=392),
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth-export', type=Path, required=True)
    p.add_argument('--calibration', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); root=a.depth_export
    manifest=json.loads((root/'manifest.json').read_text())
    for name in ['camera.json','frames.csv','zed_depth_points.npz']:
        if sha256(root/name)!=manifest['files_sha256'][name]:
            raise ValueError('Input hash mismatch: '+name)
    camera=json.loads((root/'camera.json').read_text()); intr=camera['intrinsics_left']
    calibration=json.loads(a.calibration.read_text())
    with (root/'frames.csv').open(newline='',encoding='utf-8-sig') as f: frames=list(csv.DictReader(f))
    rows=[]
    with np.load(root/'zed_depth_points.npz') as z:
        xyz, ids, fi, ft = (z[k] for k in ['points_camera_image_m','point_frame_index','frame_indices','frame_timestamps_ns'])
        for station in STATIONS:
            selected=[f for f in frames if station['start_s']<=float(f['elapsed_s'])<=station['end_s']]
            for frame in selected:
                image=root/frame['image_file']
                if sha256(image)!=frame['image_sha256']:raise ValueError('Image hash mismatch: '+str(image))
                points=select_sample_points(xyz,ids,fi,ft,frame)
                u=np.rint(points[:,0]/points[:,2]*intr['fx']+intr['cx']).astype(int)
                v=np.rint(points[:,1]/points[:,2]*intr['fy']+intr['cy']).astype(int)
                found=np.flatnonzero((u==station['u'])&(v==station['v']))
                if len(found)>1:raise ValueError('Duplicate pixel')
                value=transform(points[found[0]],calibration)[0] if len(found) else None
                rows.append(dict(station_from_end_m=station['distance_m'],elapsed_s=float(frame['elapsed_s']),
                    sample_index=int(frame['sample_index']),svo_frame_index=int(frame['frame_index']),
                    timestamp_ns=frame['image_timestamp_ns'],u=station['u'],v=station['v'],
                    corridor_X_m=value,estimated_center_X_m=station['distance_m']-.15,
                    surface_minus_approx_center_m=value-(station['distance_m']-.15) if value is not None else None,
                    image_file=frame['image_file']))
    summaries=[]
    for s in STATIONS:
        subset=[r for r in rows if r['station_from_end_m']==s['distance_m']]
        values=[r['corridor_X_m'] for r in subset if r['corridor_X_m'] is not None]
        summaries.append(dict(distance_from_end_m=s['distance_m'],samples=len(subset),valid=len(values),
            median_X_m=float(np.median(values)) if values else None,
            min_X_m=float(np.min(values)) if values else None,
            max_X_m=float(np.max(values)) if values else None,
            median_surface_minus_approx_center_m=float(np.median(values)-(s['distance_m']-.15)) if values else None))
    a.output.mkdir(parents=True,exist_ok=False)
    with (a.output/'samples.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(stations=summaries,limitation='Preselected single surface pixel per station; correlated repeated frames; not an independent accuracy estimate or a calibration fit',
        assumptions='15 cm approximate camera offset, no pole radius correction, provisional group002 floor/wall transform; camera pose assumed unchanged',
        depth_inputs_sha256={name:sha256(root/name) for name in ['camera.json','frames.csv','zed_depth_points.npz','manifest.json']},
        calibration_sha256=sha256(a.calibration),script_sha256=sha256(Path(__file__)))
    (a.output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
