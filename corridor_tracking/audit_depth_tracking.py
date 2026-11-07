"""Prioritize depth-coordinate recordings for manual review, without declaring accuracy."""
import argparse
import bisect
import collections
import csv
from datetime import datetime
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import statistics
from itertools import combinations

from corridor_tracking.coordinate_only_replay import make_page, validate_input
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.prepare_group004_005_bundle import scope_calibration
from corridor_tracking.spatial_filter import filter_frames

SHARE=Path('/data/experiment_data/kaiseki1103/exchange')
TEMPLATE=Path('/data/experiment_data/kaiseki1103/zed_sdk_package/depth_group004_005_batch_20261106_03')
PROGRESS=Path('/data/experiment_data/recordings/.experiment_progress')
TAG=re.compile(r'^g(002|003|004)_(recording_\d{3})_[A-Za-z0-9_]+$')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def packet(path, status='complete'):
    if {p.name for p in path.iterdir()} != {'positions.json','manifest.json'}:
        raise ValueError('unexpected packet files')
    manifest=read(path/'manifest.json')
    if manifest.get('status')!=status or manifest.get('positions_sha256')!=digest(path/'positions.json'):
        raise ValueError('packet hash or status invalid')
    data=read(path/'positions.json'); frames=data['frames']
    if manifest.get('frame_count')!=len(frames) or [f['frame_index'] for f in frames]!=list(range(len(frames))):
        raise ValueError('missing or invalid frame indices')
    previous=None
    for f in frames:
        now=int(f['timestamp_ns']); elapsed=float(f['elapsed_s'])
        if not math.isfinite(elapsed) or (previous and (now<=previous[0] or elapsed<=previous[1])):
            raise ValueError('nonmonotonic time')
        previous=(now,elapsed)
        for o in f['observations']:
            xyz=o['surface_corridor_m']
            if xyz is not None and (len(xyz)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in xyz)):
                raise ValueError('invalid coordinate')
    return data,manifest


def windows(frames, mask, minimum=.5):
    """Ranges of adjacent observed frames, with no interpolation across gaps."""
    found=[];start=None;end=None
    for i,on in enumerate(mask):
        if on and (start is None or (end==i-1 and frames[i]['elapsed_s']-frames[end]['elapsed_s']<=.15)):
            if start is None:start=i
            end=i
        else:
            if start is not None and frames[end]['elapsed_s']-frames[start]['elapsed_s']>=minimum:
                found.append((start,end))
            start=end=i if on else None
    if start is not None and frames[end]['elapsed_s']-frames[start]['elapsed_s']>=minimum:
        found.append((start,end))
    return sorted(found,key=lambda x:frames[x[1]]['elapsed_s']-frames[x[0]]['elapsed_s'],reverse=True)


