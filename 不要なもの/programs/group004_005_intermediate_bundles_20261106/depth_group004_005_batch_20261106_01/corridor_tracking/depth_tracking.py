"""Experimental 2D/depth association, without SDK skeleton information."""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
import shutil

import numpy as np

from corridor_tracking.assignment import linear_sum_assignment
from corridor_tracking.depth_person_comparison import box_iou, load_run
from depth_person_prototype import digest, safe_asset


def centre_diagonal(box):
    x0,y0,x1,y1 = box
    if not (x0 < x1 and y0 < y1):
        raise ValueError('invalid detection box')
    return np.array([(x0+x1)/2, (y0+y1)/2]), math.hypot(x1-x0, y1-y0)


def association_cost(track, person, timestamp_ns, *, max_speed, margin_m):
    """Return image gate, valid cost; no SDK IDs, skeletons or joint inputs."""
    box = person.get('region_bbox_xyxy')
    if box is None:
        return False, None
    a,da=centre_diagonal(track['bbox']); b,db=centre_diagonal(box)
    distance=float(np.linalg.norm(a-b)); scale=max(da,db,1.0)
    overlap=box_iou(track['bbox'], box)
    image_ok = overlap > 0 or distance <= .6*scale
    if not image_ok:
        return False, None
    current=person.get('surface_camera_image_m')
    previous=track.get('last_surface_camera_m')
    score=(1-overlap)+.25*min(distance/scale,2.)
    if current is not None and previous is not None:
        dt=(timestamp_ns-track['surface_timestamp_ns'])/1e9
        if dt < 0:
            raise ValueError('non-monotonic surface timestamp')
        spatial=float(np.linalg.norm(np.asarray(current)-np.asarray(previous)))
        limit=margin_m+max_speed*dt
        if spatial > limit:
            return True, None
        score += .2*min(spatial/max(limit,1e-9),1.)
    return True, score


def associate_frames(frames, *, max_gap_s=.5, max_speed=3., margin_m=1., ambiguity_margin=.15):
    if not all(math.isfinite(x) and x>0 for x in (max_gap_s,max_speed,margin_m,ambiguity_margin)):
        raise ValueError('tracking thresholds must be positive finite values')
    tracks={}; next_id=1; output=[]; last_ns=None; last_frame=None
    max_cost=1.5
    for frame in frames:
        frame_index=int(frame['frame_index']); now=int(frame['timestamp_ns'])
        if last_ns is not None and (now<=last_ns or frame_index<=last_frame):
            raise ValueError('frames must have strictly increasing timestamps and indices')
        last_ns,last_frame=now,frame_index
        tracks={k:v for k,v in tracks.items() if (now-v['last_seen_ns'])/1e9 <= max_gap_s}
        ids=sorted(tracks); people=frame['people']; costs=np.full((len(ids),len(people)), np.inf)
        contradicted=np.zeros(len(people),dtype=bool)
        for i,ident in enumerate(ids):
            for j,person in enumerate(people):
                image_ok,score=association_cost(tracks[ident],person,now,max_speed=max_speed,margin_m=margin_m)
                if image_ok and score is None:
                    contradicted[j]=True
                if score is not None and score <= max_cost:
                    costs[i,j]=score
        ambiguous=set()
        # Similar candidate costs in either direction cannot safely resolve identity.
        for j in range(len(people)):
            candidates=np.sort(costs[:,j][np.isfinite(costs[:,j])])
            if len(candidates)>1 and candidates[1]-candidates[0] < ambiguity_margin:
                ambiguous.add(j)
        for i in range(len(ids)):
            valid=np.flatnonzero(np.isfinite(costs[i]))
            if len(valid)>1:
                order=valid[np.argsort(costs[i,valid])]
                if costs[i,order[1]]-costs[i,order[0]] < ambiguity_margin:
                    ambiguous.update(int(j) for j in order if costs[i,j]-costs[i,order[0]] < ambiguity_margin)
        available=[j for j in range(len(people)) if j not in ambiguous]
        pairs={}
        if ids and available:
            finite_cost=np.where(np.isfinite(costs[:,available]),costs[:,available],1e6)
            with_dummy=np.concatenate([finite_cost,np.full((len(ids),len(ids)),max_cost)],axis=1)
            r,c=linear_sum_assignment(with_dummy)
            for i,k in zip(r,c):
                if k < len(available) and np.isfinite(costs[i,available[k]]) and costs[i,available[k]] < max_cost:
                    pairs[available[k]]=ids[i]
        observations=[]
        for j,person in enumerate(people):
            valid_candidates=int(np.isfinite(costs[:,j]).sum())
            if j in ambiguous or (j not in pairs and (valid_candidates or contradicted[j])):
                ident=None; reason='ambiguous_or_conflicting_association'
            elif j in pairs:
                ident=pairs[j]; reason='matched_image_and_depth' if person.get('surface_camera_image_m') is not None and tracks[ident].get('last_surface_camera_m') is not None else 'matched_image_only'
            elif person.get('region_bbox_xyxy') is None:
                ident=None; reason='missing_region'
            else:
                ident=next_id; next_id+=1; reason='new_track'
                tracks[ident]={'last_surface_camera_m':None,'surface_timestamp_ns':None}
            if ident is not None:
                tr=tracks[ident];tr['bbox']=person['region_bbox_xyxy'];tr['last_seen_ns']=now
                if person.get('surface_camera_image_m') is not None:
                    tr['last_surface_camera_m']=person['surface_camera_image_m'];tr['surface_timestamp_ns']=now
            observations.append({'detection_label':person['label'],'track_id':ident,'association_reason':reason,
                'region_bbox_xyxy':person['region_bbox_xyxy'],'depth_status':person['status'],
                'surface_camera_image_m':person.get('surface_camera_image_m'),
                'surface_corridor_m':person.get('surface_corridor_m'),
                'position_source':'depth_surface_candidate' if person.get('surface_camera_image_m') is not None else 'no_depth_position',
                'matching_candidates':valid_candidates})
        output.append({'frame_index':frame_index,'timestamp_ns':str(now),'elapsed_s':frame['elapsed_s'],
                       'review_image':frame['review_image'],'observations':observations})
    return output


