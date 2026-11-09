"""Generate explicitly unverified 10 m ID proposals where one anchor pair is eligible."""
import argparse
import collections
import copy
from datetime import datetime
import html
import json
from pathlib import Path

from corridor_tracking.audit_depth_tracking import digest, make_replay, packet, snapshot_images
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.reassign_depth_identity_temporal import propose_backwards

ROOT = Path('/data/experiment_data/kaiseki1103/exchange')
AUDIT = Path('results/tracking_v2/trusted10_quality_live_20261107_01/audit.json')
INPUT = ROOT/'depth_group002_005_trusted10_20261106_01/originals'
OUTPUT = Path('results/tracking_v2/identity_proposals_10m_group004_005_20261107_01')


def evaluate(frames):
    counts=collections.Counter(o['track_id'] for f in frames for o in f['observations']
                               if o['track_id'] is not None and o.get('surface_corridor_m') is not None)
    ids=sorted(k for k,v in counts.items() if v>=10)
    options=[]
    for target in ids:
        for reference in ids:
            if target==reference:continue
            try:
                changed,assignments,diagnostics=propose_backwards(frames,target,reference)
                if len(assignments)>=5:options.append((target,reference,changed,assignments,diagnostics))
            except ValueError:
                continue
    return options,dict(counts)


