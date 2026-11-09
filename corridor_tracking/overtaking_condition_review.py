"""Review unverified ID candidates against planned overtaking direction.

This does not modify candidates, assign subject identities, or assume a trial
was executed as planned. It requires observed order exchange and a sustained
side near that exchange before comparing against the planned side.
"""
import argparse
from collections import Counter
from datetime import datetime
import csv
import html
import json
import math
import os
from pathlib import Path
import statistics

from corridor_tracking.audit_depth_tracking import digest, packet, read
from corridor_tracking.audit_trusted10_live import PLAN, PROGRESS, safe_trial
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.propose_trusted10_identities_live import candidate_root
from corridor_tracking.analysis_exclusions import REGISTRY, excluded, load_exclusions

ROOT=Path('results/tracking_v2')
AUDIT=ROOT/'trusted10_quality_live_20261107_01/audit.json'
CANDIDATES=ROOT/'identity_short_anchor_v2_live_20261107_01/summary.json'
OUTPUT=ROOT/'overtaking_condition_review_20261108_01'
WORKBOOK=Path('/home/hp-ubuntu/experiment_recorder/inputs/追い越し実験_完成版_18グループ.xlsx')


def assess(frames, target, reference, planned_side, basis_determinant):
    """Return cautious geometric evidence; all thresholds are exploratory.

    Coordinate basis is camera IMAGE XYZ (right-handed), and its determinant
    gives orientation of corridor XYZ. Positive right component is heading × up.
    """
    if planned_side not in ('右','左') or not .95 < abs(basis_determinant) < 1.05:
        return {'status':'insufficient','reason':'左右または座標軸の向きが未確認'}
    pairs=[]
    for f in frames:
        found={}
        for o in f['observations']:
            p=o.get('surface_corridor_m'); ident=o.get('track_id')
            if ident in (target,reference) and p is not None:
                if ident in found: return {'status':'insufficient','reason':'同一IDの重複'}
                found[ident]=p
        if len(found)==2:
            a,b=found[target],found[reference]
            pairs.append((float(f['elapsed_s']),int(f['frame_index']),a[0],a[1],b[0],b[1]))
    if len(pairs)<20 or pairs[-1][0]-pairs[0][0]<1.0:
        return {'status':'insufficient','reason':'２人の同時位置が不足','paired_samples':len(pairs)}
    # Compare separate beginning/end windows; neither adjacent nor extrapolated points.
    span=min(1.0,(pairs[-1][0]-pairs[0][0])/4)
    first=[p for p in pairs if p[0]-pairs[0][0]<=span]
    last=[p for p in pairs if pairs[-1][0]-p[0]<=span]
    if len(first)<3 or len(last)<3:return {'status':'insufficient','reason':'前後の同時位置が不足','paired_samples':len(pairs)}
    moves=[statistics.median(p[i] for p in last)-statistics.median(p[i] for p in first) for i in (2,4)]
    if min(abs(v) for v in moves)<.5 or moves[0]*moves[1]<=0:
        return {'status':'insufficient','reason':'両者の進行方向が不明瞭','paired_samples':len(pairs)}
    heading=1 if moves[0]>0 else -1
    before=statistics.median(heading*(p[2]-p[4]) for p in first)
    after=statistics.median(heading*(p[2]-p[4]) for p in last)
    if before<-.15 and after>.15:passer=target
    elif before>.15 and after<-.15:passer=reference
    else:return {'status':'insufficient','reason':'前後の順序逆転が明瞭でない','paired_samples':len(pairs),
                 'relative_along_start_m':round(before,3),'relative_along_end_m':round(after,3)}
    near=[p for p in pairs if abs(p[2]-p[4])<=.45]
    if len(near)<5 or near[-1][0]-near[0][0]<.15:
        return {'status':'insufficient','reason':'並走付近の同時位置が不足','paired_samples':len(pairs)}
    # Right in corridor Y is -heading*det(X,Y,Z), from heading × up.
    right_sign=-heading*(1 if basis_determinant>0 else -1)
    sides=[right_sign*(p[3]-p[5])*(1 if passer==target else -1) for p in near]
    side=statistics.median(sides)
    if abs(side)<.20 or sum(x*side>0 for x in sides)/len(sides)<.75:
        return {'status':'insufficient','reason':'追い越し時の左右差が不明瞭','paired_samples':len(pairs)}
    actual='右' if side>0 else '左'
    return {'status':'consistent' if actual==planned_side else 'conflict',
            'reason':'計画と同じ側に見える' if actual==planned_side else '計画と逆側に見える・要目視確認',
            'estimated_overtaker_track_id':passer,'estimated_side':actual,'planned_side':planned_side,
            'paired_samples':len(pairs),'near_samples':len(near),'near_start_s':near[0][0],
            'near_end_s':near[-1][0],'near_frame':min(near,key=lambda p:abs(p[2]-p[4]))[1],
            'median_right_offset_m':round(side,3),'relative_along_start_m':round(before,3),
            'relative_along_end_m':round(after,3),'heading_x_sign':heading,'basis_determinant':round(basis_determinant,6)}


