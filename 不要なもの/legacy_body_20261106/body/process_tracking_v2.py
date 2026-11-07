#!/usr/bin/env python3
"""Process legacy/full-frame exports into versioned tracking comparisons."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import traceback
import platform
import time
import cv2
import numpy as np

from corridor_tracking.data import load_export,sha256
from body.corridor_tracking.tracker import Config,run_tracker,apply_anchors
from body.corridor_tracking.evaluation import diagnostics,evaluate_checkpoints,evaluate_intervals


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def process_one(source,output,calibration,config,recording,annotations=None,anchors=None,head_source=None,replay=True):
    start=time.monotonic()
    output.mkdir(parents=True,exist_ok=False)
    data = load_export(source,calibration,with_appearance=config.appearance_weight>0,heads_folder=head_source)
    result = run_tracker(data,config)
    metrics = diagnostics(data,result)
    checked = evaluate_checkpoints(data,result,annotations,recording) if annotations else None
    if checked is not None:
        checked['reviewed_intervals']=evaluate_intervals(data,result,annotations,recording)
    write_json(output/'observations.json',data)
    write_json(output/'tracking.json',result)
    write_json(output/'metrics.json',metrics)
    if checked:
        write_json(output/'visual_evaluation.json',checked)
    anchored = None
    if anchors:
        anchored = apply_anchors(result,anchors)
        write_json(output/'tracking_anchored.json',anchored)
        if annotations:
            anchored_check=evaluate_checkpoints(data,anchored,annotations,recording)
            anchored_check['reviewed_intervals']=evaluate_intervals(data,anchored,annotations,recording)
            write_json(output/'visual_evaluation_anchored.json',anchored_check)
    with (output/'trajectories.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['frame_index','timestamp_ns','t','obs_id','sdk_id','track_id','subject_id','position_source','id_status','X_m','Y_m','Z_m','sigma_m','parts']
        w = csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for p in [*result['observations'],*result['derived']]:
            row = {k:p.get(k) for k in fields if k not in ['X_m','Y_m','Z_m','parts']}
            row.update(dict(zip(['X_m','Y_m','Z_m'],p['xyz'] or [None]*3)))
            row['parts'] = json.dumps(p.get('parts',[]))
            w.writerow(row)
    if replay:
        from body.corridor_tracking.replay import write_replay
        write_replay(output,data,result,calibration,recording,anchored)
    project=Path(__file__).resolve().parent.parent
    code=[*sorted((project/'corridor_tracking').glob('*.py')), *sorted((project/'body/corridor_tracking').glob('*.py')),
          project/'body/corridor_tracking/replay_template.html',
          project/'zed_sdk_package/tracking_v2/validate_export.py',Path(__file__).resolve()]
    manifest = dict(schema_version=2,recording=recording,status='complete',input_hashes=data['input_hashes'],
                    config=asdict(config),source=str(source.resolve()),
                    camera={k:data['camera'].get(k) for k in ['camera_model','sdk_version','fps','width','height','depth_mode','body_tracking_model_gen']},
                    calibration_hash=hashlib.sha256(json.dumps(calibration,sort_keys=True).encode()).hexdigest(),
                    output_hashes={p.name:sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
                    image_hashes=data['image_hashes'],
                    annotations_sha256=hashlib.sha256(json.dumps(annotations,sort_keys=True).encode()).hexdigest() if annotations else None,
                    anchors_sha256=hashlib.sha256(json.dumps(anchors,sort_keys=True).encode()).hexdigest() if anchors else None,
                    code_hashes={str(p.relative_to(project)):sha256(p) for p in code},
                    elapsed_wall_s=time.monotonic()-start,python_version=platform.python_version(),
                    dependency_versions=dict(numpy=np.__version__,opencv=cv2.__version__),
                    adoption='candidate_only_until_reviewed',sdk_hardware_tested=False)
    write_json(output/'manifest.json',manifest)
    return metrics,checked


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exchange-root',type=Path,default=Path('/data/experiment_data/kaiseki1103/exchange'))
    p.add_argument('--input-tag',default='20261103')
    p.add_argument('--source',type=Path,help='Single legacy or v2 SDK export folder')
    p.add_argument('--heads',type=Path,help='Optional separate head export for --source')
    p.add_argument('--recording',default='recording_unknown')
    p.add_argument('--recordings',default=','.join(str(i) for i in range(1,49)))
    p.add_argument('--output',type=Path,required=True,help='New run directory, never overwritten')
    p.add_argument('--calibration',type=Path,default=Path('results/recording_001/zed_depth_review/zed_corridor_candidate.json'))
    p.add_argument('--config',type=Path)
    p.add_argument('--annotations',type=Path)
    p.add_argument('--anchors',type=Path,help='Single recording observation anchors (separate result)')
    p.add_argument('--no-replay',action='store_true')
    a = p.parse_args()
    cfg = Config.from_dict(json.loads(a.config.read_text())) if a.config else Config()
    calibration = json.loads(a.calibration.read_text())
    annotations = json.loads(a.annotations.read_text()) if a.annotations else None
    anchors = json.loads(a.anchors.read_text()) if a.anchors else None
    if (a.heads or a.anchors) and not a.source:
        p.error('--heads and --anchors require --source')
    a.output.mkdir(parents=True,exist_ok=False)
    write_json(a.output/'run_config.json',dict(config=asdict(cfg),calibration=str(a.calibration.resolve()),
                config_file=str(a.config.resolve()) if a.config else None,config_sha256=sha256(a.config) if a.config else None,
                calibration_sha256=sha256(a.calibration),annotations_sha256=sha256(a.annotations) if a.annotations else None,
                command=sys.argv,python_version=platform.python_version(),
                anchors_sha256=sha256(a.anchors) if a.anchors else None,
                scope='candidate evaluation, not automatic adoption'))
    sources = [(a.recording,a.source)] if a.source else [(f'recording_{i:03d}',a.exchange_root/f'recording_{i:03d}'/f'model_comparison_{a.input_tag}'/'ACCURATE_GEN2') for i in map(int,a.recordings.split(','))]
    summaries,failures = [],[]
    for recording,source in sources:
        try:
            metrics,checked = process_one(source,a.output/recording,calibration,cfg,recording,annotations,anchors,a.heads,not a.no_replay)
            summaries.append(dict(recording=recording,metrics=metrics,visual_evaluation=checked))
            print(f'{recording}: {metrics["baseline_points"]} -> {metrics["candidate_points"]} supported estimates; {metrics["baseline_tracks"]} -> {metrics["candidate_tracks"]} tracks',flush=True)
        except Exception as exc:
            failures.append(dict(recording=recording,error=str(exc),traceback=traceback.format_exc()))
            print(f'{recording}: FAILED {exc}',flush=True)
    write_json(a.output/'summary.json',dict(records=summaries,failures=failures))
    with (a.output/'summary.csv').open('w',newline='') as f:
        fields=['recording','baseline_points','candidate_points','baseline_tracks','candidate_tracks']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for s in summaries:
            w.writerow(dict(recording=s['recording'],**{k:s['metrics'][k] for k in fields[1:]}))
    from body.corridor_tracking.replay import write_overview
    write_overview(a.output,summaries,failures)
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
