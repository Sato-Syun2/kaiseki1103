"""Screen all shared trusted-10m recordings for unverified identity hypotheses."""
import argparse
import collections
import copy
from datetime import datetime
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import time
import uuid

from corridor_tracking.audit_depth_tracking import digest, make_replay, packet, read, snapshot_images
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.propose_trusted10_identities import evaluate
from corridor_tracking.analysis_exclusions import REGISTRY, excluded, load_exclusions

ROOT=Path('/data/experiment_data/kaiseki1103/exchange')
AUDIT=Path('results/tracking_v2/trusted10_quality_live_20261107_01/audit.json')
OUTPUT=Path('results/tracking_v2/identity_proposals_10m_all_live_20261107_01')
PREVIOUS=Path('results/tracking_v2/identity_proposals_10m_group004_005_20261107_01')
METHOD=Path('corridor_tracking/reassign_depth_identity_temporal.py')
EVALUATOR=Path('corridor_tracking/propose_trusted10_identities.py')


def atomic(path,text):
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(text,encoding='utf-8');os.replace(tmp,path)


def candidate_root(group):
    return ROOT/('depth_group002_005_trusted10_20261106_01' if group<=5 else 'depth_group006_009_trusted10_20261107_01')/'originals'


def image_root(row):
    if row['group']==4:return ROOT/'group004_20261105_body_01'/row['recording']/'body'
    if row['group'] in (2,3):
        import csv
        with (ROOT/'depth_group002_003_inventory_20261105_01.csv').open(newline='',encoding='utf-8-sig') as f:
            found=[r for r in csv.DictReader(f) if r['group']==str(row['group']) and r['recording']==row['recording']]
        if len(found)==1:return Path(found[0]['body_dir'])
    return None


def prior_candidate(row, original, source_hash):
    if row['group'] not in (4,5):return None
    folder=PREVIOUS/row['tag']
    if not (folder/'manifest.json').is_file():return None
    manifest=read(folder/'manifest.json');proposal=read(folder/'positions.json')
    if (manifest.get('status')!='proposed_not_verified' or manifest.get('source_positions_sha256')!=source_hash or
        manifest.get('positions_sha256')!=digest(folder/'positions.json') or
        manifest.get('assignments_sha256')!=digest(folder/'assignments.json') or
        manifest.get('report_sha256')!=digest(folder/'index.html')):
        raise ValueError('existing candidate differs; preserve for review')
    count=validate_candidate(original,proposal,source_hash)
    if count!=manifest['proposed_observations']:raise ValueError('existing candidate count mismatch')
    meta=proposal['reassignment_candidate']
    if row['condition_category']!='追い越し' or meta.get('condition_id')!=row['condition_id']:
        return None
    return {'status':'candidate','candidate_path':str(folder/'index.html'),'candidate_page_sha256':digest(folder/'index.html'),
            'candidate_positions_sha256':digest(folder/'positions.json'), 'candidate_assignments_sha256':digest(folder/'assignments.json'),
            'candidate_manifest_sha256':digest(folder/'manifest.json'),
            'target_id':meta['target_id'],'reference_id':meta['reference_id'],'proposed_count':count,'reused':True}


