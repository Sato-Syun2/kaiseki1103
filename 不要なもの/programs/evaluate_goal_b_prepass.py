#!/usr/bin/env python3
"""Evaluate reviewed saved-image checkpoints and interval, not interpolated truth."""
import argparse
import csv
import json
from pathlib import Path

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import diagnostics, evaluate_checkpoints, evaluate_intervals
from corridor_tracking.tracker import Config, run_tracker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source=Path('results/tracking_v2/group003_20261104_analysis_01/recording_001/observations.json')
    review=Path('results/tracking_v2/goal_b_20261104_development_01')
    checkpoints=review/'annotations_development.json'; interval=review/'prepass_interval_development.json'
    confs=[Path('configs/tracking_candidate_final_20261104.json'),Path('configs/tracking_goal_b_hold_candidate_20261104.json')]
    data=json.loads(source.read_text()); cp=json.loads(checkpoints.read_text()); ann=json.loads(interval.read_text())
    bounds=ann['intervals'][0]['frames']; selected={x['timestamp_ns'] for x in bounds}
    frames=[f for f in data['frames'] if f['timestamp_ns'] in selected and f.get('image_path')]
    if len(frames)!=len(bounds) or not frames: raise ValueError('Reviewed images missing or duplicated')
    full_saved=[f for f in data['frames'] if f.get('image_path') and frames[0]['t']<=f['t']<=frames[-1]['t']]
    if [f['timestamp_ns'] for f in frames] != [f['timestamp_ns'] for f in full_saved]:
        raise ValueError('Every saved image in the interval must be reviewed')
    reviewed_data={**data,'frames':frames}
    a.output.mkdir(parents=True,exist_ok=False)
    results=[]
    for path in confs:
        config=json.loads(path.read_text()); tracking=run_tracker(data,Config.from_dict(config))
        scores=evaluate_checkpoints(data,tracking,cp,'recording_001')
        intervals=evaluate_intervals(reviewed_data,tracking,ann,'recording_001')
        metrics=diagnostics(data,tracking)
        results.append(dict(config=str(path),checkpoints=scores,intervals=intervals,metrics=metrics))
    (a.output/'evaluation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for result in results:
        for item in result['intervals']:
            rows.append(dict(config=result['config'],**{k:v for k,v in item.items() if k!='samples'}))
    with (a.output/'intervals.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
        w.writerows([{k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows])
    metadata=dict(scope='development, saved-image cadence only; inter-image frames and event time are not labelled',
        inputs_sha256={str(x):sha256(x) for x in [source,checkpoints,interval,*confs]},
        tracker_sha256=sha256(Path('corridor_tracking/tracker.py')),
        evaluation_sha256=sha256(Path('corridor_tracking/evaluation.py')),script_sha256=sha256(Path(__file__)))
    (a.output/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(a.output/'intervals.csv')


if __name__=='__main__':main()
