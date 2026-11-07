#!/usr/bin/env python3
"""Inspect spacing between previously reviewed pole pixels, without fitting.

The pole stations are user-provided approximate positions. A selected pixel
represents a surface rather than its surveyed centre, and serial depth samples
are correlated. This descriptive comparison is not independent validation.
"""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

import numpy as np

from corridor_tracking.data import sha256


def calculate_spacings(stations):
    """Compare station medians; any common longitudinal origin cancels."""
    if len(stations)<2:raise ValueError('At least two stations are required')
    ordered=sorted(stations,key=lambda x:x['distance_from_end_m'])
    if len({x['distance_from_end_m'] for x in ordered})!=len(ordered):
        raise ValueError('Station distances must be distinct')
    results=[]
    for near,far in zip(ordered,ordered[1:]):
        measured=far['median_X_m']-near['median_X_m']
        reference=far['distance_from_end_m']-near['distance_from_end_m']
        if not np.isfinite([measured,reference]).all():raise ValueError('Station values must be finite')
        results.append(dict(near_station_m=near['distance_from_end_m'],far_station_m=far['distance_from_end_m'],
            nominal_spacing_m=reference,observed_median_spacing_m=measured,
            observed_minus_nominal_m=measured-reference))
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    summary_path=a.input/'summary.json';samples_path=a.input/'samples.csv'
    previous=json.loads(summary_path.read_text())
    with samples_path.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    by=defaultdict(list);seen=set()
    for row in rows:
        station=int(row['station_from_end_m']);stamp=row['timestamp_ns'];key=(station,stamp)
        if key in seen:raise ValueError('Repeated station timestamp')
        seen.add(key)
        if row['corridor_X_m']:
            value=float(row['corridor_X_m'])
            if not np.isfinite(value):raise ValueError('Nonfinite point')
            by[station].append(value)
    for station in previous['stations']:
        key=station['distance_from_end_m'];values=by[key]
        if len(values)!=station['valid'] or not values or not np.isclose(np.median(values),station['median_X_m'],rtol=0,atol=1e-12):
            raise ValueError('Saved samples and station summary do not agree')
    if set(by)!={x['distance_from_end_m'] for x in previous['stations']}:
        raise ValueError('Samples and summary have different stations')
    results=calculate_spacings(previous['stations'])
    a.output.mkdir(parents=True,exist_ok=False)
    with (a.output/'spacing.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    report=dict(spacings=results,input_sha256={str(summary_path):sha256(summary_path),str(samples_path):sha256(samples_path)},
        input_depth_sha256=previous['depth_inputs_sha256'],calibration_sha256=previous['calibration_sha256'],
        script_sha256=sha256(Path(__file__)),interpretation='Descriptive differences of two station medians, not independent calibration validation',
        limitations=['One previously selected surface pixel at each station; selection may depend on prior inspection.',
          'Repeated frames at one stationary pole position are correlated, not independent trials.',
          'A common longitudinal origin offset cancels; surface-versus-centre differences, sight direction and provisional orientation do not necessarily cancel.',
          'Positions were supplied as nominal corridor-axis station locations; measurement uncertainty is not established.',
          'Only 3, 5 and 7 m stations were visually reviewed for these points; 9–15 m are not evaluated.',
          'No correction or 3D accuracy claim is derived from these differences.'])
    (a.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# ポール間隔の参考比較','','既に目視選択した各距離の支柱表面1画素について、静止中の複数時刻のX中央値を引いた。',
        'カメラ位置の共通の原点差は引き算で消えるが、表面と中心の差、視線、暫定姿勢の影響は残り得る。',
        '画素選択後の参考値であり、独立検証・補正係数・3D絶対精度ではない。','',
        '| 設置点 | 公称間隔 | X中央値の差 | 差から公称間隔を引いた値 |',
        '|---|---:|---:|---:|']
    for x in results:
        lines.append(f"| {x['near_station_m']}→{x['far_station_m']}m | {x['nominal_spacing_m']:.3f}m | {x['observed_median_spacing_m']:.3f}m | {x['observed_minus_nominal_m']:+.3f}m |")
    lines+=['','繰り返し画像は同じ静止姿勢の連続サンプルで独立試行ではない。9〜15mはこの集計に含まれない。']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(a.output/'report.md')


if __name__=='__main__':main()
