"""Expose all competing temporal ID hypotheses with planned-side evidence."""
import copy
import html
import json
import os
from pathlib import Path
import sys

from corridor_tracking.audit_depth_tracking import digest, make_replay, packet, read, snapshot_images
from corridor_tracking.audit_trusted10_live import PLAN, PROGRESS, safe_trial
from corridor_tracking.overtaking_condition_review import assess, calibration
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.propose_trusted10_identities_live import candidate_root, image_root
from corridor_tracking.short_anchor_identity_v2 import evaluate
from corridor_tracking.analysis_exclusions import excluded, load_exclusions

ROOT=Path('results/tracking_v2')
SUMMARY=ROOT/'identity_short_anchor_v2_live_20261107_01/summary.json'
OUTPUT=ROOT/'overtaking_ambiguous_review_20261108_01'


def main():
    output=Path(sys.argv[1]) if len(sys.argv)>1 else OUTPUT
    if output.exists():raise FileExistsError(output)
    summary=read(SUMMARY);plan=read(PLAN);progress={}
    for g in range(2,10):
        files=list(PROGRESS.glob(f'g{g:02d}_plan_*.json'))
        if len(files)==1:progress[g]=read(files[0])
    output.mkdir(parents=True);results=[];exclusions=load_exclusions()
    for row in summary['records']:
        if excluded(row,exclusions):continue
        if row['status']!='ambiguous':continue
        source=candidate_root(row['group'])/row['tag'];original,_=packet(source)
        source_hash=digest(source/'positions.json')
        if source_hash!=row['source_positions_sha256']:raise ValueError('source changed')
        trial,_=safe_trial(plan,progress,row['group'],row['recording'])
        side=trial['overtaking_direction'] if trial and trial['condition_category']=='追い越し' else None
        det,cal_hash=calibration(row['group'],row['recording'])
        options,_=evaluate(original['frames'])
        if len(options)<2:raise ValueError('cached ambiguous status differs; rerun later')
        record={'tag':row['tag'],'group':row['group'],'recording':row['recording'],'planned_side':side,
                'condition_id':trial['condition_id'] if trial else None,'source_positions_sha256':source_hash,
                'calibration_sha256':cal_hash,'options':[]}
        for target,reference,frames,changes,diagnostics in options:
            dest=output/row['tag']/f'candidate_id{target}_reference{reference}';dest.mkdir(parents=True)
            proposal=copy.deepcopy(original);proposal['frames']=frames
            proposal['reassignment_candidate']={'status':'proposed_not_verified','source_positions_sha256':source_hash,
                'target_id':target,'reference_id':reference,'condition_id':record['condition_id'],
                'basis':'one of multiple competing temporal hypotheses; neither is selected',
                'warning':'planned direction is an instruction, not proof of identity'}
            if validate_candidate(original,proposal,source_hash)!=len(changes):raise ValueError('invalid candidate')
            result=assess(frames,target,reference,side,det)
            (dest/'positions.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            (dest/'assignments.json').write_text(json.dumps({'assignments':changes,'diagnostics':diagnostics,'condition_evidence':result},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            events=[]
            if 'near_frame' in result:
                t=result['near_start_s'];events=[{'frame':result['near_frame'],'end_frame':result['near_frame'],
                    'time_s':t,'end_time_s':result['near_end_s'],'detail':'並走付近・計画との左右比較'}]
            images=snapshot_images(image_root(row),original)
            view={'frames':frames,'walls':original['walls'],'reassignment_candidate':True}
            page=make_replay(view,f"{row['tag']} 競合する未確認候補 ID {target}",events,dest,images)
            page=page.replace('<label>時刻','<p><strong>複数候補があり未決定です。計画方向との一致だけでは選択できません。</strong></p><label>時刻',1)
            (dest/'index.html').write_text(page,encoding='utf-8')
            record['options'].append({'target':target,'reference':reference,'proposed_observations':len(changes),
                'assessment':result,'page':str(dest/'index.html'),'positions_sha256':digest(dest/'positions.json'),
                'assignments_sha256':digest(dest/'assignments.json')})
        results.append(record)
    (output/'review.json').write_text(json.dumps({'source_summary_at':summary['at'],'records':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    parts=[]
    for r in results:
        parts.append(f'<h2>G{r["group"]:03d} {html.escape(r["recording"])}：計画 {html.escape(str(r["planned_side"]))}</h2><ul>')
        for o in r['options']:
            url=html.escape(os.path.relpath(o['page'],output),quote=True);a=o['assessment']
            parts.append(f'<li><a href="{url}">ID {o["target"]} / 参照ID {o["reference"]}：{o["proposed_observations"]}観測</a> — {html.escape(a["reason"])}</li>')
        parts.append('</ul>')
    (output/'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>競合するID候補</title><h1>競合するID候補の比較</h1><p>どの候補も未確定です。条件に一致する候補が一つでも、他候補が観測不足なら除外できません。計画と映像の両方を確認してください。原本は変更していません。</p>'+''.join(parts)+'<p><a href="review.json">判定根拠・入力ハッシュ</a></p></html>',encoding='utf-8')
    print(json.dumps({'recordings':len(results),'options':sum(len(r['options']) for r in results)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