def calibration(group,recording):
    if group in (2,3):
        inv=Path('/data/experiment_data/kaiseki1103/exchange/depth_group002_003_inventory_20261105_01.csv')
        with inv.open(encoding='utf-8-sig',newline='') as f:
            rows=[r for r in csv.DictReader(f) if r['group']==str(group) and r['recording']==recording]
        if len(rows)!=1:raise ValueError('calibration inventory mapping not unique')
        path=Path(rows[0]['calibration'])
        if digest(path)!=rows[0]['calibration_sha256']:raise ValueError('calibration hash mismatch')
    elif group in (4,5):
        path=ROOT/'group004_005_coordinate_audit_20261106_01/base_calibration.json'
    else:
        path=Path('/data/experiment_data/kaiseki1103/exchange/calibration_review_metadata_20261107_131230_e63f2ed2')/f'g{group:03d}_calibration_depth_20261107_01/zed_corridor_candidate.json'
    b=read(path)['corridor_basis_camera_image']
    x,y,z=[b[k] for k in ('X_into_hallway','Y_positive_toward_ZED_visible_far_wall','Z_up')]
    det=(x[0]*(y[1]*z[2]-y[2]*z[1])-x[1]*(y[0]*z[2]-y[2]*z[0])+x[2]*(y[0]*z[1]-y[1]*z[0]))
    if not math.isfinite(det):raise ValueError('invalid basis')
    return det,digest(path)