def metrics(frames, expected):
    good=[];unknown=[];ids=collections.Counter();per_id={};jumps=[];swaps=[];previous_frame=None
    for i,f in enumerate(frames):
        located=[o for o in f['observations'] if o['surface_corridor_m'] is not None]
        known=[o for o in located if o['track_id'] is not None]
        positions={o['track_id']:o['surface_corridor_m'] for o in known}
        if previous_frame is not None:
            before_t,before=previous_frame
            dt=f['elapsed_s']-before_t
            if 0<dt<=.15:
                for a,b in combinations(sorted(positions.keys() & before.keys()),2):
                    before_sep=math.dist(before[a][:2],before[b][:2])
                    after_sep=math.dist(positions[a][:2],positions[b][:2])
                    same=math.dist(before[a][:2],positions[a][:2])+math.dist(before[b][:2],positions[b][:2])
                    other=math.dist(before[a][:2],positions[b][:2])+math.dist(before[b][:2],positions[a][:2])
                    if min(before_sep,after_sep)>=.25 and same-other>=.45:
                        swaps.append({'frame':i,'ids':[a,b],'same_m':round(same,2),'swapped_m':round(other,2)})
        previous_frame=(f['elapsed_s'],positions)
        good.append(len({o['track_id'] for o in known}));unknown.append(any(o['track_id'] is None for o in located))
        for o in known:
            ident=o['track_id'];p=o['surface_corridor_m'];ids[ident]+=1
            if ident in per_id:
                old_i, old_t, old_p=per_id[ident];dt=f['elapsed_s']-old_t
                dist=math.dist(p[:2],old_p[:2])
                if old_i==i-1 and 0<dt<=.15 and dist>=.6 and dist/dt>=4:
                    jumps.append({'frame':i,'time_s':round(f['elapsed_s'],3),'id':ident,
                                  'distance_m':round(dist,2),'delta_s':round(dt,3),'speed_m_s':round(dist/dt,1)})
            per_id[ident]=(i,f['elapsed_s'],p)
    present=[i for i,n in enumerate(good) if n>0]
    first,last=(present[0],present[-1]) if present else (0,len(frames)-1)
    active=range(first,last+1); size=max(1,last-first+1)
    pair=sum(good[i]>=2 for i in active)/size
    unk=sum(unknown[i] for i in active)/size
    known_count={str(k):v for k,v in sorted(ids.items())}
    substantial=sum(v>=10 for v in ids.values())
    flags=[];events=[]
    def add_event(kind,begin,end,detail):
        events.append({'kind':kind,'frame':begin,'end_frame':end,'time_s':round(frames[begin]['elapsed_s'],3),
                       'end_time_s':round(frames[end]['elapsed_s'],3),'detail':detail})
    if expected==2:
        if pair<.2:
            flags.append(('high','two_person_little_overlap','２つの確定IDが同時に位置を持つ割合が20%未満'))
        elif pair<.5:
            flags.append(('review','two_person_low_overlap','２つの確定IDが同時に位置を持つ割合が50%未満'))
        if pair<.5:
            mask=[first<=i<=last and good[i]<2 for i in range(len(frames))]
            for a,b in windows(frames,mask,1.0)[:2]:add_event('two_person_low_overlap',a,b,'２つの確定IDが同時に存在しない区間')
    if unk>=.35:
        flags.append(('high','unassigned_many','位置のあるID未確定が多い'))
    elif unk>=.15:
        flags.append(('review','unassigned','位置のあるID未確定が見られる'))
    if unk>=.15:
        for a,b in windows(frames,[first<=i<=last and unknown[i] for i in range(len(frames))],.5)[:2]:add_event('unassigned',a,b,'位置があるID未確定の連続区間')
    if expected==1:
        extra=sum(good[i]>=2 for i in active)/size
        if extra>=.15:
            flags.append(('review','solo_multiple','単独歩行の計画に対し、２つ以上の確定IDが同時に位置を持つ'))
            for a,b in windows(frames,[first<=i<=last and good[i]>=2 for i in range(len(frames))],.5)[:2]:add_event('solo_multiple',a,b,'複数IDの同時位置')
    if jumps:
        flags.append(('high' if len(jumps)>=3 or max(j['distance_m'] for j in jumps)>=1.2 else 'review',
                      'position_jump','同じIDの隣接座標に急な移動'))
        for j in sorted(jumps,key=lambda k:k['distance_m'],reverse=True)[:3]:
            add_event('position_jump',j['frame'],j['frame'],f"ID {j['id']} が {j['delta_s']:.3f} 秒で {j['distance_m']:.2f} m（{j['speed_m_s']:.1f} m/s）")
    if swaps:
        flags.append(('high','possible_id_swap','２つのIDの位置対応が入れ替わった可能性'))
        for s in swaps[:3]:
            add_event('possible_id_swap',s['frame'],s['frame'],f"ID {s['ids'][0]} と {s['ids'][1]} の前後の位置が交差対応に近い")
    if substantial>=5:
        flags.append(('high' if substantial>=7 else 'review','many_ids',f'10フレーム以上のIDが{substantial}種類'))
    if not present:
        flags.append(('high','no_located_id','範囲内の確定ID付き位置なし'))
    no_position=windows(frames,[first<=i<=last and good[i]==0 for i in range(len(frames))],2.)
    if no_position:
        flags.append(('review','no_located_span','確定ID付き位置が２秒以上途切れる'))
        for a,b in no_position[:2]:add_event('no_located_span',a,b,'確定ID付き位置なし')
    rank='優先' if any(f[0]=='high' for f in flags) else ('確認' if flags else '低')
    return {'rank':rank,'frames':len(frames),'active_frames':size,'active_start_s':round(frames[first]['elapsed_s'],3),
        'active_end_s':round(frames[last]['elapsed_s'],3),'two_ids_fraction':round(pair,4),
        'unassigned_positioned_fraction':round(unk,4),'substantial_ids':substantial,'id_positioned_frames':known_count,
        'jump_count':len(jumps),'possible_swap_count':len(swaps),'flags':[{'level':a,'code':b,'label':c} for a,b,c in flags],
        'events':sorted(events,key=lambda e:e['time_s'])}


