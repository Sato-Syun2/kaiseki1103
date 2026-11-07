"""Withhold unresolved yaw discontinuities in a new, auditable pose result."""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
import json
import math
import os
from pathlib import Path
from urllib.parse import quote, unquote

from corridor_tracking.upper_body_pose import write_csv, write_gaps
from corridor_tracking.upper_body_replay import make_page
from depth_person_prototype import digest, safe_asset

PARTS = ('shoulder', 'hip', 'torso', 'head')


def withhold_yaw_discontinuities(frames, min_delta_deg=45., min_speed_deg_s=900., max_interval_s=.15):
    if not all(math.isfinite(x) and x > 0 for x in (min_delta_deg,min_speed_deg_s,max_interval_s)) or min_delta_deg > 180:
        raise ValueError('invalid yaw quality thresholds')
    out=deepcopy(frames); selected={}; events=[]
    for i,(a,b) in enumerate(zip(frames,frames[1:])):
        dt=float(b['elapsed_s'])-float(a['elapsed_s'])
        if b['frame_index'] != a['frame_index']+1 or not 0 < dt <= max_interval_s: continue
        previous={}
        for j,o in enumerate(a['observations']):
            ident=o['track_id']
            if ident is not None:
                if ident in previous: raise ValueError('duplicate ID in a frame')
                previous[ident]=(j,o)
        seen=set()
        for k,o in enumerate(b['observations']):
            ident=o['track_id']
            if ident is None: continue
            if ident in seen: raise ValueError('duplicate ID in a frame')
            seen.add(ident)
            if ident not in previous: continue
            j,old=previous[ident]
            for part in PARTS:
                left=old['angles'][part]['yaw_deg']; right=o['angles'][part]['yaw_deg']
                if left is None or right is None: continue
                if not math.isfinite(left) or not math.isfinite(right): raise ValueError('nonfinite yaw')
                delta=abs((right-left+180)%360-180); speed=delta/dt
                if delta >= min_delta_deg and speed >= min_speed_deg_s:
                    event={'track_id':ident,'part':part,'first_frame':a['frame_index'],'last_frame':b['frame_index'],
                           'start_s':a['elapsed_s'],'end_s':b['elapsed_s'],'delta_deg':delta,'interval_s':dt,
                           'angular_speed_deg_s':speed,'first_yaw_deg':left,'last_yaw_deg':right,
                           'reason':'adjacent_discontinuity_unresolved'}
                    events.append(event)
                    selected[(i,j,part)]='withheld_adjacent_discontinuity'
                    selected[(i+1,k,part)]='withheld_adjacent_discontinuity'
    for (i,j,part),reason in list(selected.items()):
        if part in ('shoulder','hip') and out[i]['observations'][j]['angles']['torso']['yaw_deg'] is not None:
            selected.setdefault((i,j,'torso'),'withheld_component_discontinuity')
    for (i,j,part),reason in selected.items():
        angle=out[i]['observations'][j]['angles'][part]
        angle['original_yaw_deg']=angle['yaw_deg']; angle['original_reason']=angle['reason']
        angle['yaw_deg']=None; angle['reason']=reason
    return out,events,dict((part,sum(1 for _,_,p in selected if p==part)) for part in PARTS)


def run(source, output, min_delta_deg=45., min_speed_deg_s=900., max_interval_s=.15):
    source=Path(source).resolve(); output=Path(output).resolve()
    if output.exists(): raise FileExistsError('choose a new output directory')
    if output.is_relative_to(source) or str(output).startswith('\\\\') or output.is_relative_to(Path('/data/experiment_data/kaiseki1103')):
        raise ValueError('output must be separate from input and on local storage')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('status')!='complete': raise ValueError('source pose output incomplete')
    for name in ('pose.json','pose.csv','gaps.csv','pose_replay.html'):
        expected=manifest.get('files_sha256',{}).get(name)
        if not expected or digest(safe_asset(source,name)) != expected: raise ValueError(f'source hash mismatch: {name}')
    data=json.loads((source/'pose.json').read_text(encoding='utf-8-sig'))
    frames,events,counts=withhold_yaw_discontinuities(data['frames'],min_delta_deg,min_speed_deg_s,max_interval_s)
    for f in frames:
        image=(source/unquote(f['image'])).resolve()
        if not image.is_file(): raise ValueError('original replay image is unavailable')
        try: f['image']=quote(os.path.relpath(image,output).replace('\\','/'),safe='/')
        except ValueError as exc: raise ValueError('output and source images must be on the same drive') from exc
    data['frames']=frames
    data['yaw_quality']={'status':'provisional_review_candidates','source_pose_sha256':digest(source/'pose.json'),
       'source_manifest_sha256':digest(source/'manifest.json'),'method':'withhold both endpoints; no interpolation',
       'min_delta_deg':min_delta_deg,'min_speed_deg_s':min_speed_deg_s,'max_interval_s':max_interval_s,
       'unknown_id_motion_checked':False,'event_count':len(events),'withheld_by_part':counts,'code_sha256':digest(Path(__file__))}
    output.mkdir(parents=True,exist_ok=False)
    (output/'pose.json').write_text(json.dumps(data,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    write_csv(output/'pose.csv',data); write_gaps(output/'gaps.csv',data)
    with (output/'yaw_events.csv').open('w',encoding='utf-8-sig',newline='') as f:
        columns=['track_id','part','first_frame','last_frame','start_s','end_s','delta_deg','interval_s','angular_speed_deg_s','first_yaw_deg','last_yaw_deg','reason']
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(events)
    (output/'pose_replay.html').write_text(make_page(data),encoding='utf-8')
    files={name:digest(output/name) for name in ('pose.json','pose.csv','gaps.csv','yaw_events.csv','pose_replay.html')}
    (output/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':files},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data['yaw_quality'],ensure_ascii=False,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--min-delta-deg',type=float,default=45.);p.add_argument('--min-speed-deg-s',type=float,default=900.);p.add_argument('--max-interval-s',type=float,default=.15)
    a=p.parse_args();run(a.source,a.output,a.min_delta_deg,a.min_speed_deg_s,a.max_interval_s)

if __name__=='__main__': main()
