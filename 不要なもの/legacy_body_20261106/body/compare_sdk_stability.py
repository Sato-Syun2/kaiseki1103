#!/usr/bin/env python3
"""Compare BODY_34 exports at common sampled frames, with a legacy group-1 reference."""
import argparse
import csv
import hashlib
import html
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

BONES = [(0,1),(1,2),(2,3),(3,26),(2,5),(5,6),(6,7),(2,12),(12,13),(13,14),
         (0,18),(18,19),(19,20),(0,22),(22,23),(23,24)]
ANGLES = {'left_elbow':(5,6,7), 'right_elbow':(12,13,14), 'left_knee':(18,19,20), 'right_knee':(22,23,24)}


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):
            h.update(part)
    return h.hexdigest()


def point(v, n):
    return isinstance(v, list) and len(v)==n and all(isinstance(x,(int,float)) and math.isfinite(x) for x in v)


def angle(joints, confidence, indices):
    if any(i>=len(joints) or i>=len(confidence) or not isinstance(confidence[i],(int,float)) or confidence[i]<20 or not point(joints[i],3) for i in indices):
        return None
    a,b,c=(np.asarray(joints[i],dtype=float) for i in indices)
    x,y=a-b,c-b
    denom=float(np.linalg.norm(x)*np.linalg.norm(y))
    return math.degrees(math.acos(float(np.clip(x.dot(y)/denom,-1,1)))) if denom>1e-8 else None


def load(folder, validate=True):
    folder=folder.resolve()
    camera=json.loads((folder/'camera.json').read_text(encoding='utf-8-sig'))
    manifest_path=folder/'manifest.json'
    if manifest_path.exists() and validate:
        from zed_sdk_package.tracking_v2.validate_export import validate_export
        validate_export(folder)
        manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if manifest.get('completion_scope')!='full_svo_eof':
            raise ValueError(f'{folder}: a complete full-SVO export is required')
    frames=rows(folder/'frames.csv')
    if not frames: raise ValueError(f'{folder}: empty frames')
    byframe={int(f['frame_index']):f for f in frames}
    if len(byframe)!=len(frames): raise ValueError(f'{folder}: repeated frame index')
    bodies=defaultdict(list)
    for r in rows(folder/'bodies.csv'):
        frame=int(r['frame_index'])
        if frame not in byframe or r['image_timestamp_ns']!=byframe[frame]['image_timestamp_ns']:
            raise ValueError(f'{folder}: body frame/timestamp mismatch')
        try:
            r['joints']=json.loads(r['keypoints_3d_camera_json'])
            r['pixels']=json.loads(r['keypoints_2d_json'])
            r['conf']=json.loads(r['keypoint_confidence_json'])
            r['id']=int(r['body_id'])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'{folder}: malformed body') from exc
        bodies[frame].append(r)
    log=folder.parent/'export.log'
    log_text=log.read_text(encoding='utf-8',errors='replace').lower() if log.is_file() else ''
    fitting_auto_enabled='automatically enable body fitting' in log_text
    return dict(folder=folder,camera=camera,frames=frames,byframe=byframe,bodies=bodies,
                fitting_auto_enabled=fitting_auto_enabled,
                hashes={k:digest(folder/k) for k in ('camera.json','frames.csv','bodies.csv')})


def compare_identity(base, other):
    a,b=base['camera'],other['camera']
    if not a.get('source_svo_sha256') or a['source_svo_sha256']!=b.get('source_svo_sha256'):
        raise ValueError('Candidates must have the same verified SVO SHA-256 as the baseline')
    for k in ('setup_id','serial_number','width','height','fps','coordinate_system','coordinate_units','depth_mode','body_format','intrinsics_left'):
        if a.get(k)!=b.get(k): raise ValueError(f'Camera setting differs: {k}')
    for k in ('body_tracking_model_gen','prediction_timeout_s','detection_confidence_threshold','minimum_keypoints_threshold','skeleton_smoothing','body_fitting'):
        if k not in b: raise ValueError(f'Candidate missing setting metadata: {k}')
    ta=[(f['frame_index'],f['image_timestamp_ns']) for f in base['frames']]
    tb=[(f['frame_index'],f['image_timestamp_ns']) for f in other['frames']]
    if ta!=tb: raise ValueError('Full frame indices or timestamps differ')