def process(row, output=OUTPUT):
    tag=row['tag'];source=candidate_root(row['group'])/tag
    original,manifest=packet(source);source_hash=digest(source/'positions.json')
    if (source_hash!=row['filtered_positions_sha256'] or digest(source/'manifest.json')!=row['filtered_manifest_sha256'] or
        original['metadata']['group']!=row['group'] or original['metadata']['recording']!=row['recording'] or
        manifest['bounds'].get('max_x_m')!=10.):
        raise ValueError('trusted 10 m data or provenance mismatch')
    result={'tag':tag,'group':row['group'],'recording':row['recording'],'source_label':row['source_label'],
            'source_positions_sha256':source_hash,'source_manifest_sha256':digest(source/'manifest.json'),
            'condition_id':row['condition_id'],'condition_category':row['condition_category'],
            'condition_basis':row['condition_basis'],'anchor_status':'automatic_not_visually_verified'}
    if row['condition_category']=='単独歩行':
        result.update(status='planned_single_walker',reason='計画上は単独歩行。２人を仮定した再割当ては保留。')
        return result
    previous=prior_candidate(row,original,source_hash)
    if previous:
        result.update(previous);return result
    options,counts=evaluate(original['frames'])
    if len(options)!=1:
        result.update(status='no_candidate' if not options else 'ambiguous',eligible_pairs=len(options),
                      reason='基準を満たすIDの組がない' if not options else '複数のIDの組が成立するため保留',
                      positioned_observations_per_id=counts)
        return result
    target,reference,frames,assignments,diagnostics=options[0]
    proposal=copy.deepcopy(original);proposal['frames']=frames
    proposal['reassignment_candidate']={'status':'proposed_not_verified','source_positions_sha256':source_hash,
        'target_id':target,'reference_id':reference,'condition_id':row['condition_id'],
        'basis':'automatically selected anchor, no image verification; no actual condition or subject identity asserted',
        'warning':'development hypothesis only; never treat as a validated person or subject ID'}
    if validate_candidate(original,proposal,source_hash)!=len(assignments):raise ValueError('candidate validation failed')
    key=hashlib.sha256((source_hash+digest(METHOD)+digest(EVALUATOR)+str(target)+':'+str(reference)).encode()).hexdigest()[:16]
    records=output/'candidates';records.mkdir(parents=True,exist_ok=True)
    dest=records/(tag+'_'+key)
    assignment_data={'assignments':assignments,'diagnostics':diagnostics,
                     'positioned_observations_per_id':{str(k):v for k,v in counts.items()}}
    if dest.exists():
        existing=read(dest/'manifest.json');saved=read(dest/'positions.json');saved_assignments=read(dest/'assignments.json')
        if (existing['source_positions_sha256']!=source_hash or existing['positions_sha256']!=digest(dest/'positions.json') or
            existing['assignments_sha256']!=digest(dest/'assignments.json') or existing['report_sha256']!=digest(dest/'index.html') or
            validate_candidate(original,saved,source_hash)!=len(assignments) or saved!=proposal or saved_assignments!=assignment_data):
            raise ValueError('existing candidate conflicts; preserve files')
    else:
        temp=records/('.partial-'+uuid.uuid4().hex);temp.mkdir()
        (temp/'positions.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        (temp/'assignments.json').write_text(json.dumps(assignment_data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        events=[{'kind':'anchor','frame':diagnostics['anchor_frame'],'end_frame':diagnostics['anchor_frame'],
                 'time_s':diagnostics['anchor_elapsed_s'],'end_time_s':diagnostics['anchor_elapsed_s'],
                 'detail':f'自動選択した暫定基点 ID {target}。人物との対応は未確認'}]
        for change in (assignments[0],assignments[-1]):
            events.append({'kind':'candidate','frame':change['frame_index'],'end_frame':change['frame_index'],
                'time_s':change['elapsed_s'],'end_time_s':change['elapsed_s'],'detail':f'ID {target} への未確認候補'})
        images=snapshot_images(image_root(row),original)
        view={'frames':frames,'walls':original['walls'],'reassignment_candidate':True}
        page=make_replay(view,f"G{row['group']:03d} {row['recording']} 未確認ID候補",events,dest,images)
        notice='<p><strong>基点と候補は自動選択であり、画像・人物との照合前です。実際のIDとみなさず、元画像で確認してください。</strong>'
        if row['condition_category'] is None:
            notice+=' この録画の実験条件は保留中で、２つのIDが２人を示すことも確認されていません。'
        page=page.replace('<label>時刻',notice+'</p><label>時刻',1)
        (temp/'index.html').write_text(page,encoding='utf-8')
        info={'status':'proposed_not_verified','group':row['group'],'recording':row['recording'],
              'source_positions_sha256':source_hash,'source_manifest_sha256':digest(source/'manifest.json'),
              'positions_sha256':digest(temp/'positions.json'),'assignments_sha256':digest(temp/'assignments.json'),
              'report_sha256':digest(temp/'index.html'),'algorithm_sha256':digest(Path(__file__)),
              'evaluator_sha256':digest(EVALUATOR),'method_sha256':digest(METHOD),
              'anchor_status':'automatically_selected_not_visually_verified','proposed_observations':len(assignments)}
        (temp/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temp.rename(dest)
    result.update(status='candidate',candidate_path=str(dest/'index.html'),candidate_page_sha256=digest(dest/'index.html'),
                  candidate_positions_sha256=digest(dest/'positions.json'),candidate_assignments_sha256=digest(dest/'assignments.json'),
                  candidate_manifest_sha256=digest(dest/'manifest.json'),
                  target_id=target,reference_id=reference,proposed_count=len(assignments),reused=False,
                  anchor_elapsed_s=diagnostics['anchor_elapsed_s'])
    return result


def scan(output=OUTPUT, audit_path=AUDIT):
    audit=read(audit_path);output.mkdir(parents=True,exist_ok=True)
    states=output/'states';states.mkdir(exist_ok=True)
    records=[];failures=[];exclusions=load_exclusions()
    for row in audit['records']:
        if excluded(row,exclusions):continue
        tag=row['tag'];path=states/(tag+'.json')
        key={'source_sha256':row['filtered_positions_sha256'],'manifest_sha256':row['filtered_manifest_sha256'],
             'condition_id':row['condition_id'],'condition_category':row['condition_category'],
             'condition_basis':row['condition_basis'],'algorithm_sha256':digest(Path(__file__)),
             'evaluator_sha256':digest(EVALUATOR),'method_sha256':digest(METHOD)}
        try:
            source=candidate_root(row['group'])/tag
            if (digest(source/'positions.json')!=key['source_sha256'] or digest(source/'manifest.json')!=key['manifest_sha256']):
                raise ValueError('source changed since tracking audit; waiting for an updated audit')
            old=read(path) if path.is_file() else None
            previous=old.get('result') if old and old.get('key')==key else None
            candidate_ok=False
            if previous and previous['status']=='candidate':
                folder=Path(previous['candidate_path']).parent
                candidate_ok=all((folder/name).is_file() and digest(folder/name)==previous.get(key_name)
                    for name,key_name in (('index.html','candidate_page_sha256'),('positions.json','candidate_positions_sha256'),
                                          ('assignments.json','candidate_assignments_sha256'),('manifest.json','candidate_manifest_sha256')))
            if previous and (previous['status']!='candidate' or candidate_ok):
                result=previous
            else:
                result=process(row,output)
                atomic(path,json.dumps({'key':key,'result':result},ensure_ascii=False,indent=2)+'\n')
            records.append(result)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            failures.append({'tag':tag,'reason':str(exc)})
    records.sort(key=lambda r:(r['group'],r['recording']))
    summary={'at':datetime.now().astimezone().isoformat(timespec='seconds'),'source_audit_at':audit['at'],
             'records':records,'failures':failures,'audit_pending':audit['pending'],'audit_failures':audit['failures'],
             'excluded':audit.get('excluded',[]),'exclusion_registry_sha256':digest(REGISTRY),
             'limits':['anchors not visually checked','no identity or accuracy claim','conditions may be unknown',
                       'original 10 m observations are not modified']}
    atomic(output/'summary.json',json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    labels={'candidate':'候補あり','planned_single_walker':'単独歩行予定・保留','no_candidate':'候補なし','ambiguous':'複数組・保留'}
    for r in records:
        if r['status']=='candidate':
            href=html.escape(os.path.relpath(r['candidate_path'],output).replace(os.sep,'/'),quote=True)
            detail=f'<a href="{href}">候補を確認</a>（{r["proposed_count"]}観測）'
        else:detail=html.escape(r.get('reason',''))
        tag=html.escape(r['tag'],quote=True)
        audit_link=html.escape(os.path.relpath(AUDIT.parent/'replay'/(r['tag']+'.html'),output).replace(os.sep,'/'),quote=True)
        condition=html.escape(str(r['condition_id'] or '保留'))
        rows.append(f'<tr><td>G{r["group"]:03d} {html.escape(r["recording"])}</td><td>{html.escape(str(r["source_label"]))}</td><td>{condition}</td><td>{labels[r["status"]]}</td><td>{detail}</td><td><a href="{audit_link}">10 m版</a></td></tr>')
    failures_html=''.join(f'<li>{html.escape(x["tag"])}: {html.escape(x["reason"])}</li>' for x in failures) or '<li>なし</li>'
    counts=collections.Counter(r['status'] for r in records)
    page=('<!doctype html><html lang="ja"><meta charset="utf-8"><title>10 m ID候補</title><style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:6px}</style>'
          '<h1>共有済み録画の10 m版 ID候補</h1><p><strong>全て基点も自動選択で画像・人物との対応は未確認です。被験者番号や正解ではありません。必ず元画像と照合してください。</strong></p>'
          '<p>２つの暫定IDをもとに、時間・位置・高さの条件を満たす未確定の点だけを候補にします。複数の組が成立する場合は保留します。実験条件が不明な録画でも候補を検討しますが、２つのIDが２人を示すとは限りません。</p>'
          '<p>原本の座標とIDを変更せず、欠測を補間しません。計画上の単独歩行は２人の割当てを保留します。グループ５以降の画像はWindows SSDにあります。</p>'
          f'<p>更新 {html.escape(summary["at"])} / 対象 {len(records)}録画 / 候補 {counts["candidate"]}録画 / 解析対象外 {len(summary["excluded"])}録画 / エラー {len(failures)}。<a href="summary.json">詳細</a></p>'
          '<table><tr><th>録画</th><th>元録画名</th><th>計画条件</th><th>状態</th><th>候補</th><th>追跡確認</th></tr>'+''.join(rows)+'</table><h2>エラー</h2><ul>'+failures_html+'</ul></html>')
    atomic(output/'index.html',page)
    print(json.dumps({'at':summary['at'],'records':len(records),'statuses':dict(counts),'failures':failures},ensure_ascii=False),flush=True)
    return failures


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=120)
    a=p.parse_args()
    if a.interval<30:p.error('interval must be at least 30 seconds')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with (OUTPUT/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('identity candidate watcher already running')
        while True:
            failures=scan()
            if not a.watch:return 1 if failures else 0
            time.sleep(a.interval)


if __name__=='__main__':raise SystemExit(main())