def run(output):
    if output.exists():raise FileExistsError(output)
    plan=read(PLAN); workbook_hash=digest(WORKBOOK)
    if workbook_hash!=plan['source_workbooks']['completed_plan']['sha256']:
        raise ValueError('experiment workbook differs from this trial plan')
    progress={};progress_hashes={}
    for group in range(2,10):
        paths=list(PROGRESS.glob(f'g{group:02d}_plan_*.json'))
        if len(paths)==1:
            progress[group]=read(paths[0]);progress_hashes[str(group)]=digest(paths[0])
    audit=read(AUDIT); summary=read(CANDIDATES); aud={r['tag']:r for r in audit['records']}
    rows=[]; failures=[]; exclusions=load_exclusions()
    for r in summary['records']:
        if excluded(r,exclusions):continue
        try:
            a=aud[r['tag']]
            if a['filtered_positions_sha256']!=r['source_positions_sha256']:raise ValueError('audit/source hash differs')
            trial,basis=safe_trial(plan,progress,r['group'],r['recording'])
            if (trial['global_trial_number'] if trial else None)!=a['trial'] or (trial['condition_id'] if trial else None)!=a['condition_id']:
                raise ValueError('current plan/progress differs from audit')
            entry={'group':r['group'],'recording':r['recording'],'tag':r['tag'],'trial':a['trial'],
                   'condition_id':a['condition_id'],'condition_basis':basis,'candidate_status':r['status'],
                   'candidate_page':r.get('candidate_path'),'source_positions_sha256':r['source_positions_sha256']}
            if trial is None:result={'status':'plan_unknown','reason':'録画と実施条件の対応が未確認'}
            elif trial['condition_category']!='追い越し':result={'status':'not_overtaking','reason':'計画上は単独歩行'}
            elif r['status']!='candidate':result={'status':'no_candidate','reason':'比較するID再割当て候補がない'}
            else:
                folder=Path(r['candidate_path']).parent; src=candidate_root(r['group'])/r['tag']
                original,_=packet(src); candidate=read(folder/'positions.json')
                if digest(src/'positions.json')!=r['source_positions_sha256'] or digest(folder/'positions.json')!=r['candidate_positions_sha256']:
                    raise ValueError('candidate/source hash mismatch')
                if validate_candidate(original,candidate,r['source_positions_sha256'])!=r['proposed_count']:
                    raise ValueError('candidate validation failed')
                det,cal_hash=calibration(r['group'],r['recording'])
                result=assess(candidate['frames'],r['target_id'],r['reference_id'],trial['overtaking_direction'],det)
                entry.update(candidate_positions_sha256=r['candidate_positions_sha256'],calibration_sha256=cal_hash,
                             planned_side=trial['overtaking_direction'],planned_overtaker=trial['overtaker'],
                             planned_overtaken=trial['overtaken_person'])
            entry.update(result);rows.append(entry)
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            failures.append({'tag':r['tag'],'reason':str(exc)})
    output.mkdir(parents=True)
    data={'at':datetime.now().astimezone().isoformat(timespec='seconds'),'audit_at':audit['at'],
          'candidate_summary_at':summary['at'],'workbook_sha256':workbook_hash,'plan_sha256':digest(PLAN),
          'progress_sha256':progress_hashes,'exclusion_registry_sha256':digest(REGISTRY),
          'excluded':list(exclusions.values()),
          'method_sha256':digest(Path(__file__)),'records':rows,'failures':failures,
          'limits':['planned side and role are instructions, not verified truth','surface points are not body centers',
                    'agreement does not prove identity, conflict is not proof of error','thresholds are unvalidated']}
    (output/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    labels={'consistent':'計画と同じ側に見える','conflict':'計画と逆側・要確認','insufficient':'観測不足','plan_unknown':'条件保留','not_overtaking':'単独歩行予定','no_candidate':'ID候補なし'}
    rows.sort(key=lambda r:({'conflict':0,'consistent':1,'insufficient':2,'no_candidate':3,'not_overtaking':4,'plan_unknown':5}[r['status']],r['group'],r['recording']))
    lines=[]
    for r in rows:
        link='—'
        if r['candidate_page']:
            path=html.escape(os.path.relpath(r['candidate_page'],output),quote=True)
            link=f'<a href="{path}">ID候補再生</a>'
            if r.get('near_frame') is not None:link+=f' / <a href="{path}#frame={r["near_frame"]}">並走付近</a>'
        vals=[f'G{r["group"]:03d} {r["recording"]}',str(r['trial'] or '保留'),str(r['condition_id'] or '保留'),
              str(r.get('planned_side','—')),str(r.get('estimated_side','—')),
              ('ID '+str(r['estimated_overtaker_track_id'])) if r.get('estimated_overtaker_track_id') is not None else '—',
              labels[r['status']],r['reason']]
        lines.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'<td>'+link+'</td></tr>')
    counts=Counter(r['status'] for r in rows)
    page='<!doctype html><html lang="ja"><meta charset="utf-8"><title>追い越し方向とID候補</title><style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:5px}</style><h1>追い越し方向とID候補の照合</h1><p>計画は指示であり実施内容の正解ではありません。一致はIDの正しさを保証せず、不一致も必ずしもID誤りではありません。観測点は身体中心でなく可視表面。画面外・遮蔽・ID入替え・深度誤差があり、目視で確認してください。被験者IDは確定していません。</p><p>前後の順序逆転・両者の進行・並走時の左右差を利用。左右は歩行方向と校正軸の向きから変換します。閾値は開発用で未検証です。候補と元データは変更していません。実験者指定の録画は解析から除外しています。</p><p>結果: '+html.escape(str(dict(counts)))+' / エラー '+str(len(failures))+' / <a href="review.json">根拠</a></p><table><tr><th>録画</th><th>試行候補</th><th>条件候補</th><th>計画の側</th><th>推定された側</th><th>追い越すID候補</th><th>判定</th><th>理由</th><th>再生</th></tr>'+''.join(lines)+'</table></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'records':len(rows),'counts':dict(counts),'failures':failures},ensure_ascii=False),flush=True)
    return failures


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=OUTPUT);a=p.parse_args()
    return 1 if run(a.output) else 0


if __name__=='__main__':raise SystemExit(main())