def matched_trial(plan,progress,group,recording):
    if progress.get('group')!=f'G{group:02}' or progress.get('plan_sha256')!=plan.get('plan_sha256'):
        raise ValueError('progress and experiment plan differ')
    found=[int(k) for k,v in progress.get('attempts',{}).items()
           if any(a.get('recording_id')==recording and a.get('status')=='complete' for a in v)]
    if len(found)!=1:raise ValueError(f'recording maps to {len(found)} completed trials')
    matches=[x for x in plan['groups'][f'G{group:02}']['trials'] if int(x['global_trial_number'])==found[0]]
    if len(matches)!=1 or matches[0]['condition_category'] not in ('追い越し','単独歩行'):
        raise ValueError('plan trial missing or unsupported')
    return matches[0]


def snapshot_images(root,data):
    """Use original sparse SDK left images as context only; never infer person identity."""
    if root is None or not root.is_dir():return []
    try:
        manifest=root/'manifest.json';m=read(manifest)
        if digest(manifest)!=data['metadata'].get('body_manifest_sha256') or digest(root/'assets.csv')!=m['file_hashes']['assets.csv']:
            return []
        out=[]
        with (root/'assets.csv').open(newline='',encoding='utf-8-sig') as f:
            for a in csv.DictReader(f):
                rel=Path(a['path']);i=int(a['frame_index'])
                if rel.is_absolute() or '..' in rel.parts or not (0<=i<len(data['frames'])):continue
                if str(a['image_timestamp_ns'])!=str(data['frames'][i]['timestamp_ns']):continue
                file=root/rel
                if file.is_file():out.append({'frame':i,'time_s':data['frames'][i]['elapsed_s'],'file':file,'sha256':a['sha256']})
        return sorted(out,key=lambda r:r['time_s'])
    except (OSError,ValueError,KeyError):return []


