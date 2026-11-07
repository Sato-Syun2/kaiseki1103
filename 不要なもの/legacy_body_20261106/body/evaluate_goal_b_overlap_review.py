#!/usr/bin/env python3
"""Evaluate a frozen visual-overlap interval, excluding contested skeletons."""
import argparse
import csv
from dataclasses import asdict
import json
from collections import defaultdict
from pathlib import Path

from corridor_tracking.data import sha256
from body.corridor_tracking.evaluation import cross_person_anchors,evaluate_intervals
from body.corridor_tracking.tracker import Config,run_tracker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stored-tracking',action='store_true',help='Use hash-verified tracking saved under the original frozen implementation')
    a=p.parse_args()
    review=Path('results/tracking_v2/goal_b_visual_holdout_20261104_01')
    plan_path=review/'plan.json';ann_path=review/'annotations.json'
    plan=json.loads(plan_path.read_text());ann=json.loads(ann_path.read_text())
    source=Path('results/tracking_v2/group003_20261104_analysis_01/recording_002/observations.json')
    if sha256(source)!=plan['observations_sha256']:
        raise ValueError('Predeclared source changed')
    if not a.stored_tracking and sha256(Path('body/corridor_tracking/tracker.py'))!=plan['tracker_sha256']:
        raise ValueError('Predeclared tracking code changed; use --stored-tracking for the preserved results')
    recorded_path=Path('results/tracking_v2/goal_b_mixed_confidence_20261104_03/summary.json')
    recorded=json.loads(recorded_path.read_text()) if a.stored_tracking else None
    data=json.loads(source.read_text());labels=ann['intervals'][0]['frames']
    frames=[f for f in data['frames'] if f['image_path'] and 1<=f['t']<=2]
    if [f['timestamp_ns'] for f in frames]!=[x['timestamp_ns'] for x in labels]:
        raise ValueError('Image labels do not cover the planned interval')
    for frame in frames:
        if sha256(Path(frame['image_path']))!=ann['image_sha256'][str(frame['frame_index'])]:
            raise ValueError('Reviewed image changed')
    by_frame=defaultdict(list)
    for obs in data['observations']:by_frame[obs['frame_index']].append(obs)
    crossing=[dict(frame_index=f['frame_index'],t=f['t'],
        crossed=cross_person_anchors(by_frame[f['frame_index']],label['people'])) for f,label in zip(frames,labels)]
    a.output.mkdir(parents=True,exist_ok=False)
    rows=[];details=[]
    for filename,expected_hash in plan['configuration_sha256'].items():
        cfg=Path(filename)
        if sha256(cfg)!=expected_hash:raise ValueError('Predeclared configuration changed: '+filename)
        config=Config.from_dict(json.loads(cfg.read_text()))
        if a.stored_tracking:
            saved=review/(cfg.stem+'_tracking.json')
            if sha256(saved)!=recorded['input_sha256'].get(str(saved)):
                raise ValueError('Preserved tracking hash differs: '+str(saved))
            tracking=json.loads(saved.read_text())
            if tracking['config']!=asdict(config):raise ValueError('Preserved tracking config differs')
        else:
            tracking=run_tracker(data,config)
        evaluated=evaluate_intervals({**data,'frames':frames},tracking,ann,'recording_002')
        details.append(dict(config=filename,intervals=evaluated))
        for item in evaluated:
            row=dict(config=filename,mode=item['mode'],person=item['person'],
                evaluated_s=item['evaluated_s'],support_proxy_s=item['support_proxy_s'],
                support_fraction=item['support_fraction'],max_missing_s=item['max_missing_s'],
                excluded_samples=sum(not x['included'] for x in item['samples']))
            # A missing-duration estimate is undefined if no time was eligible.
            if not item['evaluated_s']:row['max_missing_s']=None
            rows.append(row)
    with (a.output/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    output=dict(scope='Frozen visual review; contaminated skeleton frames excluded as unknown, not counted as missing',
        crossing=crossing,results=details,plan_sha256=sha256(plan_path),annotations_sha256=sha256(ann_path),
        tracking_source='hash_verified_stored_results' if a.stored_tracking else 'rerun_predeclared_tracker',
        predeclared_tracker_sha256=plan['tracker_sha256'],
        stored_tracking_hash_record_sha256=sha256(recorded_path) if a.stored_tracking else None,
        evaluation_sha256=sha256(Path('body/corridor_tracking/evaluation.py')),script_sha256=sha256(Path(__file__)))
    (a.output/'evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print('contested images',sum(bool(c['crossed']) for c in crossing),'/',len(crossing))


if __name__=='__main__':main()
