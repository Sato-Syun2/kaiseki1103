"""Review shared trusted-10m trajectories, including newly arriving recordings."""
import argparse
import collections
import csv
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import time

from corridor_tracking.audit_depth_tracking import digest, make_replay, matched_trial, metrics, packet, read, snapshot_images
from corridor_tracking.spatial_filter import filter_frames
from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs, withhold_isolated_excursions
from corridor_tracking.analysis_exclusions import REGISTRY, load_exclusions

SHARE = Path('/data/experiment_data/kaiseki1103/exchange')
PROGRESS = Path('/data/experiment_data/recordings/.experiment_progress')
PLAN = Path('experiment_metadata/run_order_20261103.json')
OUTPUT = Path('results/tracking_v2/trusted10_quality_live_20261107_01')
TAG = re.compile(r'^g(00[2-9])_(recording_\d{3})_[A-Za-z0-9_]+$')


def safe_trial(plan, progress, group, recording):
    if group == 6 or (group == 7 and recording in ('recording_901','recording_902')):
        return None, '録画・試行の対応は例外として保留'
    p = progress.get(group)
    if p is None:
        return None, '録画進捗がないため条件を保留'
    try:
        t = matched_trial(plan, p, group, recording)
        if (group == 7 and t['global_trial_number'] >= 55) or (group == 9 and t['global_trial_number'] == 9):
            return None, '申告された録画・実施条件の例外により保留'
        return t, '録画進捗と計画による候補。実際の実施条件は未検証'
    except (KeyError, ValueError, TypeError) as exc:
        return None, f'録画と試行の対応を保留: {exc}'


def check_record(raw_path, derived_path, plan, progress):
    match=TAG.fullmatch(raw_path.name)
    if not match:raise ValueError('unexpected raw tag')
    group=int(match[1]);recording=match[2]
    original,rm=packet(raw_path); filtered,fm=packet(derived_path)
    if (fm.get('source_positions_sha256') != digest(raw_path/'positions.json') or
            fm.get('source_manifest_sha256') != digest(raw_path/'manifest.json') or
            filtered['metadata'] != original['metadata'] or
            int(original['metadata']['group']) != group or original['metadata']['recording'] != recording):
        raise ValueError('source or metadata hash mismatch')
    bounds=fm['bounds']
    if bounds.get('max_x_m') != 10.:
        raise ValueError('not the trusted 10 m range')
    in_bounds,_,counts=filter_frames(original['frames'],bounds)
    isolated,spikes=withhold_isolated_excursions(in_bounds)
    replayed,jumps,pair_count=withhold_discontinuous_pairs(isolated)
    if replayed != filtered['frames']:
        raise ValueError('screened positions differ from declared source and algorithm')
    trial,basis=safe_trial(plan,progress,group,recording)
    expected=None if trial is None else (2 if trial['condition_category']=='追い越し' else 1)
    stats=metrics(filtered['frames'],expected or 0)
    for f in stats['flags']:f['label']=f['label'].replace('確定ID','暫定ID')
    for event in stats['events']:event['detail']=event['detail'].replace('確定ID','暫定ID')
    before=metrics(in_bounds,expected or 0)
    if spikes or jumps:
        stats['flags'].append({'level':'review','code':'withheld_motion','label':'位置の急変を保留。元データを確認'})
        if stats['rank']=='低':stats['rank']='確認'
        for event in jumps[:3]:
            stats['events'].append({'kind':'withheld_jump','frame':event['right_frame'],'end_frame':event['right_frame'],
                                    'time_s':event['right_time_s'],'end_time_s':event['right_time_s'],
                                    'detail':f"ID {event['track_id']} の急変前後を保留"})
        for event in spikes[:3]:
            stats['events'].append({'kind':'withheld_isolated','frame':event['frame_index'],'end_frame':event['frame_index'],
                                    'time_s':event['elapsed_s'],'end_time_s':event['elapsed_s'],
                                    'detail':f"ID {event['track_id']} の孤立した飛びを保留"})
    stats['events'].sort(key=lambda e:e['time_s'])
    record={'tag':raw_path.name,'group':group,'recording':recording,
        'source_label':original['metadata'].get('source_label',recording),'condition_basis':basis,
        'trial':trial['global_trial_number'] if trial else None,'condition_id':trial['condition_id'] if trial else None,
        'condition_category':trial['condition_category'] if trial else None,
        'raw_positions_sha256':digest(raw_path/'positions.json'),'raw_manifest_sha256':digest(raw_path/'manifest.json'),
        'filtered_positions_sha256':digest(derived_path/'positions.json'),'filtered_manifest_sha256':digest(derived_path/'manifest.json'),
        'outside_counts':counts,'withheld_isolated':len(spikes),'withheld_discontinuous_points':pair_count,
        'jump_before':before['jump_count'],'jump_after':stats['jump_count'],'stats':stats}
    return record,original,filtered


