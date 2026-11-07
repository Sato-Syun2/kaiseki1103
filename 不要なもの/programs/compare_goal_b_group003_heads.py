#!/usr/bin/env python3
"""Compare head fusion on previously reviewed group003/001 development images."""
import argparse
from pathlib import Path
import json
from corridor_tracking.data import load_export, sha256
from corridor_tracking.tracker import Config, run_tracker
from corridor_tracking.evaluation import diagnostics, evaluate_checkpoints, evaluate_intervals
from corridor_tracking.replay import write_replay

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.output.exists(): raise FileExistsError(a.output)
root=Path('/data/experiment_data/kaiseki1103/exchange')
body_path=root/'group003_20261104_candidate_01/recording_001/body'
head_path=root/'group003_heads_20261104_01/recording_001/heads'
cal_path=Path('results/tracking_v2/group003_20261104_analysis_01/scoped_calibrations/recording_001.json')
cfg_path=Path('configs/tracking_candidate_final_20261104.json')
review=Path('results/tracking_v2/goal_b_20261104_development_01')
cp_path=review/'annotations_development.json'; interval_path=review/'prepass_interval_development.json'
cal=json.loads(cal_path.read_text()); cfg=Config.from_dict(json.loads(cfg_path.read_text()))
cp=json.loads(cp_path.read_text()); ann=json.loads(interval_path.read_text())
body=load_export(body_path,cal,with_appearance=cfg.appearance_weight>0)
merged=load_export(body_path,cal,with_appearance=cfg.appearance_weight>0,heads_folder=head_path)
stamps={x['timestamp_ns'] for x in ann['intervals'][0]['frames']}
frames=[f for f in body['frames'] if f['timestamp_ns'] in stamps and f.get('image_path')]
if len(frames)!=len(stamps) or not frames: raise ValueError('reviewed images missing')
full=[f for f in body['frames'] if f.get('image_path') and frames[0]['t']<=f['t']<=frames[-1]['t']]
if [f['timestamp_ns'] for f in frames]!=[f['timestamp_ns'] for f in full]: raise ValueError('incomplete saved-image annotations')
reviewed={**body,'frames':frames}
a.output.mkdir(parents=True)
results={}
for name,data in [('body_only',body),('body_plus_heads',merged)]:
 track=run_tracker(data,cfg)
 # Use the same body observations for matching and exclusion; head boxes are not ground truth.
 results[name]={'diagnostics':diagnostics(data,track),'checkpoints':evaluate_checkpoints(body,track,cp,'recording_001'),
                'intervals':evaluate_intervals(reviewed,track,ann,'recording_001')}
 target=a.output/name; target.mkdir()
 (target/'tracking.json').write_text(json.dumps(track,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 write_replay(target,data,track,cal,'recording_001')
summary={'scope':'Development recording; reviewed saved images only, not continuous identity truth; head detections are not independently labelled.',
 'adoption':'not_adopted_pending_independent_validation', 'results':results,
 'input_hashes':merged['input_hashes'],'image_hashes':merged['image_hashes'],
 'file_hashes':{str(x):sha256(x) for x in [cal_path,cfg_path,cp_path,interval_path,Path(__file__),Path('corridor_tracking/data.py'),Path('corridor_tracking/tracker.py'),Path('corridor_tracking/evaluation.py')]}}
(a.output/'evaluation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(a.output/'evaluation.json')
for k,v in results.items():
 print(k,'supported',v['diagnostics']['candidate_points'],'interval',json.dumps([{kk:vv for kk,vv in row.items() if kk!='samples'} for row in v['intervals'] if row['mode']=='candidate'],ensure_ascii=False))
