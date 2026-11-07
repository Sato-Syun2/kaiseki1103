#!/usr/bin/env python3
"""Compare adjacent and wider-baseline pixel velocity on reviewed recordings.

These recordings have been seen during development; results are not a held-out
accuracy measurement. New output directory is required.
"""
import argparse
import csv
import json
from pathlib import Path

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import diagnostics, evaluate_checkpoints, evaluate_intervals
from corridor_tracking.tracker import Config, run_tracker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    root=Path('results/tracking_v2')
    legacy_ann=root/'visual_review_20261104/annotations_final.json'
    dev_ann=root/'goal_b_20261104_development_01/annotations_development.json'
    interval_ann=root/'goal_b_20261104_development_01/prepass_interval_development.json'
    ann_legacy=json.loads(legacy_ann.read_text());ann_dev=json.loads(dev_ann.read_text());ann_interval=json.loads(interval_ann.read_text())
    configs=[Path('configs/tracking_candidate_final_20261104.json'),Path('configs/tracking_goal_b_pairwise_candidate_20261104.json')]
    specs=[('goal_a_20261104_02',i) for i in ['001','003','025','002','044','048']]
    specs += [('group002_20261104_analysis_01',i) for i in ['001','012']]
    specs += [('group003_20261104_analysis_01',i) for i in ['001','017']]
    rows=[];details=[];input_hashes={}
    for run,number in specs:
        source=root/run/f'recording_{number}'/'observations.json'
        data=json.loads(source.read_text());input_hashes[str(source)]=sha256(source)
        for cfg_path in configs:
            cfg=Config.from_dict(json.loads(cfg_path.read_text()));result=run_tracker(data,cfg)
            m=diagnostics(data,result)
            ann=ann_legacy if run.startswith('goal_a_') else (ann_dev if run.startswith('group003_') and number=='001' else None)
            checkpoints=evaluate_checkpoints(data,result,ann,f'recording_{number}') if ann else None
            intervals=[]
            if ann is ann_legacy:
                intervals=evaluate_intervals(data,result,ann,f'recording_{number}')
            elif ann is ann_dev:
                stamps={x['timestamp_ns'] for x in ann_interval['intervals'][0]['frames']}
                reviewed=[f for f in data['frames'] if f['timestamp_ns'] in stamps and f.get('image_path')]
                all_saved=[f for f in data['frames'] if f.get('image_path') and reviewed[0]['t']<=f['t']<=reviewed[-1]['t']]
                if [f['timestamp_ns'] for f in reviewed]!=[f['timestamp_ns'] for f in all_saved]:
                    raise ValueError('Not every saved image in the reviewed interval has a label')
                intervals=evaluate_intervals({**data,'frames':reviewed},result,ann_interval,f'recording_{number}')
            row=dict(run=run,recording=number,method=cfg.pixel_velocity_method,
                baseline_points=m['baseline_points'],candidate_points=m['candidate_points'],
                baseline_tracks=m['baseline_tracks'],candidate_tracks=m['candidate_tracks'],
                ambiguous=m['id_status'].get('ambiguous',0))
            if checkpoints:
                row.update({k:checkpoints['scores']['candidate'][k] for k in ['person_checkpoints','matched_positions',
                    'excluded_person_checkpoints','identity_changes_lower_bound','fragmented_identities_lower_bound','cross_person_id_reuse_lower_bound']})
            rows.append(row);details.append(dict(run=run,recording=number,method=cfg.pixel_velocity_method,
                metrics=m,checkpoints=checkpoints,intervals=intervals))
            print(run,number,cfg.pixel_velocity_method,'points',m['candidate_points'],'tracks',m['candidate_tracks'],flush=True)
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (a.output/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    (a.output/'details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    metadata=dict(scope='Development only; sparse image checkpoints are not complete identity ground truth',
        input_sha256=input_hashes,annotations_sha256={str(p):sha256(p) for p in [legacy_ann,dev_ann,interval_ann]},
        configs_sha256={str(p):sha256(p) for p in configs},tracker_sha256=sha256(Path('corridor_tracking/tracker.py')),
        evaluation_sha256=sha256(Path('corridor_tracking/evaluation.py')),script_sha256=sha256(Path(__file__)))
    (a.output/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
