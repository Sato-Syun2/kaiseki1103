#!/usr/bin/env python3
"""Inspect exact-frame depth against manually selected image regions and original BODY."""
import csv
import hashlib
import html
import json
from pathlib import Path
import cv2
import numpy as np
from zed_sdk_package.tracking_v2.validate_export import validate_export

BASE=Path('/data/experiment_data/kaiseki1103/exchange/group003_20261104_candidate_01/recording_018/body')
RUN=Path('/data/experiment_data/kaiseki1103/exchange/rec018_diagnosis_20261105_01')
OUT=Path('results/tracking_v2/group003_018_depth_analysis_20261105_01')
FRAMES=[3,4,5,6,7,8,9,12,15,18,19,21,24,27,30,45,60]
# Fixed image coordinates selected after viewing frame 6; unsegmented rectangles, not ground truth.
REGIONS={'front_vest':(1256,204,1288,252),'rear_vest':(1230,136,1258,180),'near_floor':(1240,620,1290,670)}

def readcsv(p):
    with p.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()
def main():
    if OUT.exists():raise ValueError('output already exists')
    for folder in [BASE,RUN/'body']:validate_export(folder)
    dc=json.loads((RUN/'depth/camera.json').read_text());bc=json.loads((RUN/'body/camera.json').read_text());oc=json.loads((BASE/'camera.json').read_text())
    manifest=json.loads((RUN/'depth/manifest.json').read_text());
    if manifest['status']!='complete' or any(sha(RUN/'depth'/k)!=v for k,v in manifest['files_sha256'].items()):raise ValueError('depth output hash mismatch')
    if not (dc['source_svo_sha256']==bc['source_svo_sha256']==oc['source_svo_sha256']):raise ValueError('SVO hash mismatch')
    for k in ('serial_number','width','height','setup_id','intrinsics_left','depth_mode'):
        if dc[k]!=bc[k]:raise ValueError('Camera mismatch '+k)
    baseline={r['frame_index']:r for r in readcsv(BASE/'frames.csv')};timeline={r['frame_index']:r for r in readcsv(RUN/'body/frames.csv')}
    if baseline.keys()!=timeline.keys() or any(baseline[k]['image_timestamp_ns']!=v['image_timestamp_ns'] for k,v in timeline.items()):raise ValueError('Body timeline mismatch')
    frames=readcsv(RUN/'depth/frames.csv')
    if [int(f['frame_index']) for f in frames]!=FRAMES:raise ValueError('Unexpected depth frames')
    if any(f['image_timestamp_ns']!=timeline[f['frame_index']]['image_timestamp_ns'] for f in frames):raise ValueError('Depth timeline mismatch')
    def obs(folder):
        return {(r['frame_index'],r['body_id']):r for r in readcsv(folder/'bodies.csv')}
    orig,repeat=obs(BASE),obs(RUN/'body')
    if orig.keys()!=repeat.keys():raise ValueError('SDK IDs differ')
    fields=['tracking_state','confidence','keypoints_2d_json','keypoints_3d_camera_json','keypoint_confidence_json','position_json','velocity_json','is_new','detection_timestamp_ns']
    equality={k:sum(orig[x][k]==repeat[x][k] for x in orig) for k in fields}
    K=dc['intrinsics_left'];w,h=dc['width'],dc['height']; archive=np.load(RUN/'depth/zed_depth_points.npz');points=archive['points_camera_image_m'];idx=archive['point_frame_index']
    output=[];OUT.mkdir(parents=True,exist_ok=False);(OUT/'images').mkdir()
    palette={'front_vest':(0,255,255),'rear_vest':(255,160,0),'near_floor':(40,180,255)}
    for f in frames:
        frame=int(f['frame_index']); sample=int(f['sample_index']);p=points[idx==sample];z=p[:,2]
        u=np.rint(K['fx']*p[:,0]/z+K['cx']).astype(np.int32);v=np.rint(K['fy']*p[:,1]/z+K['cy']).astype(np.int32)
        usable=(u>=0)&(u<w)&(v>=0)&(v<h)&(z>0);u,v,z=u[usable],v[usable],z[usable]
        if np.any((u%2)!=0) or np.any((v%2)!=0):raise ValueError('Projected grid does not match 2-pixel sampling')
        regions={}
        for name,(x0,y0,x1,y1) in REGIONS.items():
            sel=(u>=x0)&(u<x1)&(v>=y0)&(v<y1);vals=z[sel]
            total=len(range(x0+(x0%2),x1,2))*len(range(y0+(y0%2),y1,2))
            regions[name]={'rectangle_xyxy':[x0,y0,x1,y1],'valid':len(vals),'expected_grid_points':total,
                'valid_fraction':len(vals)/total,'median_m':float(np.median(vals)) if len(vals) else None,
                'p10_m':float(np.percentile(vals,10)) if len(vals) else None,'p90_m':float(np.percentile(vals,90)) if len(vals) else None}
        body=[]
        for ident in ('0','1'):
            r=orig.get((str(frame),ident))
            if r:
                body.append({'sdk_id':ident,'pelvis_camera_m':json.loads(r['keypoints_3d_camera_json'])[0],
                             'pelvis_pixel':json.loads(r['keypoints_2d_json'])[0],
                             'confidence':float(r['confidence']),'pelvis_confidence':json.loads(r['keypoint_confidence_json'])[0]})
        output.append({'frame_index':frame,'elapsed_s':float(f['elapsed_s']),'regions':regions,'body':body})
        image=cv2.imread(str(RUN/'depth'/f['image_file']));depth=np.full((h//2,w//2),np.nan,np.float32);depth[v//2,u//2]=z
        n=np.nan_to_num((np.clip(depth,2,20)-2)/18,nan=0);color=cv2.applyColorMap((n*255).astype(np.uint8),cv2.COLORMAP_TURBO);color[~np.isfinite(depth)]=0
        color=cv2.resize(color,(w,h),interpolation=cv2.INTER_NEAREST)
        for name,(x0,y0,x1,y1) in REGIONS.items():
            cv2.rectangle(image,(x0,y0),(x1,y1),palette[name],2);cv2.rectangle(color,(x0,y0),(x1,y1),palette[name],2)
        # Consistent 1180..1360,80..380 crop emphasizes the reviewed image regions.
        crop=(1180,80,1360,380); x0,y0,x1,y1=crop
        rgb=cv2.resize(image[y0:y1,x0:x1],(360,600)); dep=cv2.resize(color[y0:y1,x0:x1],(360,600),interpolation=cv2.INTER_NEAREST)
        canvas=np.concatenate([rgb,dep],axis=1);cv2.rectangle(canvas,(0,0),(720,32),(0,0,0),-1)
        cv2.putText(canvas,f'frame {frame}, {float(f["elapsed_s"]):.3f}s | RGB / depth 2-20m', (6,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
        cv2.imwrite(str(OUT/'images'/f'frame_{frame:03d}.jpg'),canvas)
    data={'source_svo_sha256':dc['source_svo_sha256'],'body_observation_count':len(orig),'equal_fields_counts':equality,
          'limitations':['Rectangles were selected after inspecting frame 6; their contents can include background and are not ground truth.',
          'Depth exported in a separate SDK pass without body or positional tracking; the precise internal depth values used by body tracking are not established.',
          'Valid sample percentages only apply to the 2-pixel grid and exported range/confidence filtering.','Frame-to-frame 2D rectangle does not track individual motion; compare the saved RGB crops.'],
          'depth_camera':dc,'frames':output}
    (OUT/'summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    fields=['frame_index','elapsed_s','region','valid','expected_grid_points','valid_fraction','median_m','p10_m','p90_m']
    with (OUT/'regions.csv').open('w',encoding='utf-8-sig',newline='') as s:
        wr=csv.DictWriter(s,fieldnames=fields);wr.writeheader()
        for f in output:
            for name,v in f['regions'].items():wr.writerow({k:({'frame_index':f['frame_index'],'elapsed_s':f['elapsed_s'],'region':name}|v)[k] for k in fields})
    images=''.join(f'<section><h2>Frame {f["frame_index"]}, {f["elapsed_s"]:.3f}秒</h2><img src="images/frame_{f["frame_index"]:03d}.jpg"><pre>{html.escape(json.dumps(f["regions"],ensure_ascii=False,indent=2))}</pre></section>' for f in output)
    (OUT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>録画18の深度</title><style>body{font:16px sans-serif;margin:24px}img{max-width:100%}section{border-top:1px solid #aaa}</style><h1>録画18：同時刻の画像と深度</h1><p>画像と別パスのZED深度。右は2〜20mの表示、黒は無効・未保存。左の青緑枠は奥の赤い服、黄色枠は手前の青い服の画像領域。固定矩形はフレーム6を見て指定し、人物の厳密な領域や正解ではありません。背景を含む可能性があります。色と矩形は全フレーム共通です。</p>'+images+'<p><a href="summary.json">数値と条件</a></p>',encoding='utf-8')
    print('repeat counts',equality,'/',len(orig)); print('saved',OUT)
    for f in output[:7]:print(f['frame_index'],round(f['elapsed_s'],3),{n:(round(v['median_m'],2) if v['median_m'] else None,v['valid'],v['expected_grid_points']) for n,v in f['regions'].items()})

if __name__=='__main__':main()
