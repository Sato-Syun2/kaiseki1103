#!/usr/bin/env python3
"""Summarize SDK scores for image-reviewed overlap and separated intervals.

These samples were already reviewed; crossing visible regions is a conservative
warning, not person-identity ground truth. Do not infer an operating threshold.
"""
import argparse
from collections import defaultdict
import csv
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from corridor_tracking.data import finite,sha256
from corridor_tracking.evaluation import cross_person_anchors
from corridor_tracking.tracker import Config


SPECS=[
    ('overlap','results/tracking_v2/group003_20261104_analysis_01/recording_002/observations.json',
     'results/tracking_v2/goal_b_visual_holdout_20261104_01/annotations.json'),
    ('separated','results/tracking_v2/group003_20261104_analysis_01/recording_001/observations.json',
     'results/tracking_v2/goal_b_20261104_development_01/prepass_interval_development.json'),
]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--include-population',action='store_true',help='Also count SDK confidence below 70 in all 109 recordings')
    p.add_argument('--include-tracking-acceptance',action='store_true',help='Compare stored tracking decisions for the reviewed crossing observations')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    rows=[];hashes={}
    for name,source_name,ann_name in SPECS:
        source=Path(source_name);ann_path=Path(ann_name);data=json.loads(source.read_text());ann=json.loads(ann_path.read_text())
        hashes.update({str(source):sha256(source),str(ann_path):sha256(ann_path)})
        by_stamp={f['timestamp_ns']:f for f in data['frames']};by_frame=defaultdict(list)
        for obs in data['observations']:by_frame[obs['frame_index']].append(obs)
        for label in ann['intervals'][0]['frames']:
            f=by_stamp[label['timestamp_ns']]
            if not f.get('image_path'):raise ValueError('Review frame has no saved image')
            if ann.get('image_sha256') and sha256(Path(f['image_path']))!=ann['image_sha256'][str(f['frame_index'])]:
                raise ValueError('Reviewed image changed')
            obs=[o for o in by_frame[f['frame_index']] if o['kind']=='body' and o['legacy_valid']]
            crossed={x['obs_id'] for x in cross_person_anchors(obs,label['people'])}
            for o in obs:
                root,head=o['joints'][0],o['joints'][26]
                distance=float(np.linalg.norm(np.asarray(root)-head)) if finite(root) and finite(head) else None
                rows.append(dict(interval=name,frame_index=f['frame_index'],t=f['t'],obs_id=o['obs_id'],
                    sdk_id=o['sdk_id'],crosses_visible_regions=o['obs_id'] in crossed,confidence=o['confidence'],
                    root_confidence=o['joint_confidence'][0],head_confidence=o['joint_confidence'][26],
                    root_head_distance_m=distance))
    a.output.mkdir(parents=True,exist_ok=False)
    with (a.output/'observations.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summaries=[]
    for interval,cross in [('overlap',True),('overlap',False),('separated',False)]:
        subset=[r for r in rows if r['interval']==interval and r['crosses_visible_regions']==cross]
        values={}
        for key in ['confidence','root_confidence','head_confidence','root_head_distance_m']:
            v=[r[key] for r in subset if r[key] is not None and np.isfinite(r[key])]
            values[key]=dict(min=float(np.min(v)),median=float(np.median(v)),max=float(np.max(v))) if v else None
        summaries.append(dict(interval=interval,crosses_visible_regions=cross,count=len(subset),values=values))
    population=[]
    if a.include_population:
        for group in ['group002','group003']:
            root=Path('results/tracking_v2')/f'{group}_20261104_analysis_01'
            summary_path=root/'summary.json';summary=json.loads(summary_path.read_text());hashes[str(summary_path)]=sha256(summary_path)
            total=below=unknown=0
            for record in summary['records']:
                path=root/record['recording']/'observations.json';hashes[str(path)]=sha256(path)
                observations=json.loads(path.read_text())['observations']
                for o in observations:
                    if not o['legacy_valid']:continue
                    total+=1
                    if o['confidence'] is None:unknown+=1
                    elif o['confidence']<70:below+=1
            population.append(dict(group=group,recordings=len(summary['records']),legacy_points=total,
                confidence_below_70=below,confidence_missing=unknown))
    acceptance=[]
    if a.include_tracking_acceptance:
        review=Path('results/tracking_v2/goal_b_visual_holdout_20261104_01')
        plan_path=review/'plan.json';plan=json.loads(plan_path.read_text());hashes[str(plan_path)]=sha256(plan_path)
        record_path=Path('results/tracking_v2/goal_b_mixed_confidence_20261104_03/summary.json')
        recorded=json.loads(record_path.read_text());hashes[str(record_path)]=sha256(record_path)
        crossed_ids={r['obs_id'] for r in rows if r['interval']=='overlap' and r['crosses_visible_regions']}
        for name,expected_hash in plan['configuration_sha256'].items():
            config_path=Path(name);track_path=review/(config_path.stem+'_tracking.json')
            if sha256(config_path)!=expected_hash:raise ValueError('Review configuration changed')
            if sha256(track_path)!=recorded['input_sha256'].get(str(track_path)):
                raise ValueError('Preserved tracking result changed')
            config=Config.from_dict(json.loads(config_path.read_text()));track=json.loads(track_path.read_text())
            if track['config']!=asdict(config):raise ValueError('Stored tracking configuration does not match')
            hashes.update({str(config_path):sha256(config_path),str(track_path):sha256(track_path)})
            selected=[o for o in track['observations'] if o['obs_id'] in crossed_ids]
            if len(selected)!=len(crossed_ids):raise ValueError('Stored tracking observations incomplete')
            acceptance.append(dict(configuration=name,crossed_observations=len(selected),
                assigned_id=sum(o['track_id'] is not None for o in selected),
                supported_position=sum(o['xyz'] is not None and o['position_source'] in ['sdk_estimate','partial_observation_estimate'] for o in selected),
                ambiguous=sum(o['id_status']=='ambiguous' for o in selected)))
    result=dict(scope='Reviewed sparse frames from two recordings only; not independent operating-point validation',
        notes=['High fitted-joint confidence is not an identity or direct-measurement guarantee.',
               'No crossing detected does not prove correct identity, and an observed crossing is only a conservative warning.',
               'Root-to-head geometry is SDK-fitted and is not independent anthropometric ground truth.',
               'No candidate is adopted or tuned from this small, previously examined sample.',
               'The 70 threshold is a post-hoc illustration, not an evaluated classifier or a recall estimate.'],
        input_sha256=hashes,evaluation_sha256=sha256(Path('corridor_tracking/evaluation.py')),
        script_sha256=sha256(Path(__file__)),summaries=summaries,population=population,tracking_acceptance=acceptance)
    (a.output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
