#!/usr/bin/env python3
"""Create a separate, narrowly reviewed group003/002 result and replay.

Only explicitly reviewed images can trigger exclusions. Intervening frames
are not adjudicated, and all derived interpolation/prediction is omitted.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import cross_person_anchors, diagnostics
from corridor_tracking.manual_review import exclude_reviewed_observations,label_visual_review_scope
from corridor_tracking.replay import write_replay


def write_json(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    source=Path('results/tracking_v2/group003_20261104_analysis_01/recording_002')
    review=Path('results/tracking_v2/goal_b_visual_holdout_20261104_01')
    calibration=Path('results/tracking_v2/group003_20261104_analysis_01/scoped_calibrations/recording_002.json')
    manifest=json.loads((source/'manifest.json').read_text());ann=json.loads((review/'annotations.json').read_text())
    for name in ['observations.json','tracking.json']:
        if sha256(source/name)!=manifest['output_hashes'][name]:raise ValueError('Source changed: '+name)
    calibration_value=json.loads(calibration.read_text())
    calibration_hash=hashlib.sha256(json.dumps(calibration_value,sort_keys=True).encode()).hexdigest()
    if calibration_hash!=manifest['calibration_hash']:raise ValueError('Calibration changed')
    data=json.loads((source/'observations.json').read_text());tracking=json.loads((source/'tracking.json').read_text())
    frames={f['timestamp_ns']:f for f in data['frames']};by_frame=defaultdict(list)
    for obs in data['observations']:by_frame[obs['frame_index']].append(obs)
    evidence={};reviewed_frames=[]
    for label in ann['intervals'][0]['frames']:
        f=frames.get(label['timestamp_ns'])
        if f is None or not f['image_path']:raise ValueError('Reviewed frame absent')
        if sha256(Path(f['image_path']))!=ann['image_sha256'][str(f['frame_index'])]:raise ValueError('Reviewed image changed')
        reviewed_frames.append(f)
        for cross in cross_person_anchors(by_frame[f['frame_index']],label['people']):
            evidence[cross['obs_id']]=dict(frame_index=f['frame_index'],timestamp_ns=f['timestamp_ns'],
                visible_regions_and_joint_indices=cross['people'],annotation_file=str((review/'annotations.json').resolve()))
    if not evidence:raise ValueError('No reviewed crossing observations')
    for f in data['frames']:
        if f['image_path'] and sha256(Path(f['image_path']))!=manifest['image_hashes'][f['image']]:
            raise ValueError('Source replay image changed')
    manual=exclude_reviewed_observations(tracking,evidence)
    manual=label_visual_review_scope(manual,[f['frame_index'] for f in reviewed_frames],
        min(f['t'] for f in reviewed_frames),max(f['t'] for f in reviewed_frames))
    a.output.mkdir(parents=True,exist_ok=False);folder=a.output/'recording_002';folder.mkdir()
    write_json(folder/'manual_tracking.json',manual);write_json(folder/'automatic_tracking.json',tracking)
    fields=['obs_id','frame_index','t','sdk_id','track_id','xyz','position_source','id_status','visual_review_status']
    with (folder/'manual_trajectories.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for o in manual['observations']:
            writer.writerow({k:json.dumps(o[k]) if isinstance(o.get(k),(list,dict)) else o.get(k) for k in fields})
    write_replay(folder,data,tracking,calibration_value,'recording_002',anchored=manual)
    page=folder/'index.html';html=page.read_text();marker="option.textContent='手動アンカー適用';"
    if html.count(marker)!=1:raise ValueError('Unknown replay template')
    html=html.replace(marker,"option.textContent='目視確認箇所のみ除外';option.selected=true;",1)
    old='座標校正は別途検証が必要です。'
    notice='目視で確認した保存画像10枚の混在骨格のみを除外しています。画像間やその他の区間は未確認で、個別の画像確認欄に表示します。手動モードでは補間・予測を表示しません。'
    if old not in html:raise ValueError('Unknown replay notice')
    html=html.replace(old,notice,1)
    html=html.replace('trajectories.csv','manual_trajectories.csv').replace('metrics.json','manual_metrics.json').replace('tracking.json','manual_tracking.json')
    page.write_text(html,encoding='utf-8')
    metrics=diagnostics(data,manual);write_json(folder/'manual_metrics.json',metrics)
    summary=dict(scope='Only 10 image frames reviewed; unreviewed frames may contain the same problem',
        exclusion_count=len(evidence),reviewed_image_count=len(ann['intervals'][0]['frames']),
        visual_review_status_counts=dict(Counter(o['visual_review_status'] for o in manual['observations'])),
        review_window_s=manual['manual_review']['review_window_s'],
        automatic_supported=diagnostics(data,tracking)['candidate_points'],
        manually_retained_supported=metrics['candidate_points'],derived_omitted=True,
        source_hashes={str(path):sha256(path) for path in [source/'manifest.json',source/'observations.json',source/'tracking.json',review/'annotations.json',calibration]},
        code_hashes={str(path):sha256(path) for path in [Path(__file__),Path('corridor_tracking/manual_review.py'),Path('corridor_tracking/evaluation.py'),Path('corridor_tracking/replay_template.html')]},
        outputs={x:sha256(folder/x) for x in ['index.html','manual_tracking.json','automatic_tracking.json','manual_trajectories.csv','manual_metrics.json']})
    write_json(a.output/'manifest.json',summary)
    (a.output/'report.md').write_text('# 録画002: 目視確認箇所の除外\n\n'
        '[手動確認用リプレイ](recording_002/index.html) / [手動確認用CSV](recording_002/manual_trajectories.csv)\n\n'
        f'保存画像10枚で確認した混在骨格{len(evidence)}観測を手動モードだけで除外した。'
        '他の時間は未確認で、混在がないことは保証しない。補間と予測は手動モードに含めない。'
        '自動結果は別のまま残しており、手動介入を自動追跡の精度向上として数えない。\n\n'
        'CSVのvisual_review_statusは画像確認の範囲を表す。unreviewed_between_images_with_crossingは混在確認画像の間を示すが、全フレームが混在しているという意味ではない。unreviewed_outside_review_windowとother_observation_on_reviewed_image_not_adjudicatedも未判定であり、正しいことを保証しない。\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['exclusion_count','reviewed_image_count','automatic_supported','manually_retained_supported']},ensure_ascii=False))


if __name__=='__main__':main()