def sample_frames(data):
    # Group 1 saved only samples; full exports use the baseline image clock (~0.1 s).
    return [int(f['frame_index']) for f in data['frames'] if f.get('image_file')]


def measure(data, frames, max_dt=.2):
    tracks=defaultdict(list); valid_per_frame={}; suspicious=[]
    valid_angles=extreme_angles=0
    for order,frame in enumerate(frames):
        f=data['byframe'][frame]; t=float(f['elapsed_s']); valid=0
        for r in data['bodies'].get(frame,[]):
            j,c=r['joints'],r['conf']
            if r['tracking_state'].upper()!='OK' or not j or not point(j[0],3) or not c or not isinstance(c[0],(int,float)) or c[0]<20: continue
            valid+=1
            ang={k:angle(j,c,ix) for k,ix in ANGLES.items()}
            for k,v in ang.items():
                if v is not None:
                    valid_angles+=1
                    if v<20:
                        extreme_angles+=1
                        suspicious.append(dict(frame=frame,t=t,kind='angle_below_20_deg',body_id=r['id'],joint=k,value=round(v,2)))
            tracks[r['id']].append((order,frame,t,j[0],ang))
        valid_per_frame[frame]=valid
    pairs=jumps=angle_pairs=angle_jumps=spikes=0
    for ident,track in tracks.items():
        for a,b in zip(track,track[1:]):
            dt=b[2]-a[2]
            if b[0]-a[0]!=1 or not 0<dt<=max_dt: continue
            pairs+=1; distance=math.dist(a[3],b[3])
            if distance>.75 and distance/dt>6:
                jumps+=1
                suspicious.append(dict(frame=b[1],t=b[2],kind='pelvis_jump',body_id=ident,value=round(distance,3),seconds=round(dt,4)))
            for k in ANGLES:
                if a[4][k] is not None and b[4][k] is not None:
                    angle_pairs+=1; change=abs(b[4][k]-a[4][k])
                    if change>90 and change/dt>450:
                        angle_jumps+=1
                        suspicious.append(dict(frame=b[1],t=b[2],kind='angle_change_over_90_deg',body_id=ident,joint=k,value=round(change,2),seconds=round(dt,4)))
        for a,b,c in zip(track,track[1:],track[2:]):
            d1=b[2]-a[2];d2=c[2]-b[2]
            if b[0]-a[0]!=1 or c[0]-b[0]!=1 or not(0<d1<=max_dt and 0<d2<=max_dt):continue
            x=math.dist(a[3],b[3]);y=math.dist(b[3],c[3])
            spikes+=int(x>.75 and y>.75 and x/d1>6 and y/d2>6 and math.dist(a[3],c[3])<.5+4*(d1+d2))
    return dict(frames=len(frames),frames_with_position=sum(v>0 for v in valid_per_frame.values()),
                position_observations=sum(valid_per_frame.values()),sdk_ids=len(tracks),adjacent_pairs=pairs,
                pelvis_jumps=jumps,pelvis_jump_fraction=jumps/pairs if pairs else None,one_sample_spikes=spikes,
                angle_observations=valid_angles,angles_below_20=extreme_angles,
                adjacent_joint_angle_pairs=angle_pairs,angle_changes_over_90=angle_jumps,
                per_frame=valid_per_frame,events=suspicious)


def render(data, frame, label, width=640, crop=None):
    f=data['byframe'][frame]; image=(data['folder']/f['image_file']).resolve()
    im=cv2.imread(str(image))
    if im is None: raise ValueError(f'Cannot load image {image}')
    for r in data['bodies'].get(frame,[]):
        pixels,conf=r['pixels'],r['conf']
        color=((int(r['id'])*93+50)%220+30,(int(r['id'])*141+80)%220+30,(int(r['id'])*173+100)%220+30)
        for a,b in BONES:
            if max(a,b)>=len(pixels) or max(a,b)>=len(conf):continue
            if not point(pixels[a],2) or not point(pixels[b],2):continue
            if not all(isinstance(conf[k],(int,float)) and conf[k]>=20 for k in (a,b)):continue
            cv2.line(im,tuple(map(round,pixels[a])),tuple(map(round,pixels[b])),color,3,cv2.LINE_AA)
        if pixels and point(pixels[0],2):
            cv2.putText(im,str(r['id']),tuple(map(round,pixels[0])),cv2.FONT_HERSHEY_SIMPLEX,.8,color,2)
    if crop:
        x0,y0,x1,y1=crop
        im=im[y0:y1,x0:x1]
    height=360
    scale=min(width/im.shape[1],height/im.shape[0]); new=(max(1,round(im.shape[1]*scale)),max(1,round(im.shape[0]*scale)))
    small=cv2.resize(im,new); canvas=np.full((height,width,3),35,dtype=np.uint8)
    x=(width-new[0])//2;y=(height-new[1])//2;canvas[y:y+new[1],x:x+new[0]]=small;im=canvas
    cv2.rectangle(im,(0,0),(width,32),(25,25,25),-1)
    cv2.putText(im,label[:65],(6,23),cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),1,cv2.LINE_AA)
    return im


