#!/usr/bin/env python3
"""Analyze full-frame exports using an explicitly scoped provisional calibration."""
import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import sys
import traceback

from corridor_tracking.data import sha256
from body.corridor_tracking.tracker import Config
from body.corridor_tracking.replay import write_overview
from body.process_tracking_v2 import process_one,write_json


def scope_calibration(calibration,camera,calibration_hash):
    """Retain the surveyed setup while documenting subpixel SDK intrinsic changes.

    These are camera-frame 3D SDK points, already reconstructed with each SVO's
    own intrinsics; the calibration is the extrinsic floor/corridor transform.
    This limited compatibility decision does not prove metric accuracy.
    """
    scope=calibration['applies_to']
    if calibration.get('setup_id')!=camera.get('setup_id'):
        raise ValueError('Setup IDs differ; do not silently transfer calibration')
    for k in ['serial_number','width','height','depth_mode','coordinate_units']:
        if scope.get(k)!=camera.get(k):
            raise ValueError(f'Calibration/camera mismatch: {k}')
    if not all(str(x).startswith('IMAGE') for x in [scope['coordinate_system'],camera['coordinate_system']]):
        raise ValueError('Both calibration and recording must use IMAGE coordinates')
    a,b=scope['intrinsics_left'],camera['intrinsics_left']
    delta={k:float(b[k])-float(a[k]) for k in ['fx','fy','cx','cy']}
    if max(map(abs,delta.values()))>1.0:
        raise ValueError('Intrinsics differ by more than one pixel; review calibration transfer')
    adapted=dict(calibration)
    adapted['applies_to']={k:camera.get(k) for k in scope}
    adapted['scope_transfer']=dict(source_calibration_sha256=calibration_hash,
        source_applies_to=scope,target_applies_to=adapted['applies_to'],intrinsics_delta_px=delta,
        compatibility_max_intrinsics_delta_px=1.,coordinate_system_equivalence='IMAGE axes',
        assumptions=['same physical setup ID; 3D points reconstructed with each recording intrinsics',
                     'floor/wall model and extrinsic camera pose remained fixed',
                     'intrinsic tolerance is a screening rule, not a measured position error'],
        status='provisional_not_survey_validated')
    return adapted


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-roots',type=Path,nargs='+',required=True)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expected-count',type=int,default=55)
    p.add_argument('--group',choices=['2','3'],default='2')
    a=p.parse_args()
    sources={}
    for root in a.input_roots:
        for d in sorted(root.glob('recording_*/body')):
            name=d.parent.name
            if name in sources:
                raise ValueError('Duplicate recording in inputs: '+name)
            sources[name]=d
    expected={f'recording_{i:03d}' for i in range(1,a.expected_count+1)}
    if set(sources)!=expected:
        raise ValueError(f'Missing={sorted(expected-set(sources))}, unexpected={sorted(set(sources)-expected)}')
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'scoped_calibrations').mkdir()
    calibration=json.loads(a.calibration.read_text());cal_hash=sha256(a.calibration)
    cfg=Config.from_dict(json.loads(a.config.read_text()))
    write_json(a.output/'run_config.json',dict(command=sys.argv,config=asdict(cfg),config_sha256=sha256(a.config),
        source_calibration=str(a.calibration.resolve()),source_calibration_sha256=cal_hash,
        input_roots=[str(p.resolve()) for p in a.input_roots],physical_setup=calibration.get('setup_id'),group=a.group,
        interpretation='provisional extrinsic transfer, SDK ID reference vs unadopted tracking candidate',
        code_sha256=sha256(Path(__file__))))
    summaries=[];failures=[]
    for recording,source in sorted(sources.items()):
        try:
            camera=json.loads((source/'camera.json').read_text(encoding='utf-8-sig'))
            scoped=scope_calibration(calibration,camera,cal_hash)
            write_json(a.output/'scoped_calibrations'/f'{recording}.json',scoped)
            metrics,checked=process_one(source,a.output/recording,scoped,cfg,recording)
            summaries.append(dict(recording=recording,metrics=metrics,visual_evaluation=checked))
            print(f'{recording}: SDK-ID {metrics["baseline_points"]} -> candidate {metrics["candidate_points"]}; '
                  f'IDs {metrics["baseline_tracks"]} -> {metrics["candidate_tracks"]}',flush=True)
        except Exception as e:
            failures.append(dict(recording=recording,error=str(e),traceback=traceback.format_exc()))
            print(f'{recording}: FAILED {e}',flush=True)
    write_json(a.output/'summary.json',dict(records=summaries,failures=failures))
    with (a.output/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['recording','baseline_points','candidate_points','baseline_tracks','candidate_tracks']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for s in summaries:w.writerow(dict(recording=s['recording'],**{k:s['metrics'][k] for k in fields[1:]}))
    write_overview(a.output,summaries,failures)
    report=a.output/'report.md'
    report.write_text(f'グループ{a.group}・暫定分析（元のSDK IDを基準、候補は未採用）\n\n'
        '全フレームSDK出力に対し、SDK IDのままの基準と追跡候補を同じ時刻で比較した。'
        f'これらは旧0.1秒書き出しとの対照ではない。校正はグループ{a.group}の床・壁候補であり、'
        'ポールによる絶対誤差の独立検証はまだ行っていない。ID数・点数は正解精度ではない。\n\n'
        'カメラ個体・解像度・深度・設置IDを確認し、各録画の画像座標系の表記差と1px以内の内部パラメータ差を記録した。'
        '元校正・元SDK出力は変更していない。scoped_calibrationsに録画別の適用条件と差分を保存した。\n\n'
        +report.read_text(),encoding='utf-8')
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
