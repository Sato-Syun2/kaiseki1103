#!/usr/bin/env python3
"""Record three manually image-reviewed sparse pole pixels as illustrative probes."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from corridor_tracking.data import sha256,transform
from inspect_group002_pole import select_sample_points
from process_tracking_v2 import write_json


EXAMPLES=[dict(station_from_end_m=3,t_s=5.017,u=920,v=608),
          dict(station_from_end_m=5,t_s=17.06,u=1048,v=528),
          dict(station_from_end_m=7,t_s=28.16,u=1128,v=392)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth-export',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=a.depth_export
    camera=json.loads((r/'camera.json').read_text());cal=json.loads(a.calibration.read_text())
    intr=camera['intrinsics_left']
    with (r/'frames.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    with np.load(r/'zed_depth_points.npz') as z:
        xyz,ids,fi,ft=(z[k] for k in ['points_camera_image_m','point_frame_index','frame_indices','frame_timestamps_ns'])
    result=[];out=Image.new('RGB',(1200,590),'white');draw=ImageDraw.Draw(out)
    for i,e in enumerate(EXAMPLES):
        f=min(rows,key=lambda f:abs(float(f['elapsed_s'])-e['t_s']))
        points=select_sample_points(xyz,ids,fi,ft,f)
        uu=np.rint(points[:,0]/points[:,2]*intr['fx']+intr['cx']).astype(int)
        vv=np.rint(points[:,1]/points[:,2]*intr['fy']+intr['cy']).astype(int)
        matches=np.flatnonzero((uu==e['u'])&(vv==e['v']))
        if len(matches)!=1:raise ValueError('No unique selected SDK point at reviewed pixel')
        point=points[matches[0]];corridor=transform(point,cal)
        expected=e['station_from_end_m']-.15
        result.append(dict(**e,actual_t_s=float(f['elapsed_s']),sample_index=int(f['sample_index']),
            svo_frame_index=int(f['frame_index']),timestamp_ns=f['image_timestamp_ns'],
            camera_xyz_m=point.tolist(),corridor_xyz_m=corridor,assumed_pole_center_X_m=expected,
            surface_minus_center_m=corridor[0]-expected,
            uncertainty='one manually selected surface pixel; .15m camera offset approximate; no radius correction; provisional transform'))
        im=Image.open(r/f['image_file']).convert('RGB')
        if sha256(r/f['image_file'])!=f['image_sha256']:raise ValueError('image hash mismatch')
        im=im.crop((e['u']-50,e['v']-70,e['u']+50,e['v']+70)).resize((400,560))
        d=ImageDraw.Draw(im);d.ellipse((195,275,205,285),outline='red',width=2)
        out.paste(im,(400*i,30));draw.text((400*i+5,6),f'{e["station_from_end_m"]}m, t={float(f["elapsed_s"]):.2f}, pixel {e["u"]},{e["v"]}',fill='black')
    a.output.mkdir(parents=True,exist_ok=False)
    out.save(a.output/'reviewed_pixels.jpg',quality=90)
    write_json(a.output/'examples.json',dict(examples=result,method='one manually visually selected sparse pixel per near station',
        interpretation='illustrative only; not a survey validation, accuracy estimate, fitted correction, or representative sample',
        setup_assumption='user reports same physical camera location; orientation and optical-centre offset are not separately measured',
        points_sha256=sha256(r/'zed_depth_points.npz'),calibration_sha256=sha256(a.calibration),
        script_sha256=sha256(Path(__file__))))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