def atomic_text(path, text):
    temporary=path.with_name('.'+path.name+'.tmp')
    temporary.write_text(text,encoding='utf-8');os.replace(temporary,path)


def scan(output=OUTPUT):
    plan=read(PLAN);progress={}
    for group in range(2,10):
        matches=list(PROGRESS.glob(f'g{group:02d}_plan_*.json'))
        if len(matches)==1:progress[group]=read(matches[0])
    datasets=[(SHARE/'depth_group002_003_coordinates_20261105_01',SHARE/'depth_group002_005_trusted10_20261106_01/originals',set('23')),
              (SHARE/'depth_group004_005_coordinates_20261106_01',SHARE/'depth_group002_005_trusted10_20261106_01/originals',set('45')),
              (SHARE/'depth_group006_009_coordinates_20261107_01',SHARE/'depth_group006_009_trusted10_20261107_01/originals',set('6789'))]
    inputs=[]
    for root,filtered,groups in datasets:
        if not root.is_dir():continue
        for p in sorted(root.iterdir()):
            m=TAG.fullmatch(p.name)
            if p.is_dir() and m and str(int(m[1])) in groups:inputs.append((p,filtered/p.name))
    keys=collections.Counter((TAG.fullmatch(p.name)[1],TAG.fullmatch(p.name)[2]) for p,_ in inputs)
    output.mkdir(parents=True,exist_ok=True);pages=output/'replay';pages.mkdir(exist_ok=True)
    cache=output/'records';cache.mkdir(exist_ok=True)
    records=[];pending=[];failures=[];excluded_records=[]
    exclusions=load_exclusions()
    for raw,filtered in inputs:
        m=TAG.fullmatch(raw.name)
        if keys[(m[1],m[2])]!=1:
            failures.append({'tag':raw.name,'reason':'同じ録画の結果が複数あり、確認が必要'});continue
        decision=exclusions.get((int(m[1]),m[2]))
        if decision:
            try:
                original,_=packet(raw)
                if original['metadata']['source_svo_sha256']!=decision['source_svo_sha256']:
                    raise ValueError('除外録画のSVOハッシュが記録と異なる。解析には含めず要確認')
                excluded_records.append({'tag':raw.name,**decision})
            except (OSError,ValueError,KeyError,TypeError) as exc:
                failures.append({'tag':raw.name,'reason':str(exc)})
            continue
        if not filtered.is_dir():
            pending.append({'tag':raw.name,'reason':'10 m版を待機中'});continue
        try:
            fingerprints={'raw':digest(raw/'positions.json'),'raw_manifest':digest(raw/'manifest.json'),
                          'filtered':digest(filtered/'positions.json'),'filtered_manifest':digest(filtered/'manifest.json'),
                          'plan':digest(PLAN),'progress':digest(next(PROGRESS.glob(f'g{int(m[1]):02d}_plan_*.json'))) if int(m[1]) in progress else None,
                          'script':digest(Path(__file__))}
            saved=cache/(raw.name+'.json');page=pages/(raw.name+'.html')
            old=read(saved) if saved.is_file() else None
            if old and old.get('fingerprints')==fingerprints and page.is_file():
                record=old['record']
            else:
                record,original,screened=check_record(raw,filtered,plan,progress)
                group=record['group'];rec=record['recording'];body=None
                if group in (2,3):
                    with (SHARE/'depth_group002_003_inventory_20261105_01.csv').open(newline='',encoding='utf-8-sig') as f:
                        row=next((r for r in csv.DictReader(f) if r['group']==str(group) and r['recording']==rec),None)
                    if row:body=Path(row['body_dir'])
                elif group==4:body=SHARE/'group004_20261105_body_01'/rec/'body'
                images=snapshot_images(body,original)
                bounds=read(filtered/'manifest.json')['bounds']
                view={'frames':screened['frames'],'walls':{'visible':bounds['visible_wall_y_m'],'opposite':bounds['opposite_wall_y_m']}}
                content=make_replay(view,f'グループ{group} {rec}（10 m版・暫定ID）',record['stats']['events'],pages,images)
                atomic_text(page,content)
                atomic_text(saved,json.dumps({'fingerprints':fingerprints,'record':record},ensure_ascii=False,indent=2)+'\n')
            records.append(record)
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            failures.append({'tag':raw.name,'reason':str(exc)})
    order={'優先':0,'確認':1,'低':2}
    records.sort(key=lambda r:(order.get(r['stats']['rank'],3),r['group'],r['recording']))
    atomic_text(output/'audit.json',json.dumps({'at':datetime.now().astimezone().isoformat(timespec='seconds'),
        'records':records,'pending':pending,'failures':failures,'excluded':excluded_records,'exclusion_registry_sha256':digest(REGISTRY),'limits':['rank is an unvalidated review priority, not an error rate',
        'IDs and conditions remain provisional','unobserved people and unknown-ID motion cannot be verified']},ensure_ascii=False,indent=2)+'\n')
    with (output/'recordings.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['group','recording','source_label','rank','trial','condition_id','condition_category','two_ids_fraction',
                'unassigned_positioned_fraction','withheld_isolated','withheld_discontinuous_points','jump_before','jump_after','flags','condition_basis']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in records:
            s=r['stats'];w.writerow({k:(s[k] if k in s else '; '.join(x['label'] for x in s['flags']) if k=='flags' else r.get(k,'')) for k in fields})
    rows=[]
    for r in records:
        s=r['stats'];tag=html.escape(r['tag'],quote=True)
        flags='、'.join(html.escape(x['label']) for x in s['flags']) or '—'
        events=' / '.join(f'<a href="replay/{tag}.html#frame={e["frame"]}">{e["time_s"]:.2f}秒</a>' for e in s['events'][:4]) or '—'
        values=[f"G{r['group']:03d} {html.escape(r['recording'])}",html.escape(str(r['source_label'])),s['rank'],
                html.escape(str(r['condition_id'] or '保留')),f"{s['two_ids_fraction']*100:.1f}%" if r['condition_category']=='追い越し' else '—',
                f"{s['unassigned_positioned_fraction']*100:.1f}%",str(r['withheld_isolated']+r['withheld_discontinuous_points']),
                flags,f'<a href="replay/{tag}.html">再生</a> {events}']
        rows.append('<tr>'+''.join('<td>'+str(x)+'</td>' for x in values)+'</tr>')
    issues=''.join(f'<li>{html.escape(x["tag"])}: {html.escape(x["reason"])}</li>' for x in pending+failures) or '<li>なし</li>'
    excluded_html=''.join(f'<li>G{x["group"]:03d} {html.escape(x["recording"])}: {html.escape(x["reason"])}</li>' for x in excluded_records) or '<li>なし</li>'
    page=('<!doctype html><html lang="ja"><meta charset="utf-8"><title>10 m追跡確認</title><style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px}th{background:#eef}</style>'
          '<h1>深度追跡の目視確認候補（10 m版）</h1><p>優先度は目視確認の目安であり、誤り率や正解率ではありません。点は身体中心でなく可視表面で、IDと校正は暫定です。10 m以遠を除外し、急変点を保留しています。</p>'
          '<p>計画上の人数と録画進捗を参考にしますが、実施条件や被験者IDを確定するものではありません。グループ６等の例外は条件を保留します。ID未確定の点は黒で表示し、同一人物として結びません。</p>'
          f'<p>更新: {html.escape(datetime.now().astimezone().isoformat(timespec="seconds"))} / 対象 {len(records)}録画 / 解析対象外 {len(excluded_records)} / 保留 {len(pending)} / エラー {len(failures)}。<a href="recordings.csv">CSV</a> / <a href="audit.json">根拠</a></p>'
          '<table><tr><th>録画</th><th>元録画名</th><th>優先度</th><th>計画条件</th><th>２人の暫定IDが同時に位置を持つ割合</th><th>ID未確定の位置がある割合</th><th>急変保留点</th><th>確認理由</th><th>再生・時刻</th></tr>'+''.join(rows)+'</table><h2>解析対象外</h2><ul>'+excluded_html+'</ul><h2>処理待ち・エラー</h2><ul>'+issues+'</ul></html>')
    atomic_text(output/'index.html',page)
    print(json.dumps({'at':datetime.now().astimezone().isoformat(timespec='seconds'),'records':len(records),
                      'pending':len(pending),'failures':failures,'priority':dict(collections.Counter(r['stats']['rank'] for r in records))},ensure_ascii=False),flush=True)
    return failures


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=120)
    a=p.parse_args()
    if a.interval<30:p.error('interval must be at least 30 seconds')
    while True:
        failures=scan()
        if not a.watch:return 1 if failures else 0
        time.sleep(a.interval)


if __name__=='__main__':raise SystemExit(main())