def make_replay(data,tag,events,pages,images):
    page=make_page(data,tag)
    # Show positioned but unassigned observations without joining them across frames.
    page=page.replace('o.track_id!==null&&o.surface_corridor_m','o.surface_corridor_m')
    page=page.replace('if(o.track_id===null||!p)continue','if(!p)continue')
    page=page.replace('if(j>0&&f[j].frame_index','if(o.track_id!==null&&j>0&&f[j].frame_index')
    page=page.replace('color=id=>`hsl(',"color=id=>id===null?'#222':`hsl(")
    page=page.replace('${o.track_id}${o.identity_assignment',"${o.track_id===null?'?':o.track_id}${o.identity_assignment")
    page=page.replace('s.oninput=()=>{stop();render()};','s.oninput=()=>{stop();render()};')
    page=page.replace('};render();</script></html>',"};const target=Number(new URLSearchParams(location.hash.slice(1)).get('frame'));if(location.hash&&Number.isInteger(target)&&target>=0&&target<f.length)s.value=target;render();</script></html>")
    page=page.replace('<p><a href="positions.json">時刻付き座標</a> / <a href="manifest.json">照合記録</a></p>', '')
    extra=['<p>黒い点は位置のあるID未確定です。過去の未確定点は人物を特定できないため線で結びません。背景画像付きの連続再生はSSDの一覧を使用してください。</p>']
    if events:
        extra.append('<h2>確認候補の時刻</h2><ul>')
        for e in events:
            a=e['frame'];s=e['time_s'];end=e['end_time_s']; suffix=''
            if images:
                times=[x['time_s'] for x in images];idx=bisect.bisect_left(times,s)
                choices=images[max(0,idx-1):min(len(images),idx+1)]
                if choices:
                    near=min(choices,key=lambda x:abs(x['time_s']-s));delta=near['time_s']-s
                    if abs(delta)<=.15 and digest(near['file'])==near['sha256']:
                        path=os.path.relpath(near['file'],pages).replace(os.sep,'/')
                        suffix=f' / <a href="{html.escape(path,quote=True)}">近い時刻の元画像（{near["time_s"]:.3f}秒、差{delta:+.3f}秒）</a>'
            extra.append(f'<li><a href="#frame={a}" onclick="document.getElementById(\'slider\').value={a};document.getElementById(\'slider\').dispatchEvent(new Event(\'input\'))">{s:.3f}〜{end:.3f}秒</a>：{html.escape(e["detail"])}{suffix}</li>')
        extra.append('</ul>')
    return page.replace('<label>時刻', ''.join(extra)+'<label>時刻',1)


