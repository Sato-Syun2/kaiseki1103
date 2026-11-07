#!/usr/bin/env python3
"""Compare SDK model motion diagnostics on existing group 1 exports; not pose truth."""
import csv,json,math
from pathlib import Path
from collections import defaultdict
root=Path('/data/experiment_data/kaiseki1103/exchange')
out=Path('results/tracking_v2/model_motion_diagnostic_20261104_01');out.mkdir(parents=True,exist_ok=False)
models=['ACCURATE_GEN2','MEDIUM_GEN2','ACCURATE_GEN1','MEDIUM_GEN1','FAST_GEN1']
def rows(path):
 with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def pos(r):
 try:
  xyz=json.loads(r['keypoints_3d_camera_json'])[0];conf=json.loads(r['keypoint_confidence_json'])[0]
  if r['tracking_state']!='OK' or conf is None or conf<20 or not isinstance(xyz,list) or len(xyz)!=3 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in xyz):return None
  return xyz
 except (TypeError,ValueError,IndexError):return None
results=[]
for index in range(1,49):
 rec=f'recording_{index:03d}';base=root/rec/'model_comparison_20261103'; cameras=[json.loads((base/m/'camera.json').read_text()) for m in models]
 for k in ['source_svo','depth_mode','body_format','coordinate_system','coordinate_units','width','height']:
  if len({json.dumps(c.get(k),sort_keys=True) for c in cameras})!=1:raise ValueError((rec,k))
 all_frames=[rows(base/m/'frames.csv') for m in models];timeline=[(f['frame_index'],f['image_timestamp_ns']) for f in all_frames[0]]
 if any([(f['frame_index'],f['image_timestamp_ns']) for f in frames]!=timeline for frames in all_frames[1:]):raise ValueError('timeline mismatch '+rec)
 for model,frames in zip(models,all_frames):
  tracks=defaultdict(list)
  for r in rows(base/model/'bodies.csv'):
   p=pos(r)
   if p is not None:tracks[r['body_id']].append((int(r['sample_index']),float(r['elapsed_s']),p))
  pairs=jump=spike=0; largest=0.
  for track in tracks.values():
   track.sort()
   def diff(a,b):return math.dist(a[2],b[2])
   for a,b in zip(track,track[1:]):
    dt=b[1]-a[1]
    if b[0]-a[0]!=1 or not 0<dt<=.2:continue
    pairs+=1;delta=diff(a,b);largest=max(largest,delta);jump+=int(delta>.75 and delta/dt>6)
   for a,b,c in zip(track,track[1:],track[2:]):
    dt1=b[1]-a[1];dt2=c[1]-b[1]
    if b[0]-a[0]!=1 or c[0]-b[0]!=1 or not (0<dt1<=.2 and 0<dt2<=.2):continue
    d1=diff(a,b);d2=diff(b,c);spike+=int(d1>.75 and d2>.75 and d1/dt1>6 and d2/dt2>6 and diff(a,c)<.5+4*(dt1+dt2))
  results.append(dict(recording=rec,model=model,positions=sum(map(len,tracks.values())),adjacent_pairs=pairs,large_jumps=jump,one_sample_spikes=spike,maximum_jump_m=round(largest,4)))
with (out/'per_recording.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
summary={}
for model in models:
 data=[r for r in results if r['model']==model];summary[model]={k:sum(r[k] for r in data) for k in ['positions','adjacent_pairs','large_jumps','one_sample_spikes']}
 summary[model]['jump_fraction']=summary[model]['large_jumps']/summary[model]['adjacent_pairs'] if summary[model]['adjacent_pairs'] else None
report={'scope':'48 group1 recordings, 0.1 s stored-image samples; same saved frame indices and timestamps; no verified original-SVO hash in these legacy exports',
 'limitations':['Thresholds are diagnostics, not independent pose truth or identity-switch accuracy.','Compared models can detect different people and missing observations; fewer jumps may mean less detection.','Timing is sampled at ~0.1 s; full-rate short spikes can be missed.','Group 2/3 require separate tests.'], 'summary':summary}
(out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
