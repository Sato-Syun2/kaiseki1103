#!/usr/bin/env python3
"""Inspect sparse depth on manually reviewed pole regions in the test_005 SVO."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from corridor_tracking.data import sha256,transform


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


# Bounds from the source images at the stated times, in full-resolution pixels.
# These regions include some surrounding pixels; a brightness test is not a
# segmentation mask and passing it does NOT prove that depth belongs to the pole.
REGIONS=[
 dict(distance_from_end_m=3,seconds=[2,8],roi=[908,932,590,745]),
 dict(distance_from_end_m=5,seconds=[15,19],roi=[1040,1068,430,530]),
 dict(distance_from_end_m=7,seconds=[26,30],roi=[1110,1135,335,415]),
 dict(distance_from_end_m=9,seconds=[38,43],roi=[1162,1186,280,350]),
 dict(distance_from_end_m=11,seconds=[50,55],roi=[1185,1208,245,310]),
 dict(distance_from_end_m=13,seconds=[63,69],roi=[1200,1225,215,275]),
 dict(distance_from_end_m=15,seconds=[77,83],roi=[1212,1243,195,255]),
]


def select_sample_points(xyz,indices,frame_indices,frame_timestamps,frame):
    """Depth point_frame_index contains sample_index, never the SVO frame number."""
    sample=int(frame['sample_index'])
    positions=np.flatnonzero(frame_indices==sample)
    if len(positions)!=1 or int(frame_timestamps[positions[0]])!=int(frame['image_timestamp_ns']):
        raise ValueError('Depth/image sample index or timestamp mismatch')
    selected=xyz[indices==sample]
    if len(selected)!=int(frame['valid_depth_points']):
        raise ValueError('Depth sample point count mismatch')
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth-export',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.depth_export
    camera=json.loads((root/'camera.json').read_text(encoding='utf-8-sig'))
    cal=json.loads(a.calibration.read_text())
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('status')!='complete':raise ValueError('Depth export incomplete')
    for name in ['camera.json','frames.csv','zed_depth_points.npz']:
        if sha256(root/name)!=manifest['files_sha256'][name]:raise ValueError('Hash mismatch: '+name)
    with (root/'frames.csv').open(newline='',encoding='utf-8-sig') as f:frames=list(csv.DictReader(f))
    with np.load(root/'zed_depth_points.npz') as z:
        xyz=z['points_camera_image_m'];indices=z['point_frame_index']
        frame_indices=z['frame_indices'];frame_timestamps=z['frame_timestamps_ns']
    intr=camera['intrinsics_left'];samples=[];summaries=[]
    for item in REGIONS:
        x0,x1,y0,y1=item['roi'];selected=[f for f in frames if item['seconds'][0]<=float(f['elapsed_s'])<=item['seconds'][1]]
        frame_details=[]
        for f in selected:
            image_path=root/f['image_file']
            if sha256(image_path)!=f['image_sha256']:raise ValueError('Image hash mismatch: '+str(image_path))
            img=np.array(Image.open(image_path).convert('RGB'))
            pts=select_sample_points(xyz,indices,frame_indices,frame_timestamps,f)
            u=np.rint(pts[:,0]/pts[:,2]*intr['fx']+intr['cx']).astype(int)
            v=np.rint(pts[:,1]/pts[:,2]*intr['fy']+intr['cy']).astype(int)
            m=(u>=x0)&(u<=x1)&(v>=y0)&(v<=y1)
            pp,uu,vv=pts[m],u[m],v[m]
            total_roi_points=len(pp)
            bright=img[vv,uu].mean(axis=1)>=160 if len(uu) else np.array([],dtype=bool)
            pp,uu,vv=pp[bright],uu[bright],vv[bright]
            corridor=[transform(pt,cal) for pt in pp]
            row=dict(distance_from_end_m=item['distance_from_end_m'],t=float(f['elapsed_s']),
                     frame_index=int(f['frame_index']),total_roi_points=total_roi_points,bright_roi_points=len(corridor),
                     median_X_m=float(np.median(np.array(corridor)[:,0])) if corridor else None,
                     median_Z_m=float(np.median(np.array(corridor)[:,2])) if corridor else None,
                     image_file=f['image_file'])
            samples.append(row);frame_details.append(row)
        zs=[v['median_Z_m'] for v in frame_details if v['median_Z_m'] is not None]
        summaries.append(dict(**item,camera_to_end_approx_m=.15,
                     nominal_pole_center_from_camera_m=item['distance_from_end_m']-.15,
                     frames=len(selected),frames_with_any_depth=sum(x['total_roi_points']>0 for x in frame_details),
                     total_depth_points=sum(x['total_roi_points'] for x in frame_details),
                     frames_with_bright_depth=sum(x['bright_roi_points']>0 for x in frame_details),
                     bright_depth_points=sum(x['bright_roi_points'] for x in frame_details),
                     median_candidate_Z_m=float(np.median(zs)) if zs else None,
                     interpretation='unverified image-brightness ROI, not a pole depth measurement'))
    a.output.mkdir(parents=True,exist_ok=False)
    write_json(a.output/'pole_depth_diagnostics.json',dict(regions=summaries,
        notes=['Images manually reviewed; station order based on user-provided sequence.',
               'Depth samples matched by sample_index and exact timestamp; SVO frame_index is separate.',
               'x/y ROI is approximate and sparse depth stride is 8 pixels.',
               'Bright appearance does not prove 3D point belongs to the pole.',
               'Floor transform is provisional; individual depth measurements and station labels need validation.',
               'Camera is assumed 0.15m toward corridor interior from end; actual optical center is approximate.',
               'Pole radius 0.025m is not corrected in these diagnostics.',
               'No correction or absolute-accuracy result is derived from unsupported points.'],
        input_hashes={name:sha256(root/name) for name in ['camera.json','frames.csv','zed_depth_points.npz','manifest.json']},
        calibration_sha256=sha256(a.calibration)))
    with (a.output/'pole_depth_samples.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(samples[0]));w.writeheader();w.writerows(samples)
    w,h=600,500;canvas=Image.new('RGB',(w*4,h*2),'white');draw=ImageDraw.Draw(canvas)
    for i,item in enumerate(REGIONS):
        midpoint=sum(item['seconds'])/2;f=min(frames,key=lambda f:abs(float(f['elapsed_s'])-midpoint))
        img=Image.open(root/f['image_file']).convert('RGB');d=ImageDraw.Draw(img)
        x0,x1,y0,y1=item['roi'];d.rectangle((x0,y0,x1,y1),outline='red',width=3)
        img=img.crop((800,150,1400,850)).resize((600,450));x,y=i%4*w,i//4*h
        canvas.paste(img,(x,y+50));draw.text((x+4,y+4),f'{item["distance_from_end_m"]}m, t={float(f["elapsed_s"]):.2f}s',fill='black')
    canvas.save(a.output/'pole_regions.jpg',quality=90)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