def generate(audit_path, source_root, output):
    if output.exists():raise FileExistsError(output)
    audit=json.loads(audit_path.read_text(encoding='utf-8-sig'))
    output.mkdir(parents=True); candidates=[]; skipped=[]
    entries=[r for r in audit['records'] if r['group'] in (4,5) and r['condition_category']=='追い越し']
    for row in entries:
        tag=row['tag'];src=source_root/tag
        try:
            original,manifest=packet(src)
            source_hash=digest(src/'positions.json')
            if source_hash!=row['filtered_positions_sha256'] or digest(src/'manifest.json')!=row['filtered_manifest_sha256']:
                raise ValueError('source differs from reviewed 10 m dataset')
            options,counts=evaluate(original['frames'])
            if len(options)!=1:
                skipped.append({'tag':tag,'reason':'no eligible pair' if not options else 'multiple possible anchor pairs',
                                'eligible_pairs':len(options),'positioned_observations_per_id':counts})
                continue
            target,reference,frames,assignments,diagnostics=options[0]
            proposal=copy.deepcopy(original);proposal['frames']=frames
            proposal['reassignment_candidate']={'status':'proposed_not_verified','source_positions_sha256':source_hash,
                'target_id':target,'reference_id':reference,'condition_id':row['condition_id'],
                'basis':'automatically selected anchor pair; no visual verification',
                'warning':'development hypothesis only; never treat as a validated person or subject ID'}
            if validate_candidate(original,proposal,source_hash)!=len(assignments):raise ValueError('candidate change validation failed')
            dest=output/tag;dest.mkdir()
            (dest/'positions.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            (dest/'assignments.json').write_text(json.dumps({'assignments':assignments,'diagnostics':diagnostics,
                'positioned_observations_per_id':counts},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            events=[{'kind':'anchor','frame':diagnostics['anchor_frame'],'end_frame':diagnostics['anchor_frame'],
                     'time_s':diagnostics['anchor_elapsed_s'],'end_time_s':diagnostics['anchor_elapsed_s'],
                     'detail':f'自動選択した暫定基点 ID {target}。人物との対応は未確認'}]
            for change in (assignments[0],assignments[-1]):
                events.append({'kind':'candidate','frame':change['frame_index'],'end_frame':change['frame_index'],
                    'time_s':change['elapsed_s'],'end_time_s':change['elapsed_s'],'detail':f'ID {target} への未確認候補'})
            body=ROOT/'group004_20261105_body_01'/row['recording']/'body' if row['group']==4 else None
            images=snapshot_images(body,original)
            view={'frames':frames,'walls':original['walls'],'reassignment_candidate':True}
            page=make_replay(view,f"G{row['group']:03d} {row['recording']} 未確認ID候補",events,dest,images)
            page=page.replace('<label>時刻','<p><strong>基点も含めて自動選択で、人物や画像による確認はありません。白縁は仮割当てです。実際のIDとして使わず、元の画像と照合してください。</strong></p><label>時刻',1)
            (dest/'index.html').write_text(page,encoding='utf-8')
            output_manifest={'status':'proposed_not_verified','group':row['group'],'recording':row['recording'],
                'source_positions_sha256':source_hash,'source_manifest_sha256':digest(src/'manifest.json'),
                'positions_sha256':digest(dest/'positions.json'),'assignments_sha256':digest(dest/'assignments.json'),
                'report_sha256':digest(dest/'index.html'),'algorithm_sha256':digest(Path(__file__)),
                'method_sha256':digest(Path('corridor_tracking/reassign_depth_identity_temporal.py')),
                'anchor_status':'automatically_selected_not_visually_verified','proposed_observations':len(assignments)}
            (dest/'manifest.json').write_text(json.dumps(output_manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            candidates.append({'tag':tag,'group':row['group'],'recording':row['recording'],'target_id':target,
                'reference_id':reference,'proposed_count':len(assignments),'anchor_time_s':diagnostics['anchor_elapsed_s'],
                'first_time_s':assignments[0]['elapsed_s'],'last_time_s':assignments[-1]['elapsed_s'],
                'anchor_status':'automatic_not_visually_verified','source_positions_sha256':source_hash})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            skipped.append({'tag':tag,'reason':str(exc)})
    result={'generated_at':datetime.now().astimezone().isoformat(timespec='seconds'),
            'audit_sha256':digest(audit_path),'candidates':candidates,'skipped':skipped,
            'limits':['automatic anchors not visually verified','not an accuracy improvement evaluation',
                      'conditions from plan, not observed fact','source 10 m data unchanged and no interpolation']}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows=[]
    for r in candidates:
        link=html.escape(r['tag'],quote=True)
        rows.append(f'<tr><td>G{r["group"]:03d} {html.escape(r["recording"])}</td><td>{r["target_id"]}</td><td>{r["reference_id"]}</td><td>{r["proposed_count"]}</td><td>{r["anchor_time_s"]:.2f}</td><td><a href="{link}/index.html">候補を再生</a></td></tr>')
    page=('<!doctype html><html lang="ja"><meta charset="utf-8"><title>未確認ID候補</title><style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:6px}</style>'
          '<h1>10 m版のID再割当て候補（グループ４・５）</h1><p><strong>全て自動選択した未確認候補です。基点自体も人物・映像による確認をしていません。正解や精度向上とはみなさず、元画像と照合してください。</strong></p>'
          '<p>時間・距離・高さ・既存IDから競合のない候補を選びます。計画上２人の録画が対象です。位置の補間や原本の変更はありません。複数の基点ペアが成立した場合は出力しません。</p>'
          '<p>グループ４は一部の時刻に既存画像へのリンクがあります。グループ５は画像がWindows SSD内にあり、この一覧からは確認できません。</p>'
          f'<p>候補 {len(candidates)} 録画 / 候補なし・保留 {len(skipped)} 録画。<a href="summary.json">基点と処理記録</a></p><table><tr><th>録画</th><th>割当て先ID</th><th>参照ID</th><th>候補観測数</th><th>基点時刻</th><th>確認</th></tr>'+''.join(rows)+'</table></html>')
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'candidate_recordings':len(candidates),'skipped_recordings':len(skipped),
        'candidates_by_group':dict(collections.Counter(c['group'] for c in candidates))},ensure_ascii=False),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit',type=Path,default=AUDIT)
    p.add_argument('--source-root',type=Path,default=INPUT);p.add_argument('--output',type=Path,default=OUTPUT)
    a=p.parse_args();generate(a.audit,a.source_root,a.output)


if __name__=='__main__':main()
