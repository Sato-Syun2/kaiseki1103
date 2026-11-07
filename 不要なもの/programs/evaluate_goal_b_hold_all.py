#!/usr/bin/env python3
"""Reprocess group 2/3 observations with the experimental SDK-ID hold.

Existing runs and observations are never changed. Counts are diagnostics,
not identity accuracy; use image labels for adoption decisions.
"""
import argparse
import csv
import json
from pathlib import Path
import time

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import diagnostics
from corridor_tracking.tracker import Config, run_tracker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    config_path=Path('configs/tracking_goal_b_hold_candidate_20261104.json')
    config=Config.from_dict(json.loads(config_path.read_text()))
    roots=[Path('results/tracking_v2/group002_20261104_analysis_01'),
           Path('results/tracking_v2/group003_20261104_analysis_01')]
    records=[]; failures=[]
    for root in roots:
        group='group002' if 'group002' in root.name else 'group003'
        prior=json.loads((root/'summary.json').read_text())
        if prior['failures']:raise ValueError('Source run contains failures: '+str(root))
        for record in prior['records']:
            name=record['recording'];source=root/name/'observations.json';start=time.monotonic()
            try:
                data=json.loads(source.read_text());result=run_tracker(data,config);m=diagnostics(data,result)
                target=a.output/group/name;target.mkdir(parents=True,exist_ok=False)
                (target/'tracking.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                (target/'metrics.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
                previous=record['metrics']
                row=dict(group=group,recording=name,frames=m['frames'],baseline_points=m['baseline_points'],
                    original_points=previous['candidate_points'],hold_points=m['candidate_points'],
                    baseline_tracks=m['baseline_tracks'],original_tracks=previous['candidate_tracks'],hold_tracks=m['candidate_tracks'],
                    original_ambiguous=previous['id_status'].get('ambiguous',0),hold_ambiguous=m['id_status'].get('ambiguous',0),
                    hold_unresolved=m['sources'].get('unresolved_identity',0),
                    input_sha256=sha256(source),tracking_sha256=sha256(target/'tracking.json'),seconds=round(time.monotonic()-start,3))
                records.append(row);print(group,name,'points',row['original_points'],'->',row['hold_points'],
                    'IDs',row['original_tracks'],'->',row['hold_tracks'],flush=True)
            except Exception as exc:
                failures.append(dict(group=group,recording=name,error=str(exc)))
                print(group,name,'FAILED',exc,flush=True)
    if records:
        with (a.output/'comparison.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    summary=dict(records=records,failures=failures,config_sha256=sha256(config_path),
        tracker_sha256=sha256(Path('corridor_tracking/tracker.py')),script_sha256=sha256(Path(__file__)),
        interpretation='Diagnostics only. This is not measured person recall or ID accuracy; hold candidate is not adopted.')
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
