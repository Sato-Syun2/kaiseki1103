#!/usr/bin/env python3
"""Compare BODY_18 fitting off/on to BODY_34 at the same SVO frames."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import cv2
import numpy as np
from body.compare_sdk_stability import load, point
from corridor_tracking.data import transform

HIP={'BODY_18':8,'BODY_34':22}  # RIGHT_HIP; these are estimates, not guaranteed equivalent landmarks
BONES={
 'BODY_18':[(0,1),(1,2),(2,3),(3,4),(1,5),(5,6),(6,7),(2,8),(8,9),(9,10),(5,11),(11,12),(12,13),(2,5),(8,11)],
 'BODY_34':[(0,1),(1,2),(2,3),(3,26),(2,5),(5,6),(6,7),(2,12),(12,13),(13,14),(0,18),(18,19),(19,20),(0,22),(22,23),(23,24)]}
NAMES={
 'BODY_18':['NOSE','NECK','RIGHT_SHOULDER','RIGHT_ELBOW','RIGHT_WRIST','LEFT_SHOULDER','LEFT_ELBOW','LEFT_WRIST','RIGHT_HIP','RIGHT_KNEE','RIGHT_ANKLE','LEFT_HIP','LEFT_KNEE','LEFT_ANKLE','RIGHT_EYE','LEFT_EYE','RIGHT_EAR','LEFT_EAR'],
 'BODY_34':['PELVIS','NAVAL_SPINE','CHEST_SPINE','NECK','LEFT_CLAVICLE','LEFT_SHOULDER','LEFT_ELBOW','LEFT_WRIST','LEFT_HAND','LEFT_HANDTIP','LEFT_THUMB','RIGHT_CLAVICLE','RIGHT_SHOULDER','RIGHT_ELBOW','RIGHT_WRIST','RIGHT_HAND','RIGHT_HANDTIP','RIGHT_THUMB','LEFT_HIP','LEFT_KNEE','LEFT_ANKLE','LEFT_FOOT','RIGHT_HIP','RIGHT_KNEE','RIGHT_ANKLE','RIGHT_FOOT','HEAD','NOSE','LEFT_EYE','LEFT_EAR','RIGHT_EYE','RIGHT_EAR','LEFT_HEEL','RIGHT_HEEL']}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()
def rows(p):
    with p.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def validate_image_timeline(image_frames, byframe):
    for frame in image_frames:
        idx=int(frame['frame_index'])
        if idx not in byframe or frame['image_timestamp_ns']!=byframe[idx]['image_timestamp_ns']:
            raise ValueError('Image timestamp mismatch')

def compatibility(base,d,expected_fitting):
    a,b=base['camera'],d['camera']
    if not a.get('source_svo_sha256') or a.get('source_svo_sha256')!=b.get('source_svo_sha256'):raise ValueError('SVO SHA-256 mismatch')
    for k in ['sdk_version','setup_id','serial_number','width','height','fps','coordinate_system','coordinate_units','depth_mode','intrinsics_left','body_tracking_model','body_tracking_model_gen','prediction_timeout_s','detection_confidence_threshold','minimum_keypoints_threshold','skeleton_smoothing','positional_tracking_static']:
        if a.get(k)!=b.get(k):raise ValueError('Setting mismatch: '+k)
    if b.get('body_format')!='BODY_18' or b.get('detection_kind')!='body18' or b.get('body_fitting') is not expected_fitting:raise ValueError('BODY_18 format or fitting request mismatch')
    if [(f['frame_index'],f['image_timestamp_ns']) for f in base['frames']]!=[(f['frame_index'],f['image_timestamp_ns']) for f in d['frames']]:raise ValueError('Frame/timestamp mismatch')

def measurements(d,calibration):
    fmt=d['camera']['body_format']; joint=HIP[fmt];tracks=defaultdict(list); per=[]; counts=Counter()
    for order,f in enumerate(d['frames']):
        frame=int(f['frame_index']);t=float(f['elapsed_s']);valid=0
        for b in d['bodies'].get(frame,[]):
            counts['body_observations']+=1
            j=b['joints'];pix=b['pixels'];conf=b['conf']; c=conf[joint] if joint<len(conf) else None
            p=j[joint] if joint<len(j) else None;u=pix[joint] if joint<len(pix) else None
            confok=isinstance(c,(int,float)) and math.isfinite(c) and c>=20
            ok=b['tracking_state'].upper()=='OK' and point(p,3) and confok
            inimage=point(u,2) and 0<=u[0]<d['camera']['width'] and 0<=u[1]<d['camera']['height']
            corridor=transform(p,calibration) if point(p,3) and calibration else None
            if ok:
                counts['supported_right_hip']+=1;valid+=1
                counts['nonpositive_z']+=int(p[2]<=0)
                counts['out_of_image']+=int(not inimage)
                tracks[b['id']].append((order,frame,t,p))
            per.append(dict(frame_index=frame,t_s=t,sdk_id=b['id'],state=b['tracking_state'],
                right_hip_confidence=c if isinstance(c,(int,float)) and math.isfinite(c) else None,
                accepted_for_diagnostic=ok,in_image=inimage,cam_x_m=p[0] if point(p,3) else None,
                cam_y_m=p[1] if point(p,3) else None,cam_z_m=p[2] if point(p,3) else None,
                image_u=u[0] if point(u,2) else None,image_v=u[1] if point(u,2) else None,
                corridor_X_m=corridor[0] if corridor is not None else None,corridor_Y_m=corridor[1] if corridor is not None else None,
                corridor_Z_m=corridor[2] if corridor is not None else None))
        counts['frames_with_any_position']+=int(valid>0);counts['frames_with_at_least_two_positions']+=int(valid>=2)
    counts['frames']=len(d['frames']); counts['sdk_id_count']=len(tracks)
    events=[]
    for ident,seq in tracks.items():
        for a,b in zip(seq,seq[1:]):
            dt=b[2]-a[2]
            if b[0]!=a[0]+1 or not 0<dt<=.05:continue
            counts['adjacent_pairs']+=1;dist=math.dist(a[3],b[3])
            if dist>.75 and dist/dt>6:
                counts['large_jumps']+=1;events.append(dict(sdk_id=ident,from_frame=a[1],to_frame=b[1],t_s=b[2],distance_m=dist,dt_s=dt))
    for k in ['body_observations','supported_right_hip','nonpositive_z','out_of_image','frames_with_any_position','frames_with_at_least_two_positions','adjacent_pairs','large_jumps']:counts[k]+=0
    return dict(counts),per,events

def draw(image,d,frame,label,crop):
    im=image.copy();fmt=d['camera']['body_format']; hip=HIP[fmt]
    for r in d['bodies'].get(frame,[]):
        ps=r['pixels'];cs=r['conf'];col=[(0,130,255),(220,20,220),(30,200,20),(250,120,30)][abs(r['id'])%4]
        for a,b in BONES[fmt]:
            if max(a,b)>=len(ps) or max(a,b)>=len(cs) or not(point(ps[a],2) and point(ps[b],2)) or not all(isinstance(cs[k],(int,float)) and math.isfinite(cs[k]) and cs[k]>=20 for k in (a,b)):continue
            if max(abs(x) for j in (a,b) for x in ps[j])>1e6:continue
            ok,p,q=cv2.clipLine((0,0,im.shape[1],im.shape[0]),tuple(map(round,ps[a])),tuple(map(round,ps[b])))
            if ok:cv2.line(im,p,q,col,3,cv2.LINE_AA)
        if hip<len(ps) and point(ps[hip],2) and max(abs(x) for x in ps[hip])<1e6:
            x,y=map(round,ps[hip]);
            if 0<=x<im.shape[1] and 0<=y<im.shape[0]:cv2.putText(im,f'ID {r["id"]}',(x,y),cv2.FONT_HERSHEY_SIMPLEX,.6,col,2,cv2.LINE_AA)
    if crop:
        x0,y0,x1,y1=crop;im=im[y0:y1,x0:x1]
    width=360;height=840;scale=min(width/im.shape[1],height/im.shape[0]);size=(max(1,round(im.shape[1]*scale)),max(1,round(im.shape[0]*scale)))
    small=cv2.resize(im,size);canvas=np.full((height,width,3),25,np.uint8);x=(width-size[0])//2;y=(height-size[1])//2;canvas[y:y+size[1],x:x+size[0]]=small
    cv2.rectangle(canvas,(0,0),(width,31),(0,0,0),-1);cv2.putText(canvas,label,(6,22),cv2.FONT_HERSHEY_SIMPLEX,.52,(255,255,255),1,cv2.LINE_AA)
    return canvas

def projected(p,calibration):
    if calibration:
        x,y,z=transform(p,calibration)
        return (x-.65*y, .2*x+.35*y-z)
    return (p[0]+.35*p[2],p[1]-.18*p[2])

def bounds_scene(datasets,frame,calibration):
    points=[]
    for d in datasets.values():
        for r in d['bodies'].get(frame,[]):
            for p in r['joints']:
                if point(p,3) and max(abs(x) for x in p)<100:points.append(projected(p,calibration))
    if not points:return (-2,2,-2,2)
    v=np.asarray(points);lo=np.percentile(v,1,axis=0);hi=np.percentile(v,99,axis=0)
    center=(lo+hi)/2;half=np.maximum((hi-lo)/2+.3,.5)
    return (center[0]-half[0],center[0]+half[0],center[1]-half[1],center[1]+half[1])

def draw_3d(d,frame,label,bounds,calibration):
    width,height=360,400;im=np.full((height,width,3),245,np.uint8);xmin,xmax,ymin,ymax=bounds
    scale=min((width-40)/(xmax-xmin),(height-65)/(ymax-ymin))
    def xy(p):
        x,y=projected(p,calibration)
        return (round(width/2+(x-(xmin+xmax)/2)*scale),round((height+25)/2+(y-(ymin+ymax)/2)*scale))
    for r in d['bodies'].get(frame,[]):
        js=r['joints'];cs=r['conf'];col=[(0,130,255),(220,20,220),(30,200,20),(250,120,30)][abs(r['id'])%4]
        for i,j in BONES[d['camera']['body_format']]:
            if max(i,j)>=len(js) or max(i,j)>=len(cs) or not(point(js[i],3) and point(js[j],3)) or not all(isinstance(cs[k],(float,int)) and math.isfinite(cs[k]) and cs[k]>=20 for k in (i,j)):continue
            if max(abs(x) for k in (i,j) for x in js[k])>100:continue
            ok,p,q=cv2.clipLine((0,28,width,height-28),xy(js[i]),xy(js[j]))
            if ok:cv2.line(im,p,q,col,3,cv2.LINE_AA)
    cv2.rectangle(im,(0,0),(width,28),(45,45,45),-1)
    cv2.putText(im,('3D corridor | ' if calibration else '3D camera | ')+label,(4,20),cv2.FONT_HERSHEY_SIMPLEX,.46,(255,255,255),1,cv2.LINE_AA)
    return im

def write_joints(d,path,calibration):
    fmt=d['camera']['body_format']
    fields=['frame_index','t_s','sdk_id','state','joint_index','joint_name','confidence','image_u','image_v','cam_x_m','cam_y_m','cam_z_m','corridor_X_m','corridor_Y_m','corridor_Z_m']
    with path.open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for f in d['frames']:
            frame=int(f['frame_index'])
            for r in d['bodies'].get(frame,[]):
                for i,name in enumerate(NAMES[fmt]):
                    p=r['joints'][i] if i<len(r['joints']) else None; uv=r['pixels'][i] if i<len(r['pixels']) else None
                    c=r['conf'][i] if i<len(r['conf']) else None
                    corridor=transform(p,calibration) if calibration and point(p,3) else None
                    writer.writerow(dict(frame_index=frame,t_s=f['elapsed_s'],sdk_id=r['id'],state=r['tracking_state'],joint_index=i,joint_name=name,
                        confidence=c if isinstance(c,(int,float)) and math.isfinite(c) else None,
                        image_u=uv[0] if point(uv,2) else None,image_v=uv[1] if point(uv,2) else None,
                        cam_x_m=p[0] if point(p,3) else None,cam_y_m=p[1] if point(p,3) else None,cam_z_m=p[2] if point(p,3) else None,
                        corridor_X_m=corridor[0] if corridor is not None else None,corridor_Y_m=corridor[1] if corridor is not None else None,corridor_Z_m=corridor[2] if corridor is not None else None))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body34',type=Path,required=True);p.add_argument('--body18-off',type=Path,required=True);p.add_argument('--body18-on',type=Path,required=True)
    p.add_argument('--image-export',type=Path,help='validated same-SVO image/depth export with exact frames')
    p.add_argument('--calibration',type=Path,help='matching provisional corridor calibration JSON')
    p.add_argument('--crop',type=int,nargs=4,help='x0 y0 x1 y1 image crop for all panels')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output must be a new directory')
    datasets={'BODY34':load(a.body34),'BODY18_off':load(a.body18_off),'BODY18_on':load(a.body18_on)};base=datasets['BODY34']
    if base['camera'].get('body_format')!='BODY_34':raise ValueError('Reference must be BODY_34')
    compatibility(base,datasets['BODY18_off'],False);compatibility(base,datasets['BODY18_on'],True)
    calibration=json.loads(a.calibration.read_text()) if a.calibration else None
    if calibration:
        meta=base['camera']; applies=calibration.get('applies_to',{})
        if calibration.get('setup_id')!=meta.get('setup_id'):raise ValueError('Calibration setup mismatch')
        for k in ['serial_number','width','height','depth_mode','coordinate_units']:
            if applies.get(k) is not None and applies[k]!=meta.get(k):raise ValueError('Calibration camera mismatch: '+k)
        if applies.get('intrinsics_left') and any(abs(applies['intrinsics_left'][k]-meta['intrinsics_left'][k])>1.0 for k in ['fx','fy','cx','cy']):raise ValueError('Calibration intrinsics differ by over 1px')
    crop=a.crop
    if crop and not(0<=crop[0]<crop[2]<=base['camera']['width'] and 0<=crop[1]<crop[3]<=base['camera']['height']):raise ValueError('Invalid crop')
    image_root=base['folder']; image_frames=[f for f in base['frames'] if f.get('image_file')]
    if a.image_export:
        image_root=a.image_export.resolve();cam=json.loads((image_root/'camera.json').read_text());man=json.loads((image_root/'manifest.json').read_text())
        if man.get('status')!='complete' or cam.get('source_svo_sha256')!=base['camera']['source_svo_sha256']:raise ValueError('Image source mismatch')
        for k,h in man['files_sha256'].items():
            q=(image_root/k).resolve()
            if not q.is_relative_to(image_root) or not q.is_file() or sha(q)!=h:raise ValueError('Image export hash mismatch: '+k)
        image_frames=rows(image_root/'frames.csv')
        validate_image_timeline(image_frames,base['byframe'])
    result={};series={};events={}
    for name,d in datasets.items():result[name],series[name],events[name]=measurements(d,calibration)
    a.output.mkdir(parents=True,exist_ok=False);(a.output/'images').mkdir()
    for name,seq in series.items():
        with (a.output/(name+'_right_hip.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            fields=['frame_index','t_s','sdk_id','state','right_hip_confidence','accepted_for_diagnostic','in_image','cam_x_m','cam_y_m','cam_z_m','image_u','image_v','corridor_X_m','corridor_Y_m','corridor_Z_m']
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(seq)
        write_joints(datasets[name],a.output/(name+'_all_joints.csv'),calibration)
    panels=[]
    for f in image_frames:
        frame=int(f['frame_index']);im=cv2.imread(str(image_root/f['image_file']))
        if im is None or im.shape[:2]!=(base['camera']['height'],base['camera']['width']):raise ValueError('Invalid image')
        bounds=bounds_scene(datasets,frame,calibration)
        canvas=np.concatenate([np.concatenate([draw(im,d,frame,name,crop),draw_3d(d,frame,name,bounds,calibration)],axis=0) for name,d in datasets.items()],axis=1)
        path=a.output/'images'/f'frame_{frame:06d}.jpg'
        if not cv2.imwrite(str(path),canvas):raise OSError('Cannot write '+str(path))
        panels.append(f'<section><h3>Frame {frame} / {float(f["elapsed_s"]):.3f}秒</h3><img loading="lazy" src="images/{path.name}"></section>')
    sdk_logs={}
    for name,d in datasets.items():
        path=d['folder'].parent/'export.log'
        if path.is_file():
            lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
            sdk_logs[name]={'path':str(path),'sha256':sha(path),'warning_lines':[x for x in lines if 'warning' in x.lower()][:100]}
        else:sdk_logs[name]={'path':None,'warning_lines':[],'note':'SDK log unavailable'}
    summary={'counts':result,'large_jump_events':events,'source_svo_sha256':base['camera']['source_svo_sha256'],
        'inputs':{name:{'folder':str(d['folder']),'hashes':d['hashes'],'camera':d['camera']} for name,d in datasets.items()},
        'image_export':str(image_root),'sdk_logs':sdk_logs,'calibration':str(a.calibration) if a.calibration else None,
        'calibration_sha256':sha(a.calibration) if a.calibration else None,
        'limitations':['Right-hip points correspond by name only; not proven to be exactly the same anatomical landmark.',
                       'BODY_18 IDs and BODY_34 IDs are independent; do not equate IDs across runs.',
                       'Fitting settings are requested parameters; SDK logs must be checked for warnings or overrides.',
                       'Counts are diagnostics, not false-positive rate, measured-position accuracy, or person recall.',
                       'The same visible person may be omitted; fewer jumps can reflect missing observations.',
                       'Corridor calibration is provisional and camera-frame 3D is SDK estimation.']}
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    fields=['frames','body_observations','supported_right_hip','frames_with_any_position','frames_with_at_least_two_positions','sdk_id_count','adjacent_pairs','large_jumps','nonpositive_z','out_of_image']
    titles={'frames':'フレーム','body_observations':'骨格観測数','supported_right_hip':'右股関節の有効位置','frames_with_any_position':'位置が1点以上あるフレーム','frames_with_at_least_two_positions':'位置が2点以上あるフレーム','sdk_id_count':'SDK ID数','adjacent_pairs':'隣接比較組','large_jumps':'大きな飛び','nonpositive_z':'奥行き0以下','out_of_image':'画像外'}
    table=''.join('<tr><th>'+name+'</th>'+''.join('<td>'+str(vals[k])+'</td>' for k in fields)+'</tr>' for name,vals in result.items())
    warnings=''.join('<li>'+html.escape(name)+': '+html.escape(' | '.join(info.get('warning_lines',[])) or info.get('note','警告行なし。設定適用の保証ではない。'))+'</li>' for name,info in sdk_logs.items())
    text='''<!doctype html><html lang="ja"><meta charset="utf-8"><title>BODY_18とBODY_34の比較</title><style>body{font:15px sans-serif;margin:24px;color:#243345}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:6px}img{max-width:100%}section{border-top:1px solid #aaa}</style><h1>BODY_18とBODY_34の比較</h1><p>同一SVO・同じ時刻の画像を使用。骨格とIDはSDKの推定であり、ID番号を方式間で同一人物として扱えません。</p><p>比較点は両形式の右股関節（BODY_18:8、BODY_34:22）です。同名の点が厳密に同一解剖点である保証はありません。SDK状態OK・有限3D・関節信頼度20以上を集計し、値は真の検出率や精度ではありません。BODY_18の0番は鼻であり骨盤ではありません。BODY_18に骨盤点は含まれず、ここでは骨盤を作っていません。</p><p>大きな飛びは同一SDK IDの隣接フレーム・時間差0.05秒以下で0.75m超かつ6m/秒超を数えた診断値です。欠測やID変更で値が変わります。位置が2点あっても2人の正しい検出とは限りません。</p><p>フィッティングのon/offは要求値です。SDKのログに自動変更や警告がないか確認してください。画像の線は各形式の定義に従って描画しています。下段は3D骨格で同時刻は共通倍率、時刻ごとに表示範囲が変わり、極端な点は枠外になり得ます。廊下校正は暫定です。</p><h2>SDKログの警告</h2><ul>'''+warnings+'</ul><table><tr><th>設定</th>'+''.join('<th>'+titles[k]+'</th>' for k in fields)+'</tr>'+table+'</table><h2>同じ画像の骨格</h2>'+''.join(panels)+'<p><a href="summary.json">設定・集計・イベント</a> / <a href="BODY34_right_hip.csv">BODY34右股関節CSV</a> / <a href="BODY18_off_right_hip.csv">BODY18無効CSV</a> / <a href="BODY18_on_right_hip.csv">BODY18有効CSV</a></p><p><a href="BODY34_all_joints.csv">BODY34全関節CSV</a> / <a href="BODY18_off_all_joints.csv">BODY18無効全関節CSV</a> / <a href="BODY18_on_all_joints.csv">BODY18有効全関節CSV</a>。全関節CSVには異常値も含むSDK出力を記録しています。</p></html>'
    (a.output/'index.html').write_text(text,encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));print('Report:',a.output/'index.html')

if __name__=='__main__':main()