def image_crop(datasets,frame,width,height):
    points=[]
    for d in datasets.values():
        for r in d['bodies'].get(frame,[]):
            points.extend(p for p in r['pixels'] if point(p,2) and 0<=p[0]<width and 0<=p[1]<height)
    if not points:return (0,0,width,height)
    xy=np.asarray(points);lo=np.percentile(xy,1,axis=0);hi=np.percentile(xy,99,axis=0)
    center=(lo+hi)/2;half=np.maximum((hi-lo)*.75,75)
    return (max(0,int(center[0]-half[0])),max(0,int(center[1]-half[1])),
            min(width,int(math.ceil(center[0]+half[0]))),min(height,int(math.ceil(center[1]+half[1]))))


def render_3d(data, frame, label, bounds, width=640, height=360):
    """Draw SDK camera-frame joints with identical frame-specific axes across settings."""
    im=np.full((height,width,3),245,dtype=np.uint8)
    xmin,xmax,ymin,ymax=bounds
    scale=min((width-40)/(xmax-xmin),(height-65)/(ymax-ymin))
    def project(p):
        x=p[0]+.35*p[2];y=p[1]-.18*p[2]
        return (round(width/2+(x-(xmin+xmax)/2)*scale),round((height+25)/2+(y-(ymin+ymax)/2)*scale))
    for r in data['bodies'].get(frame,[]):
        joints,conf=r['joints'],r['conf']
        color=((int(r['id'])*93+50)%220+30,(int(r['id'])*141+80)%220+30,(int(r['id'])*173+100)%220+30)
        for a,b in BONES:
            if max(a,b)>=len(joints) or max(a,b)>=len(conf):continue
            if not point(joints[a],3) or not point(joints[b],3):continue
            if not all(isinstance(conf[k],(int,float)) and conf[k]>=20 for k in (a,b)):continue
            if max(abs(x) for k in (a,b) for x in joints[k])>100:continue
            pa,pb=project(joints[a]),project(joints[b])
            ok,pa,pb=cv2.clipLine((0,28,width,height-28),pa,pb)
            if ok:cv2.line(im,pa,pb,color,3,cv2.LINE_AA)
    cv2.rectangle(im,(0,0),(width,29),(45,45,45),-1)
    cv2.putText(im,('3D camera coordinates | '+label)[:65],(6,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA)
    return im


def scene_bounds(datasets, frame):
    points=[]
    for d in datasets.values():
        for r in d['bodies'].get(frame,[]):
            for p in r['joints']:
                if point(p,3) and max(abs(x) for x in p)<100:
                    points.append((p[0]+.35*p[2],p[1]-.18*p[2]))
    if not points:return (-2,2,-2,2)
    xy=np.asarray(points);lo=np.percentile(xy,1,axis=0);hi=np.percentile(xy,99,axis=0)
    center=(lo+hi)/2;half=np.maximum((hi-lo)/2+.3,.5)
    return (center[0]-half[0],center[0]+half[0],center[1]-half[1],center[1]+half[1])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',action='append',default=[],metavar='NAME=PATH')
    p.add_argument('--reference',type=Path,action='append',default=[])
    p.add_argument('--review-frame',type=int,action='append',default=[],help='add a saved-image frame for side-by-side review')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): p.error('Output must be a new directory')
    base=load(a.baseline); datasets={'baseline':base}
    for item in a.candidate:
        if '=' not in item: p.error('--candidate requires NAME=PATH')
        name,path=item.split('=',1)
        if not name or name in datasets or not all(c.isalnum() or c in '_-' for c in name):p.error('Invalid or duplicate candidate name')
        data=load(Path(path)); compare_identity(base,data); datasets[name]=data
    refs=[load(path) for path in a.reference]
    frames=sample_frames(base)
    if not frames: raise ValueError('No saved baseline images for common sampling')
    if not set(a.review_frame).issubset(frames): raise ValueError('Every --review-frame must be a saved baseline image frame')
    metrics={name:measure(d,frames) for name,d in datasets.items()}
    full_metrics={name:measure(d,[int(f['frame_index']) for f in d['frames']],max_dt=.05) for name,d in datasets.items()}
    refresults=[measure(d,sample_frames(d)) for d in refs]
    a.output.mkdir(parents=True,exist_ok=False)
    fields=['frames','frames_with_position','position_observations','sdk_ids','adjacent_pairs','pelvis_jumps','pelvis_jump_fraction','one_sample_spikes','angle_observations','angles_below_20','adjacent_joint_angle_pairs','angle_changes_over_90']
    numbers={name:{k:m[k] for k in fields} for name,m in metrics.items()}
    if refresults:
        combined={k:sum(m[k] for m in refresults) for k in fields if k!='pelvis_jump_fraction'}
        combined['pelvis_jump_fraction']=combined['pelvis_jumps']/combined['adjacent_pairs'] if combined['adjacent_pairs'] else None
        numbers['group1_reference_total']=combined
    info={'sampling':'baseline saved image timestamps, ~0.1 s; same frame indices across candidate passes',
          'thresholds':'OK, finite pelvis and pelvis confidence >=20; consecutive sampled frames; jump >0.75m AND >6m/s; elbow/knee angles <20 degrees or changes >90 degrees AND >450 degrees/s; angle thresholds are diagnostics only',
          'limitations':['No ground truth, no per-person detection rate or pose accuracy; SDK predictions and body fitting may be present.',
                         'Reference has different recordings, camera view and saved frames; candidate comparison is paired, reference is contextual.',
                         'Angle metrics are 3D camera coordinate estimates; unusual angle or change is not proof of an error; genuine motion can be flagged.',
                         'Fewer detected people can reduce event counts and rates; frames with position do not count visible people.',
                         'SDK IDs may switch or be reused; do not compare ID numbers across runs.'],
          'metrics':numbers,'inputs':{name:{'path':str(d['folder']),'sha256':d['hashes'],'camera':d['camera'],'sdk_log_automatically_enables_fitting':d['fitting_auto_enabled']} for name,d in datasets.items()},
          'full_rate_metrics':{name:{k:m[k] for k in fields} for name,m in full_metrics.items()},
          'references':[{'path':str(d['folder']),'sha256':d['hashes']} for d in refs],
          'events':{name:m['events'] for name,m in metrics.items()}}
    (a.output/'summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (a.output/'metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['name']+fields);w.writeheader()
        for name,m in numbers.items():w.writerow(dict(name=name,**m))
    # Review all available settings at the exact same saved-image frame. Rank by diagnostic events.
    counts=defaultdict(int)
    for m in metrics.values():
        for e in m['events']:counts[e['frame']]+=1
    regular=[frames[round(i*(len(frames)-1)/7)] for i in range(8)] if len(frames)>1 else frames
    ranked=list(dict.fromkeys(a.review_frame+regular+sorted(counts,key=lambda x:(-counts[x],x))))[:30]
    (a.output/'images').mkdir()
    cards=[]
    for frame in ranked:
        panels=[]
        bounds=scene_bounds(datasets,frame)
        crop=image_crop(datasets,frame,int(base['camera']['width']),int(base['camera']['height']))
        # All panels intentionally use the baseline image: output images may differ in compression.
        for name,d in datasets.items():
            view=dict(d);view['folder']=base['folder'];view['byframe']=base['byframe']
            image_panel=render(view,frame,f'{name} | frame {frame} | t={float(base["byframe"][frame]["elapsed_s"]):.3f}s')
            zoom_panel=render(view,frame,f'{name} | enlarged',crop=crop)
            panels.append(np.concatenate([image_panel,zoom_panel,render_3d(d,frame,name,bounds,width=image_panel.shape[1],height=image_panel.shape[0])],axis=0))
        canvas=np.concatenate(panels,axis=1)
        dest=a.output/'images'/f'frame_{frame:06d}.jpg'
        if not cv2.imwrite(str(dest),canvas):raise OSError(f'Cannot save {dest}')
        es=[f'{name}: {e["kind"]} ID {e["body_id"]} {e.get("joint", "")} {e["value"]}' for name,m in metrics.items() for e in m['events'] if e['frame']==frame]
        cards.append(f'<section><h3>frame {frame} / {float(base["byframe"][frame]["elapsed_s"]):.3f}秒</h3><p>{html.escape("; ".join(es))}</p><img loading="lazy" src="images/{dest.name}"></section>')
    def fmt(v):return f'{v:.2%}' if isinstance(v,float) else str(v)
    table=''.join('<tr><th>'+html.escape(name)+'</th>'+''.join('<td>'+fmt(m[k])+'</td>' for k in fields)+'</tr>' for name,m in numbers.items())
    full_table=''.join('<tr><th>'+html.escape(name)+'</th>'+''.join('<td>'+fmt(m[k])+'</td>' for k in fields)+'</tr>' for name,m in full_metrics.items())
    settings=''.join('<li>'+html.escape(name)+': '+html.escape(json.dumps({k:d['camera'].get(k) for k in ('body_tracking_model','body_fitting','prediction_timeout_s','detection_confidence_threshold','minimum_keypoints_threshold','skeleton_smoothing')},ensure_ascii=False))+(' <strong>SDKログ: BODY_34でフィッティングは自動有効。body_fitting=falseは要求値で、無効化されていません。</strong>' if d['fitting_auto_enabled'] else '')+'</li>' for name,d in datasets.items())
    page='''<!doctype html><html lang="ja"><meta charset="utf-8"><title>SDK骨格安定性比較</title><style>body{font:15px sans-serif;margin:24px;color:#203040}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px}img{max-width:100%;height:auto}section{margin:24px 0}small{color:#555}</style><h1>SDK骨格安定性比較</h1><p>同一SVOの同じ画像時刻を比較。グループ1は異なる録画での参考値です。自動指標は誤検出率や精度ではありません。画面で骨格と人物を確認してください。</p><p>骨盤の飛び: 0.75m超かつ6m/s超。角度は肘・膝の3D推定角、20度未満と、隣接時刻で90度超かつ450度/秒超の変化を確認候補とします。SDK予測・欠測・ID変化でも数値は変わり、異常の確定ではありません。これらの条件に当たらない骨格の混在や異常もあります。</p><p>数字が小さくても人物を見失っている場合があります。画像は指定時刻、等間隔の8時刻、自動候補の順で最大30枚を選びます。人物がいない時間帯や異常のすべてを網羅しません。ID番号は方式間で同じ人物を意味しません。</p><h2>設定</h2><ul>'''+settings+'''</ul><h2>約0.1秒間隔の比較</h2><p>グループ1参考値と保存画像の時刻を合わせた診断です。</p><table><tr><th>条件</th>'''+''.join('<th>'+html.escape(k)+'</th>' for k in fields)+'</tr>'+table+'''</table><h2>全フレームでの参考診断</h2><p>こちらはグループ1の保存データと時間間隔が異なります。短い飛びの確認に使います。</p><table><tr><th>条件</th>'''+''.join('<th>'+html.escape(k)+'</th>' for k in fields)+'</tr>'+full_table+'</table><h2>同一画像の骨格比較（約0.1秒間隔）</h2><p>上段はSDKの2D関節を重ねた全画像、中段は人物付近の拡大、下段はカメラ座標の3D関節を斜め方向に投影した図です。同じ時刻の条件間では表示範囲と倍率を揃えています。表示範囲は関節の1〜99パーセンタイルから作り、極端な関節は枠外に出る場合があります。時刻ごとに倍率は変わります。</p>'''+(''.join(cards) if cards else '<p>確認画像はありません。</p>')+'<p><a href="summary.json">全指標・条件・イベント</a> / <a href="metrics.csv">CSV</a></p></html>'
    (a.output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(numbers,ensure_ascii=False,indent=2));print('report:',a.output/'index.html')


if __name__=='__main__':main()
