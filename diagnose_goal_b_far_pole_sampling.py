#!/usr/bin/env python3
"""Visualize sampled depth pixel locations near the far pole stations.

This diagnostic never labels a depth sample as belonging to the pole. Each
image is matched to its depth sample using sample_index and exact timestamp.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from corridor_tracking.data import sha256
from inspect_group002_pole import REGIONS,select_sample_points


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth-export',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.depth_export
    if a.output.exists():raise FileExistsError(a.output)
    manifest=json.loads((root/'manifest.json').read_text());camera=json.loads((root/'camera.json').read_text())
    for name in ['camera.json','frames.csv','zed_depth_points.npz']:
        if sha256(root/name)!=manifest['files_sha256'][name]:raise ValueError('Input hash mismatch: '+name)
    with (root/'frames.csv').open(newline='',encoding='utf-8-sig') as f:frames=list(csv.DictReader(f))
    intr=camera['intrinsics_left'];selected=[];sheet=Image.new('RGB',(1280,2000),'white');draw=ImageDraw.Draw(sheet)
    with np.load(root/'zed_depth_points.npz') as z:
        for index,region in enumerate(REGIONS[3:]):
            midpoint=sum(region['seconds'])/2
            frame=min(frames,key=lambda f:abs(float(f['elapsed_s'])-midpoint))
            if not region['seconds'][0]<=float(frame['elapsed_s'])<=region['seconds'][1]:
                raise ValueError('No depth sample inside the reviewed station interval')
            image=root/frame['image_file']
            if sha256(image)!=frame['image_sha256']:raise ValueError('Image hash mismatch')
            pts=select_sample_points(z['points_camera_image_m'],z['point_frame_index'],z['frame_indices'],z['frame_timestamps_ns'],frame)
            u=np.rint(pts[:,0]/pts[:,2]*intr['fx']+intr['cx']).astype(int)
            v=np.rint(pts[:,1]/pts[:,2]*intr['fy']+intr['cy']).astype(int)
            x0,x1,y0,y1=region['roi'];left=(x0+x1)//2-40;top=(y0+y1)//2-30
            crop=Image.open(image).convert('RGB').crop((left,top,left+80,top+60)).resize((640,480),Image.Resampling.NEAREST)
            marked=crop.copy();d=ImageDraw.Draw(marked)
            ids=np.flatnonzero((u>=left)&(u<left+80)&(v>=top)&(v<top+60))
            for j in ids:
                x=(int(u[j])-left)*8;y=(int(v[j])-top)*8
                d.ellipse((x-4,y-4,x+4,y+4),outline='red',width=2)
            sheet.paste(crop,(0,index*500+20));sheet.paste(marked,(640,index*500+20))
            draw.text((3,index*500),f"{region['distance_from_end_m']}m t={float(frame['elapsed_s']):.3f}; red = sampled depth pixels",fill='black')
            selected.append(dict(station_m=region['distance_from_end_m'],elapsed_s=float(frame['elapsed_s']),
                sample_index=int(frame['sample_index']),svo_frame_index=int(frame['frame_index']),
                timestamp_ns=frame['image_timestamp_ns'],image_file=frame['image_file'],image_sha256=frame['image_sha256'],
                crop_uv=[left,top,left+80,top+60],sampled_pixels_in_crop=len(ids)))
    a.output.mkdir(parents=True,exist_ok=False);sheet.save(a.output/'far_pole_sampling.jpg',quality=95)
    report=dict(selected=selected,scope='Four chosen saved images, one at each nominal station, not a complete depth-availability analysis',
        limitations=['A red marker means a depth sample exists, not that its depth belongs to the pole.',
                     'Apparent darkness, sparse sampling, blur and background contamination cannot be separated by this visualization alone.',
                     'No distance estimate or calibration is produced.'],
        pixel_stride=camera['pixel_stride'],sample_period_s=camera['sample_period_s'],
        input_sha256={n:sha256(root/n) for n in ['manifest.json','camera.json','frames.csv','zed_depth_points.npz']},
        script_sha256=sha256(Path(__file__)),image_sha256=sha256(a.output/'far_pole_sampling.jpg'))
    (a.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(a.output/'far_pole_sampling.jpg')


if __name__=='__main__':main()