def make_html(data):
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    return '''<!doctype html><meta charset="utf-8"><title>人物深度の連続確認</title>
<style>body{font:16px sans-serif;margin:24px}canvas{max-width:100%;border:1px solid #ccc}label{display:block;margin:10px 0}pre{white-space:pre-wrap}input[type=range]{width:min(900px,95%)}</style>
<h1>画像と深度から求めた人物位置の追跡候補</h1>
<p>各枠のIDは暫定の対応付け。十字は身体中心ではなく可視表面の候補です。深度が保留された場合は位置なし。骨格情報は使っていません。</p>
<p>枠の色は暫定IDを表します。人物上の黄色などの輪郭・点は各フレームの検出領域と採用した深度点で、検出順により色が変わります。赤い点は除外された深度点です。枠のIDや深度位置の正確さは保証されません。</p>
<label>フレーム <input id="slider" type="range" min="0" value="0" step="1"><span id="clock"></span></label>
<button id="play">再生</button><button id="stop">停止</button>
<p>左：深度点の選択画像と暫定ID。右：カメラ座標のX（右）・Z（前方）で表示。隣接するフレームだけを結び、欠測・未保存区間はつながない。</p>
<canvas id="image"></canvas><canvas id="map" width="520" height="520"></canvas><pre id="info"></pre>
<p><a href="tracking.json">数値・設定</a> / <a href="trajectories.csv">CSV</a></p>
<script id="tracking" type="application/json">DATA</script>
<script>
const D=JSON.parse(document.getElementById('tracking').textContent),frames=D.frames,slider=document.getElementById('slider');
slider.max=frames.length-1;const image=document.getElementById('image'),ctx=image.getContext('2d'),map=document.getElementById('map'),m=map.getContext('2d');let timer=null;
const all=frames.flatMap(f=>f.observations).filter(o=>o.track_id!==null&&o.surface_camera_image_m).map(o=>o.surface_camera_image_m);
const xmin=all.length?Math.min(...all.map(p=>p[0]))-1:-1,xmax=all.length?Math.max(...all.map(p=>p[0]))+1:1,zmin=all.length?Math.min(...all.map(p=>p[2]))-1:0,zmax=all.length?Math.max(...all.map(p=>p[2]))+1:1;
const px=x=>40+(x-xmin)/(xmax-xmin)*440,pz=z=>480-(z-zmin)/(zmax-zmin)*440,color=id=>`hsl(${(id*137)%360},85%,42%)`;
function render(){const i=Number(slider.value),f=frames[i],im=new Image();document.getElementById('clock').textContent=` ${f.frame_index} / ${f.elapsed_s.toFixed(3)}秒`;
im.onload=()=>{if(Number(slider.value)!==i)return;image.width=im.width;image.height=im.height;ctx.drawImage(im,0,0);for(const o of f.observations){if(!o.region_bbox_xyxy)continue;const [x,y,x1,y1]=o.region_bbox_xyxy;ctx.strokeStyle=o.track_id===null?'red':color(o.track_id);ctx.lineWidth=3;ctx.strokeRect(x,y,x1-x,y1-y);ctx.fillStyle=ctx.strokeStyle;ctx.font='bold 24px sans-serif';ctx.fillText(o.track_id===null?'ID ?':`ID ${o.track_id}`,x,Math.max(24,y-5));}};im.src=f.review_image;
m.clearRect(0,0,520,520);m.fillStyle='black';m.font='14px sans-serif';m.fillText('camera X →',215,510);m.fillText('Z ↑',3,20);m.strokeStyle='#bbb';m.strokeRect(40,40,440,440);
for(let j=0;j<=i;j++){for(const o of frames[j].observations){if(o.track_id===null||!o.surface_camera_image_m)continue;const p=o.surface_camera_image_m;m.fillStyle=color(o.track_id);m.beginPath();m.arc(px(p[0]),pz(p[2]),j===i?5:2,0,7);m.fill();if(j>0&&frames[j].frame_index===frames[j-1].frame_index+1){const q=frames[j-1].observations.find(x=>x.track_id===o.track_id&&x.surface_camera_image_m);if(q){m.strokeStyle=color(o.track_id);m.beginPath();m.moveTo(px(q.surface_camera_image_m[0]),pz(q.surface_camera_image_m[2]));m.lineTo(px(p[0]),pz(p[2]));m.stroke();}}}}
document.getElementById('info').textContent=JSON.stringify(f.observations,null,2);}
function step(){const i=Number(slider.value);if(i>=frames.length-1){timer=null;return}const delay=Math.max(1,1000*(frames[i+1].elapsed_s-frames[i].elapsed_s));timer=setTimeout(()=>{slider.value=i+1;render();step()},delay)}
slider.oninput=render;document.getElementById('play').onclick=()=>{if(!timer)step()};document.getElementById('stop').onclick=()=>{clearTimeout(timer);timer=null};render();</script>'''.replace('DATA',payload)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True,help='completed depth_person_prototype output')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-gap-s',type=float,default=.5)
    p.add_argument('--max-speed-m-s',type=float,default=3.)
    p.add_argument('--motion-margin-m',type=float,default=1.)
    p.add_argument('--ambiguity-margin',type=float,default=.15)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('output already exists')
    source=load_run(args.input)
    source_manifest_sha256=digest(args.input/'manifest.json')
    frames=associate_frames(source['frames'],max_gap_s=args.max_gap_s,max_speed=args.max_speed_m_s,
                            margin_m=args.motion_margin_m,ambiguity_margin=args.ambiguity_margin)
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'images').mkdir()
    for frame in frames:
        source_image=safe_asset(args.input,frame['review_image'])
        target=args.output/'images'/Path(frame['review_image']).name
        shutil.copyfile(source_image,target);frame['review_image']='images/'+target.name
    payload={'metadata':{'source_manifest_sha256':source_manifest_sha256,'source_svo_sha256':source['metadata']['source_svo_sha256'],
        'method':source['metadata']['method'],'max_gap_s':args.max_gap_s,'max_speed_m_s':args.max_speed_m_s,
        'motion_margin_m':args.motion_margin_m,'ambiguity_margin':args.ambiguity_margin,
        'scope':'experimental independent frame association; IDs are not verified and skeleton information is not used',
        'limits':['no truth labels; no interpolation; no prediction','missing or ambiguous surface is not a measured position',
                  'trajectory represents visible surface rather than body centre']},'frames':frames}
    (args.output/'tracking.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    fields=['frame_index','timestamp_ns','elapsed_s','detection_label','track_id','association_reason','depth_status','position_source','x_camera_m','y_camera_m','z_camera_m','x_corridor_m','y_corridor_m','z_corridor_m']
    with (args.output/'trajectories.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for frame in frames:
            for obs in frame['observations']:
                xyz=obs['surface_camera_image_m'] or [None]*3;corr=obs['surface_corridor_m'] or [None]*3
                writer.writerow({**{k:frame[k] for k in ('frame_index','timestamp_ns','elapsed_s')},
                    **{k:obs[k] for k in ('detection_label','track_id','association_reason','depth_status','position_source')},
                    **dict(zip(fields[-6:],xyz+corr))})
    (args.output/'index.html').write_text(make_html(payload),encoding='utf-8')
    files=sorted(f for f in args.output.rglob('*') if f.is_file())
    manifest={'status':'complete','tracking_code_sha256':digest(Path(__file__)),'assignment_code_sha256':digest(Path(__file__).with_name('assignment.py')),
              'source_manifest_sha256':source_manifest_sha256,'files_sha256':{str(f.relative_to(args.output)):digest(f) for f in files}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'completed {len(frames)} frames: {args.output}')


if __name__=='__main__':main()