def run(output):
    if output.exists():raise FileExistsError(output)
    raw_roots={2:SHARE/'depth_group002_003_coordinates_20261105_01',
               3:SHARE/'depth_group002_003_coordinates_20261105_01',
               4:SHARE/'depth_group004_005_coordinates_20261106_01'}
    filtered_roots={2:SHARE/'depth_group002_003_spatial_20261106_01/originals',
                    3:SHARE/'depth_group002_003_spatial_20261106_01/originals',
                    4:SHARE/'depth_group004_005_spatial_20261106_01/originals'}
    candidate_roots={2:SHARE/'depth_group002_003_spatial_20261106_01/candidates',
                     3:SHARE/'depth_group002_003_spatial_20261106_01/candidates',
                     4:SHARE/'depth_group004_005_spatial_20261106_01/candidates'}
    with (SHARE/'depth_group002_003_inventory_20261105_01.csv').open(newline='',encoding='utf-8-sig') as f:
        inv={(int(r['group']),r['recording']):r for r in csv.DictReader(f)}
    for r in read(TEMPLATE/'group4_inventory.json'):
        inv[(int(r['group']),r['recording'])]=r
    template_manifest=read(TEMPLATE/'template_manifest.json')
    if digest(TEMPLATE/'group4_inventory.json')!=template_manifest['files_sha256']['group4_inventory.json']:
        raise ValueError('group 4 inventory hash mismatch')
    cal_path=Path('results/tracking_v2/group004_005_coordinate_audit_20261106_01/base_calibration.json')
    calibration=read(cal_path)
    planpath=Path('experiment_metadata/run_order_20261103.json');plan=read(planpath)
    progress_paths={g:next(PROGRESS.glob(f'g{g:02d}_*.json')) for g in (2,3,4)}
    progress={g:read(p) for g,p in progress_paths.items()}
    snapshot=datetime.now().astimezone().isoformat(timespec='seconds')
    discovered=[]
    for group in (2,3,4):
        for p in sorted(raw_roots[group].glob(f'g{group:03d}_recording_*')):
            if p.is_dir() and TAG.fullmatch(p.name):discovered.append((group,p))
    seen=collections.Counter((g,TAG.fullmatch(p.name)[2]) for g,p in discovered)
    snapshot_data={'snapshot_at':snapshot,'source_folder_counts':dict(collections.Counter(str(g) for g,_ in discovered)),
                   'source_names':[p.name for _,p in discovered], 'plan_sha256':digest(planpath),
                   'progress_sha256':{str(g):digest(p) for g,p in progress_paths.items()},
                   'script_sha256':digest(Path(__file__))}
    output.mkdir(parents=True);pages=output/'replay';pages.mkdir()
    records=[];failures=[]
    for group,raw_path in discovered:
        match=TAG.fullmatch(raw_path.name);rec=match[2]
        try:
            if seen[(group,rec)]!=1:raise ValueError('multiple coordinate runs for recording')
            row=inv[(group,rec)];raw,rm=packet(raw_path)
            filtered,fm=packet(filtered_roots[group]/raw_path.name)
            if fm.get('source_positions_sha256')!=digest(raw_path/'positions.json') or fm.get('source_manifest_sha256')!=digest(raw_path/'manifest.json'):
                raise ValueError('filtered coordinates do not match raw source')
            check,_,stats=filter_frames(raw['frames'],fm['bounds'])
            if check!=filtered['frames'] or stats!=fm['counts'] or filtered['metadata']!=raw['metadata']:
                raise ValueError('filtered data differ from declared bounds')
            meta=raw['metadata']
            for key in ('recording','source_svo_sha256','setup_id','body_manifest_sha256'):
                if meta.get(key)!=row[key]:raise ValueError(f'inventory differs: {key}')
            if str(meta['group'])!=str(group) or len(raw['frames'])!=int(row['frame_count']):
                raise ValueError('group or frame count differs')
            if group in (2,3):validate_input(raw_path,row)
            else:
                timeline=TEMPLATE/row['timeline']
                if digest(timeline)!=template_manifest['files_sha256'][row['timeline']]:raise ValueError('timeline hash mismatch')
                reference=read(timeline);tf=reference['frames']
                if len(tf)!=len(raw['frames']) or any(str(t['image_timestamp_ns'])!=str(f['timestamp_ns']) for t,f in zip(tf,raw['frames'])):
                    raise ValueError('timeline timestamp mismatch')
                scoped=scope_calibration(calibration,reference['camera'],digest(cal_path))
                cal_bytes=cal_path.read_bytes() if scoped is None else (json.dumps(scoped,ensure_ascii=False,indent=2,allow_nan=False)+'\n').replace('\n','\r\n').encode('utf-8')
                if hashlib.sha256(cal_bytes).hexdigest()!=meta['calibration_sha256']:
                    raise ValueError('group 4 calibration mismatch')
            trial=matched_trial(plan,progress[group],group,rec)
            expected=2 if trial['condition_category']=='追い越し' else 1
            m=metrics(filtered['frames'],expected)
            base={'group':group,'recording':rec,'tag':raw_path.name,'trial':trial['global_trial_number'],
                  'condition_id':trial['condition_id'],'category':trial['condition_category'],
                  'planned_width':trial['corridor_width'],'planned_direction':trial.get('overtaking_direction'),
                  'condition_basis':'plan_and_recorder_progress_not_observed_truth',
                  'raw_positions_sha256':digest(raw_path/'positions.json'),
                  'filtered_positions_sha256':digest(filtered_roots[group]/raw_path.name/'positions.json'),
                  'excluded_outside':fm['counts']['outside_any'],'bounds':fm['bounds'],**m}
            body=Path(row['body_dir']) if group in (2,3) else SHARE/'group004_20261105_body_01'/rec/'body'
            imgs=snapshot_images(body,raw)
            candidate_paths=sorted(candidate_roots[group].glob(f'g{group:03d}_{rec}_*'))
            candidates=[]
            for cp in candidate_paths:
                if not cp.is_dir():continue
                try:
                    cd,cm=packet(cp,'proposed_not_verified')
                    if cm['source_positions_sha256']!=base['filtered_positions_sha256'] or cm['bounds']!=fm['bounds']:
                        raise ValueError('candidate source or bounds differ')
                    n=validate_candidate(filtered,cd,base['filtered_positions_sha256'])
                    cmets=metrics(cd['frames'],expected)
                    candidate_file=pages/(cp.name+'_candidate.html')
                    candidate_view={'frames':cd['frames'],'walls':{'visible':fm['bounds']['visible_wall_y_m'],
                                    'opposite':fm['bounds']['opposite_wall_y_m']}}
                    candidate_page=make_replay(candidate_view,f'グループ{group} {rec} ID再割当て候補',m['events'],pages,imgs)
                    candidate_page=candidate_page.replace('<label>時刻','<p><strong>この再割当ては未検証の候補です。白い縁と破線は仮割当てを示します。</strong></p><label>時刻',1)
                    candidate_file.write_text(candidate_page,encoding='utf-8')
                    candidates.append({'name':cp.name,'proposed_observations':n,
                        'two_ids_fraction':cmets['two_ids_fraction'],
                        'unassigned_positioned_fraction':cmets['unassigned_positioned_fraction'],
                        'candidate_positions_sha256':digest(cp/'positions.json'),'status':'proposed_not_verified',
                        'replay':'replay/'+candidate_file.name})
                except (ValueError,KeyError,OSError) as e:
                    candidates.append({'name':cp.name,'status':'not_validated','error':str(e)})
            base['candidates']=candidates
            view={'frames':filtered['frames'],'walls':{'visible':fm['bounds']['visible_wall_y_m'],
                   'opposite':fm['bounds']['opposite_wall_y_m']}}
            replay=pages/(raw_path.name+'.html')
            replay.write_text(make_replay(view,f'グループ{group} {rec}',m['events'],pages,imgs),encoding='utf-8')
            base['replay']='replay/'+replay.name
            records.append(base)
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as e:
            failures.append({'group':group,'recording':rec,'tag':raw_path.name,'error':str(e)})
    ranks={'優先':0,'確認':1,'低':2}
    records.sort(key=lambda x:(ranks[x['rank']],-len([f for f in x['flags'] if f['level']=='high']),
                               -x['unassigned_positioned_fraction'],x['group'],x['recording']))
    summary={'snapshot':snapshot_data,'records':records,'failures':failures,
             'scope':'automatic triage only; condition from plan, positions are visible depth surfaces, ID not human-verified',
             'thresholds':{'two_id_fraction_high_below':.2,'two_id_fraction_review_below':.5,
                           'unassigned_fraction_high_at_least':.35,'unassigned_fraction_review_at_least':.15,
                           'consecutive_jump_m_at_least':.6,'consecutive_jump_speed_m_s_at_least':4,
                           'consecutive_max_gap_s':.15,'possible_id_swap_min_separation_m':.25,
                           'possible_id_swap_cost_advantage_m':.45,'substantial_id_min_frames':10,'substantial_id_review_count':5}}
    (output/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (output/'recordings.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['rank','group','recording','trial','condition_id','category','planned_width','planned_direction',
                'frames','two_ids_fraction','unassigned_positioned_fraction','substantial_ids','jump_count','possible_swap_count',
                'excluded_outside','replay','reason','times','candidates']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for x in records:
            writer.writerow({**{k:x.get(k) for k in fields},
              'reason':' / '.join(y['label'] for y in x['flags']),
              'times':' / '.join(f'{y["time_s"]:.2f}–{y["end_time_s"]:.2f}秒: {y["detail"]}' for y in x['events']),
              'candidates':json.dumps(x['candidates'],ensure_ascii=False)})
    write_index(output,records,failures,snapshot_data)
    print(f'Audited {len(records)} recordings; {len(failures)} incomplete or failed validation. '+
          str(dict(collections.Counter(x['rank'] for x in records))),flush=True)
    return records,failures


def write_index(output,records,failures,snapshot):
    rows=[]
    for x in records:
        events=' / '.join(f'<a href="{html.escape(x["replay"],quote=True)}#frame={e["frame"]}">{e["time_s"]:.1f}〜{e["end_time_s"]:.1f}秒</a>' for e in x['events']) or '—'
        flags=' / '.join(html.escape(f['label']) for f in x['flags']) or '自動条件に該当なし'
        candidate='<br>'.join(f'<a href="{html.escape(c["replay"],quote=True)}">仮候補 {c["proposed_observations"]}観測</a>（ID未確定 {c["unassigned_positioned_fraction"]:.0%}）' if c['status']=='proposed_not_verified' else '候補の検証未完了' for c in x['candidates']) or '—'
        rows.append('<tr>' + ''.join(f'<td>{v}</td>' for v in [
           html.escape(x['rank']),f'<a href="{html.escape(x["replay"],quote=True)}">G{x["group"]} {html.escape(x["recording"])}</a>',
           f'{x["trial"]} / {html.escape(x["condition_id"])}<br>{html.escape(x["category"])}・{html.escape(x["planned_width"])}',
           flags, f'{x["two_ids_fraction"]:.0%}' if x['category']=='追い越し' else '—',
           f'{x["unassigned_positioned_fraction"]:.0%}',str(x['substantial_ids']),str(x['jump_count']),str(x['possible_swap_count']),candidate,events])+'</tr>')
    missing=''.join(f'<li>G{v["group"]} {html.escape(v["recording"])}: {html.escape(v["error"])}</li>' for v in failures)
    page='''<!doctype html><html lang="ja"><meta charset="utf-8"><title>深度追跡の目視確認候補</title>
<style>body{font:15px system-ui;margin:20px;color:#203040}table{border-collapse:collapse}th,td{border:1px solid #ccd5db;padding:6px;vertical-align:top}th{background:#e9f0f2;position:sticky;top:0}tr:nth-child(even){background:#f8fafb}small{color:#555}input{padding:6px}</style>
<h1>深度追跡の目視確認候補</h1>
<p>__SNAP__ 時点で共有済みの座標が対象。計画・録画進捗に基づく条件であり、実行条件・被験者IDの正解ではありません。判定は目視の優先順位であり、精度や誤りの確定ではありません。</p>
<p>範囲はX≤15mかつ推定壁の内側。位置がないものは内外不明として保持します。IDなしでも位置がある点は黒で表示します。２人同時割合とID未確定割合は、最初から最後の確定ID付き位置までのフレームを分母とし、画面外・遮蔽・入退場でも低下します。単独歩行は２人同時割合を判定に使いません。</p>
<p>急変は隣接フレーム間0.15秒以内で水平移動0.6m以上かつ4m/s以上。入替候補は隣接フレームで2つのIDの位置を入れ替える方が0.45m以上近い場合。表面の位置変動や深度誤差も含むため要目視。実際の追い越しの左右・被験者番号は座標だけで確定できません。「仮候補」は未検証の再割当てで原本とは別です。</p>
<p>録画をクリックすると上面再生、時刻をクリックすると該当フレームへ移動します。近くの元画像がある場合は再生ページにリンクします。Windows SSD上の元画像と同時の連続再生は <code>G:\\kaiseki1005\\depth_replay_index.html</code> から開いてください。</p>
<label>絞り込み <input id="q" placeholder="例: G2 recording_004 / 優先"></label><p><a href="recordings.csv">全録画CSV</a> / <a href="audit.json">判定と入力ハッシュJSON</a></p>
<table><thead><tr><th>優先度</th><th>録画・上面再生</th><th>計画の試行 / 条件</th><th>確認理由</th><th>２ID同時</th><th>位置ありID?</th><th>10フレーム以上のID数</th><th>急変数</th><th>入替候補</th><th>再割当て候補</th><th>確認時刻</th></tr></thead><tbody>__ROWS__</tbody></table>
<h2>照合保留・未処理</h2><ul>__FAILURES__</ul><script>document.getElementById('q').oninput=function(){const q=this.value.toLowerCase();for(const r of document.querySelectorAll('tbody tr'))r.hidden=!r.textContent.toLowerCase().includes(q)};</script></html>'''
    (output/'index.html').write_text(page.replace('__ROWS__',''.join(rows)).replace('__FAILURES__',missing or '<li>なし</li>').replace('__SNAP__',html.escape(snapshot['snapshot_at'])),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.output)


if __name__=='__main__':main()
