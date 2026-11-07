"""Propose conservative backward reassociation of depth observations for one trial."""
import argparse
import copy
import csv
import html
import json
import math
import os
from pathlib import Path
import statistics

import numpy as np

from corridor_tracking.coordinate_only_replay import make_page, validate_input
from depth_person_prototype import digest
from zed_sdk_package.tracking_v2.validate_export import validate_export


# The operator reported recording/condition exceptions in this specific plan.
# Do not label affected trials using the original progress file until reviewed.
_EXCEPTION_PLAN = 'ebf77fa7972d13c7d51f0bf31021d57c8bb63e77fd347ac4ad34678b63dd8a5a'


def trial_condition(plan, progress, group, recording):
    if plan.get('plan_sha256') != progress.get('plan_sha256') or progress.get('group') != f'G{group:02d}':
        raise ValueError('experiment plan and recording progress do not match')
    trials = []
    for number, attempts in progress.get('attempts', {}).items():
        if any(x.get('recording_id') == recording and x.get('status') == 'complete' for x in attempts):
            trials.append(int(number))
    if len(trials) != 1:
        raise ValueError('recording does not uniquely map to one completed trial')
    if (plan.get('plan_sha256') == _EXCEPTION_PLAN and
            (group == 6 or (group == 7 and trials[0] >= 55) or (group == 9 and trials[0] == 9))):
        raise ValueError('reported recording/condition exception requires review; see experiment_metadata/recording_exceptions_20261106.md')
    group_plan = plan['groups'][f'G{group:02d}']
    matching = [x for x in group_plan['trials'] if int(x['global_trial_number']) == trials[0]]
    if len(matching) != 1 or matching[0]['condition_category'] != '追い越し':
        raise ValueError('this candidate requires a two-person overtaking trial')
    return matching[0]


