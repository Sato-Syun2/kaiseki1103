"""Create a separate two-person identity proposal from already shared positions."""
import argparse
import copy
import csv
import json
from pathlib import Path

from corridor_tracking.coordinate_only_replay import make_page, validate_input
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.reassign_depth_identity import review_page, trial_condition
from corridor_tracking.reassign_depth_identity_temporal import propose_backwards
from depth_person_prototype import digest
from zed_sdk_package.tracking_v2.validate_export import validate_export


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--body',type=Path,required=True);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--progress',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--group',type=int,required=True);p.add_argument('--recording',required=True)
    p.add_argument('--target-id',type=int,required=True);p.add_argument('--reference-id',type=int,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('candidate destination exists')
    with a.inventory.open(newline='',encoding='utf-8-sig') as stream:
        rows=[r for r in csv.DictReader(stream) if r['group']==str(a.group) and r['recording']==a.recording]
    if len(rows)!=1:raise ValueError('recording missing or duplicated in inventory')
    row=rows[0];data=validate_input(a.input,row);original=copy.deepcopy(data)
    validate_export(a.body)
    camera=json.loads((a.body/'camera.json').read_text(encoding='utf-8-sig'))
    if camera['source_svo_sha256']!=row['source_svo_sha256'] or digest(a.body/'manifest.json')!=row['body_manifest_sha256']:
        raise ValueError('image export source mismatch')
    cal_path=Path(row['calibration'])
    if digest(cal_path)!=row['calibration_sha256']:raise ValueError('calibration mismatch')
    cal=json.loads(cal_path.read_text(encoding='utf-8-sig'))
    plan=json.loads(a.plan.read_text(encoding='utf-8-sig'))
    progress=json.loads(a.progress.read_text(encoding='utf-8-sig'))
    condition=trial_condition(plan,progress,a.group,a.recording)
    frames,changes,diagnostics=propose_backwards(data['frames'],a.target_id,a.reference_id)
    if not changes:raise ValueError('no sufficiently supported reassignment candidates')
    source_hash=digest(a.input/'positions.json')
    data['frames']=frames
    data['reassignment_candidate']={'status':'proposed_not_verified','target_id':a.target_id,
        'source_positions_sha256':source_hash,'plan_sha256':plan['plan_sha256'],
        'trial_number':condition['global_trial_number'],'condition_id':condition['condition_id'],
        'method':'backward_local_motion_height_v1'}
    data['walls']={'visible':cal.get('visible_wall_Y_m'),
                   'opposite':(cal.get('other_wall_inference') or {}).get('opposite_wall_Y_m_assuming_same_boundaries')}
    if validate_candidate(original,data,source_hash)!=len(changes):raise ValueError('candidate validation mismatch')
    with (a.body/'frames.csv').open(newline='',encoding='utf-8-sig') as stream:
        body_frames=list(csv.DictReader(stream))
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=False)
    start=max(0,changes[0]['frame_index']-10);end=min(len(frames)-1,diagnostics['anchor_frame']+10)
    review,image_count=review_page(frames,body_frames,a.body,camera,cal,output,start,end,
                                   target_id=a.target_id,reference_id=a.reference_id)
    (output/'positions.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (output/'assignments.json').write_text(json.dumps({'assignments':changes,'diagnostics':diagnostics,'condition':condition},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'index.html').write_text(make_page(data,f'グループ{a.group} {a.recording} ID再割当て候補'),encoding='utf-8')
    (output/'review.html').write_text(review,encoding='utf-8')
    unknown=sum(o['track_id'] is None for f in frames for o in f['observations'])
    unknown_with_pos=sum(o['track_id'] is None and o['surface_corridor_m'] is not None for f in frames for o in f['observations'])
    report=f'''# グループ{a.group} {a.recording}：ID再割当て候補\n\n既存ID {a.target_id}を画像で確認した暫定基点とし、基準ID {a.reference_id}との分離、隣接時刻の位置・高さ・歩行方向と候補間の競合を確認して、ID未確定だった{len(changes)}観測にID {a.target_id}を**未確認候補**として付けた。元のID付き観測・全座標・フレーム時刻は変更せず、検出がない時刻の位置補間もしていない。未確定は{unknown}観測、うち座標あり{unknown_with_pos}観測。\n\n条件{condition['condition_id']}は計画上の追い越し試行であり、実際の人物番号や経路の正解を示さない。基点はフレーム{diagnostics['anchor_frame']}。候補はフレーム{changes[0]['frame_index']}〜{changes[-1]['frame_index']}で、間に欠測・保留がある。設定と観測ごとの値は `assignments.json`。\n\n[同時刻の画像で確認](review.html)できる保存画像は{image_count}枚。重なりや背景・脚などの混入があり得るため、全フレームの正解や精度向上を保証しない。追い越し中に２人が重なった区間や候補が競合する区間は保留する。\n'''
    (output/'report_ja.md').write_text(report,encoding='utf-8')
    manifest={'status':'proposed_not_verified','source_positions_sha256':source_hash,
              'source_manifest_sha256':digest(a.input/'manifest.json'),'body_manifest_sha256':digest(a.body/'manifest.json'),
              'plan_file_sha256':digest(a.plan),'recording_progress_sha256':digest(a.progress),
              'calibration_sha256':digest(cal_path),'script_sha256':digest(Path(__file__)),
              'method_sha256':digest(Path(__file__).with_name('reassign_depth_identity_temporal.py')),
              'files_sha256':{x.name:digest(x) for x in output.iterdir() if x.is_file()}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Proposed {len(changes)} observations; {unknown} remain unassigned; {image_count} review images: {output}')


if __name__=='__main__':main()