def propose(frames, target_id, reference_id, *, max_gap=.30, base_gate=.12, speed_gate=2.,
            min_separation=.35, margin=.15, height_margin=.30, backward_tolerance=.18):
    """Follow unassigned observations backwards from an established track.

    This is a development hypothesis, not a validated probability or truth label.
    No coordinates are invented or altered; ambiguous or missing candidates remain unassigned.
    """
    if target_id == reference_id:
        raise ValueError('target and reference must be distinct')
    anchored = [(f, o) for f in frames for o in f['observations']
                if o['track_id'] == target_id and o.get('surface_corridor_m') is not None]
    if len(anchored) < 10:
        raise ValueError('insufficient target track to establish an anchor')
    seed, target = anchored[0]
    sample = [(f, o) for f, o in anchored if 0 <= f['elapsed_s']-seed['elapsed_s'] <= 1.0]
    if len(sample) < 8:
        raise ValueError('insufficient local anchor observations')
    speeds = [(b[1]['surface_corridor_m'][0]-a[1]['surface_corridor_m'][0])/(b[0]['elapsed_s']-a[0]['elapsed_s'])
              for a, b in zip(sample, sample[1:]) if 0 < b[0]['elapsed_s']-a[0]['elapsed_s'] <= .15]
    if len(speeds) < 5 or abs(statistics.median(speeds)) < .25:
        raise ValueError('anchor does not establish a clear motion direction')
    velocity = statistics.median(speeds)
    sign = 1 if velocity > 0 else -1
    height = statistics.median(o['surface_corridor_m'][2] for _, o in sample)
    bounds = (height-height_margin, height+height_margin)
    updated = copy.deepcopy(frames)
    seed_index = int(seed['frame_index'])
    last_time = float(seed['elapsed_s'])
    last_point = target['surface_corridor_m']
    changes, reasons = [], {'missing_reference': 0, 'no_eligible_candidate': 0, 'ambiguous_candidates': 0}
    stop = 'start_of_recording'
    for frame in reversed(updated[:seed_index]):
        dt = last_time - frame['elapsed_s']
        if dt <= 0:
            raise ValueError('non-increasing time')
        if dt > max_gap:
            stop = 'gap_exceeded'
            break
        reference = [o for o in frame['observations'] if o['track_id'] == reference_id and o.get('surface_corridor_m') is not None]
        if len(reference) != 1:
            reasons['missing_reference'] += 1
            continue
        options = []
        for index, obs in enumerate(frame['observations']):
            point = obs.get('surface_corridor_m')
            if obs['track_id'] is not None or point is None or not bounds[0] <= point[2] <= bounds[1]:
                continue
            distance = math.dist(point[:2], last_point[:2])
            separation = math.dist(point[:2], reference[0]['surface_corridor_m'][:2])
            reverse_advance = sign * (point[0] - last_point[0])
            if distance <= base_gate + speed_gate*dt and separation >= min_separation and reverse_advance <= backward_tolerance:
                options.append((distance, index, point, separation))
        options.sort(key=lambda x: (x[0], x[1]))
        if not options:
            reasons['no_eligible_candidate'] += 1
            continue
        if len(options) > 1 and options[1][0]-options[0][0] < margin:
            reasons['ambiguous_candidates'] += 1
            continue
        distance, index, point, separation = options[0]
        obs = frame['observations'][index]
        obs['original_track_id'] = None
        obs['track_id'] = target_id
        obs['identity_assignment'] = 'proposed'
        changes.append({'frame_index': frame['frame_index'], 'observation_index': index,
                        'timestamp_ns': frame['timestamp_ns'], 'elapsed_s': frame['elapsed_s'],
                        'original_track_id': None, 'proposed_track_id': target_id,
                        'surface_corridor_m': point, 'time_to_next_s': round(dt, 6),
                        'distance_to_next_xy_m': round(distance, 6), 'reference_separation_xy_m': round(separation, 6),
                        'status': 'proposed_not_verified'})
        last_time, last_point = frame['elapsed_s'], point
    changes.reverse()
    diagnostics = {'target_id': target_id, 'reference_id': reference_id, 'anchor_frame': seed_index,
                   'anchor_elapsed_s': seed['elapsed_s'], 'anchor_sample_count': len(sample),
                   'anchor_median_x_velocity_m_s': velocity, 'anchor_median_height_m': height,
                   'allowed_surface_height_m': list(bounds), 'stop_reason': stop, 'rejection_counts': reasons,
                   'settings': {'max_gap_s':max_gap, 'base_gate_m':base_gate, 'speed_gate_m_s':speed_gate,
                                'min_reference_separation_m':min_separation, 'candidate_margin_m':margin,
                                'height_margin_m':height_margin, 'backward_tolerance_m':backward_tolerance}}
    return updated, changes, diagnostics


def pixel_from_corridor(point, camera, calibration):
    floor = calibration['floor_plane_camera_image']
    basis = calibration['corridor_basis_camera_image']
    matrix = np.asarray([basis['X_into_hallway'], basis['Y_positive_toward_ZED_visible_far_wall'], basis['Z_up']])
    camera_point = np.linalg.solve(matrix, np.asarray(point, dtype=float))-float(floor['offset_m'])*np.asarray(floor['normal_down'])
    if camera_point[2] <= 0:
        return None
    intr = camera['intrinsics_left']
    u = float(intr['fx']*camera_point[0]/camera_point[2]+intr['cx'])
    v = float(intr['fy']*camera_point[1]/camera_point[2]+intr['cy'])
    if not (math.isfinite(u) and math.isfinite(v) and 0 <= u < camera['width'] and 0 <= v < camera['height']):
        return None
    return [round(u, 2), round(v, 2)]


def review_page(frames, body_frames, body, camera, cal, output, start, end, target_id=3, reference_id=1):
    source_frames = {int(r['frame_index']):r for r in body_frames}
    pages = []
    for f in frames:
        i = f['frame_index']
        if not start <= i <= end:
            continue
        src = source_frames[i]
        if not src['image_file']:
            continue
        if str(f['timestamp_ns']) != src['image_timestamp_ns']:
            raise ValueError('review image timestamp mismatch')
        image = (body/src['image_file']).resolve()
        if not image.is_file() or not image.is_relative_to(body.resolve()):
            raise ValueError('review image missing or outside BODY export')
        points = []
        for number, o in enumerate(f['observations']):
            if o['surface_corridor_m'] is None:
                continue
            pixel = pixel_from_corridor(o['surface_corridor_m'], camera, cal)
            if pixel:
                points.append({'pixel':pixel,'obs':number,'id':o['track_id'],
                               'proposed':o.get('identity_assignment') == 'proposed',
                               'xyz':[round(x, 3) for x in o['surface_corridor_m']]})
        pages.append({'frame_index':i, 'elapsed_s':f['elapsed_s'],
                      'image':os.path.relpath(image, output.resolve()).replace(os.sep, '/'), 'points':points})
    payload = json.dumps(pages, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return r'''<!doctype html><html lang="ja"><meta charset="utf-8"><title>候補と元画像の照合</title>
<style>body{font:16px system-ui;margin:24px}section{border-top:1px solid #bbb;margin:20px 0}canvas{width:min(100%,1200px);height:auto;border:1px solid #aaa}pre{white-space:pre-wrap}</style>
<h1>ID再割当て候補：同時刻の元画像</h1><p>既存のSDK画像（約0.1秒間隔）に、同一フレームの深度代表点を投影。紫はID__TARGET__への仮割当て、緑は既存ID__REFERENCE__、黄は未確定。点が人物・背景のどちらにあるかを確認してください。点のIDは正解ではありません。</p><p><a href="index.html">上面再生へ</a> / <a href="report_ja.md">条件と制約</a></p><div id="list"></div><script type="application/json" id="data">__DATA__</script><script>
const pages=JSON.parse(document.getElementById('data').textContent),root=document.getElementById('list');
for(const f of pages){const section=document.createElement('section'),h=document.createElement('h2'),canvas=document.createElement('canvas'),pre=document.createElement('pre');h.textContent=`frame ${f.frame_index} / ${f.elapsed_s.toFixed(3)} 秒`;pre.textContent=JSON.stringify(f.points,null,2);section.append(h,canvas,pre);root.append(section);const image=new Image();image.onload=()=>{canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);ctx.lineWidth=5;ctx.font='bold 26px sans-serif';for(const p of f.points){ctx.strokeStyle=p.proposed?'#d800ff':(p.id===__REFERENCE__?'#00ff54':'#ffd000');ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(p.pixel[0],p.pixel[1],10,0,7);ctx.stroke();ctx.fillText(`${p.obs}: ${p.proposed?'ID__TARGET__ 候補':p.id===null?'ID?':'ID'+p.id}`,p.pixel[0]+12,p.pixel[1]-10)}};image.src=f.image}
</script></html>'''.replace('__DATA__', payload).replace('__TARGET__', str(target_id)).replace('__REFERENCE__', str(reference_id)), len(pages)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True); p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--body', type=Path, required=True); p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--progress', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--group', type=int, required=True); p.add_argument('--recording', required=True)
    p.add_argument('--target-id', type=int, required=True); p.add_argument('--reference-id', type=int, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('output already exists')
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['group'] == str(a.group) and r['recording'] == a.recording]
    if len(rows) != 1:
        raise ValueError('recording missing or duplicated in inventory')
    row = rows[0]
    data = validate_input(a.input, row)
    validate_export(a.body)
    camera = json.loads((a.body/'camera.json').read_text(encoding='utf-8-sig'))
    if camera['source_svo_sha256'] != row['source_svo_sha256'] or digest(a.body/'manifest.json') != row['body_manifest_sha256']:
        raise ValueError('BODY export source mismatch')
    cal_path = Path(row['calibration'])
    if digest(cal_path) != row['calibration_sha256']:
        raise ValueError('calibration mismatch')
    cal = json.loads(cal_path.read_text(encoding='utf-8-sig'))
    plan = json.loads(a.plan.read_text(encoding='utf-8-sig'))
    progress = json.loads(a.progress.read_text(encoding='utf-8-sig'))
    condition = trial_condition(plan, progress, a.group, a.recording)
    frames, changes, diagnostics = propose(data['frames'], a.target_id, a.reference_id)
    if not changes:
        raise ValueError('no sufficiently supported reassignment candidates')
    with (a.body/'frames.csv').open(newline='', encoding='utf-8-sig') as f:
        body_frames = list(csv.DictReader(f))
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data['frames'] = frames
    data['reassignment_candidate'] = {'status':'proposed_not_verified', 'target_id':a.target_id,
        'source_positions_sha256':digest(a.input/'positions.json'), 'plan_sha256':plan['plan_sha256'],
        'trial_number':condition['global_trial_number'], 'condition_id':condition['condition_id']}
    data['walls'] = {'visible':cal.get('visible_wall_Y_m'),
                     'opposite':cal.get('other_wall_inference', {}).get('opposite_wall_Y_m_assuming_same_boundaries')}
    start=max(0, changes[0]['frame_index']-25); end=min(len(frames)-1,diagnostics['anchor_frame']+12)
    review, image_count = review_page(frames, body_frames, a.body, camera, cal, output, start, end)
    (output/'positions.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (output/'assignments.json').write_text(json.dumps({'assignments':changes,'diagnostics':diagnostics,
        'condition':condition}, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (output/'index.html').write_text(make_page(data, f'グループ{a.group} {a.recording} ID再割当て候補'), encoding='utf-8')
    (output/'review.html').write_text(review, encoding='utf-8')
    without = sum(o['track_id'] is None for f in frames for o in f['observations'])
    without_pos = sum(o['track_id'] is None and o['surface_corridor_m'] is None for f in frames for o in f['observations'])
    report = f'''# グループ{a.group} {a.recording}：ID再割当て候補\n\n共有元の座標は変更せず、ID未確定だった{len(changes)}観測をID {a.target_id}への**未確認候補**として別出力した。再割当て候補以外は変更せず、未確定は{without}観測（うち座標なし{without_pos}観測）。各観測の座標・時刻は元のままで、欠測位置の補間はない。白縁・破線は仮割当て。\n\n録画進捗とplan_sha256が一致し、試行{condition['global_trial_number']}、条件{condition['condition_id']}（{condition['condition_category']}、幅{condition['corridor_width']}、追い越し方向{condition['overtaking_direction']}）に対応した。計画は人数・試行種別の参考であり、実際の行動や被験者番号の正解ではない。被験者番号は割り当てていない。\n\n既存ID {a.target_id}が安定している区間を基点（フレーム{diagnostics['anchor_frame']}、{diagnostics['anchor_elapsed_s']:.3f}秒）とし、その前の未確定座標を時間逆向きに追跡。隣接の時間差、廊下XYの移動量、既存ID {a.reference_id}との分離、候補間競合、既存ID {a.target_id}の表面高さと移動方向の整合を条件にした。しきい値は開発用で未検証。設定・各観測の根拠は `assignments.json`。\n\n[元画像と候補の照合](review.html)は同時刻のSDK書き出し画像{image_count}枚に深度点を投影する。画像で確認できるのは保存画像の時刻だけであり、他の全フレームや3D深度の正確さの検証ではない。背景・脚への混入やIDの混同が残り得る。ID2とID3の統合、被験者1・2の確定、座標の補正はしていない。\n'''
    (output/'report_ja.md').write_text(report, encoding='utf-8')
    manifest = {'status':'proposed_not_verified', 'source_positions_sha256':digest(a.input/'positions.json'),
                'source_manifest_sha256':digest(a.input/'manifest.json'), 'body_manifest_sha256':digest(a.body/'manifest.json'),
                'plan_file_sha256':digest(a.plan), 'recording_progress_sha256':digest(a.progress),
                'calibration_sha256':digest(cal_path), 'script_sha256':digest(Path(__file__)),
                'files_sha256':{x.name:digest(x) for x in output.iterdir() if x.is_file()}}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Proposed {len(changes)} observations; {without} remain unassigned; {image_count} review images: {output}')


if __name__ == '__main__':
    main()
