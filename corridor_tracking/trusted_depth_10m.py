"""Derive a 10 m corridor dataset from verified depth coordinates; never overwrite source."""
import argparse
import copy
import csv
from datetime import datetime
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time

from corridor_tracking.audit_depth_tracking import packet, metrics, make_replay, digest, read, snapshot_images
from corridor_tracking.coordinate_only_replay import validate_input
from corridor_tracking.filter_shared_positions import save_packet
from corridor_tracking.prepare_group004_005_bundle import scope_calibration
from corridor_tracking.spatial_filter import corridor_bounds, filter_frames
from corridor_tracking.trajectory_quality import withhold_isolated_excursions, withhold_discontinuous_pairs

SHARE=Path('/data/experiment_data/kaiseki1103/exchange')
TEMPLATE=Path('/data/experiment_data/kaiseki1103/zed_sdk_package/depth_group004_005_batch_20261106_03')
CAL=Path('results/tracking_v2/group004_005_coordinate_audit_20261106_01/base_calibration.json')
OUT=SHARE/'depth_group002_005_trusted10_20261106_01'
G45_BUNDLE='0e6974e3ccc5f469f4479172a942ecfe213666be9a9f67023775ef53dd0f754a'
TAG=re.compile(r'^g(002|003|004|005)_(recording_\d{3})_[A-Za-z0-9_]+$')


def load_context():
    with (SHARE/'depth_group002_003_inventory_20261105_01.csv').open(newline='',encoding='utf-8-sig') as f:
        rows={(int(r['group']),r['recording']):r for r in csv.DictReader(f)}
    tm=read(TEMPLATE/'template_manifest.json')
    for name in ('group4_inventory.json','group5_recordings.json'):
        if digest(TEMPLATE/name)!=tm['files_sha256'][name]:raise ValueError(f'template hash mismatch: {name}')
    for row in read(TEMPLATE/'group4_inventory.json'):rows[(4,row['recording'])]=row
    valid5=set(read(TEMPLATE/'group5_recordings.json'))
    return rows,tm,read(CAL),valid5


def validate_source(group,recording,path,rows,tm,base,valid5):
    data,manifest=packet(path);meta=data['metadata']
    if (meta.get('group')!=group or meta.get('recording')!=recording or
        manifest.get('group')!=group or manifest.get('recording')!=recording or
        manifest.get('source_svo_sha256')!=meta.get('source_svo_sha256')):
        raise ValueError('coordinate identity or source hash differs')
    if group in (2,3):
        row=rows[(group,recording)]
        validate_input(path,row)
        cal=Path(row['calibration'])
        if digest(cal)!=row['calibration_sha256']:raise ValueError('calibration hash differs')
        return data,manifest,corridor_bounds(read(cal),max_x_m=10.),row,'per-recording calibration hash checked'
    if meta.get('setup_id')!=base['setup_id'] or (group==5 and meta.get('bundle_manifest_sha256')!=G45_BUNDLE):
        raise ValueError('group 4/5 bundle or setup differs')
    if group==4:
        row=rows[(4,recording)]
        for key in ('source_svo_sha256','setup_id','body_manifest_sha256'):
            if meta.get(key)!=row[key]:raise ValueError(f'group 4 inventory mismatch: {key}')
        timeline=TEMPLATE/row['timeline']
        if digest(timeline)!=tm['files_sha256'][row['timeline']]:raise ValueError('timeline hash differs')
        reference=read(timeline); tf=reference['frames']
        if len(tf)!=len(data['frames']) or any(str(a['image_timestamp_ns'])!=str(b['timestamp_ns']) for a,b in zip(tf,data['frames'])):
            raise ValueError('group 4 timeline differs')
        scoped=scope_calibration(base,reference['camera'],digest(CAL))
        raw=CAL.read_bytes() if scoped is None else (json.dumps(scoped,ensure_ascii=False,indent=2,allow_nan=False)+'\n').replace('\n','\r\n').encode('utf-8')
        if hashlib.sha256(raw).hexdigest()!=meta['calibration_sha256']:raise ValueError('group 4 calibration differs')
        verify='per-recording calibration and timeline hashes checked'
    elif group==5:
        if recording not in valid5 or meta.get('reference_kind')!='svo_sdk_timeline_no_body' or not re.fullmatch(r'[0-9a-f]{64}',meta.get('timeline_sha256','')):
            raise ValueError('group 5 recording or SVO timeline provenance invalid')
        row=None
        verify='group 5 bundle and recorded timeline hash checked; individual SVO, timeline and calibration remain on Windows and are not independently verified here'
    else:raise ValueError('unsupported group')
    return data,manifest,corridor_bounds(base,max_x_m=10.,fallback_width_m=2.376029800280445),row,verify


def derive(data,bounds):
    ten,_,bounds_stats=filter_frames(data['frames'],bounds)
    isolated,spikes=withhold_isolated_excursions(ten)
    cleaned,jumps,pair_count=withhold_discontinuous_pairs(isolated)
    before=metrics(ten,2)['jump_count'];after=metrics(cleaned,2)['jump_count']
    payload=copy.deepcopy(data);payload['frames']=cleaned
    payload['quality_filter']={'status':'provisional','x_max_m':10.,'boundary':'x <= 10 m and inside inferred walls',
        'semantics':'positions are visible surface; ID and calibration provisional',
        'method':'out-of-region observations excluded; isolated excursions and both uncertain discontinuity endpoints withheld',
        'no_interpolation':True,'unknown_id_motion_checked':False,
        'outside_counts':bounds_stats,'isolated_points_withheld':len(spikes),
        'discontinuity_events':len(jumps),'discontinuity_points_withheld':pair_count,
        'adjacent_jump_before':before,'adjacent_jump_after':after,
        'code_sha256':digest(Path(__file__)),
        'trajectory_quality_sha256':digest(Path('corridor_tracking/trajectory_quality.py'))}
    payload['walls']={'visible':bounds['visible_wall_y_m'],'opposite':bounds['opposite_wall_y_m']}
    return payload,ten,spikes,jumps


def process(path,context,output):
    match=TAG.fullmatch(path.name)
    if not match:raise ValueError('unexpected recording tag')
    group=int(match[1]);rec=match[2]
    data,manifest,bounds,row,verification=validate_source(group,rec,path,*context)
    payload,before,spikes,jumps=derive(data,bounds)
    source_sha=digest(path/'positions.json');source_manifest_sha=digest(path/'manifest.json')
    record={'status':'complete','source_positions_sha256':source_sha,'source_manifest_sha256':source_manifest_sha,
            'bounds':bounds,'group':group,'recording':rec,'frame_count':len(before),'allowed_files':['positions.json','manifest.json'],
            'algorithm_sha256':digest(Path(__file__)),'trajectory_quality_sha256':digest(Path('corridor_tracking/trajectory_quality.py')),
            'source_verification':verification,'quality_filter':payload['quality_filter']}
    dest=output/'originals'/path.name
    if dest.exists():
        existing,old=packet(dest)
        if (existing!=payload or any(old.get(k)!=record[k] for k in ('source_positions_sha256','source_manifest_sha256','bounds','algorithm_sha256','trajectory_quality_sha256'))):
            raise ValueError('existing derived result differs; will not overwrite')
    else:
        save_packet(dest,payload,record)
        stored,stored_manifest=packet(dest)
        if stored!=payload:raise ValueError('stored output differs')
    return {'group':group,'recording':rec,'tag':path.name,'source_positions_sha256':source_sha,
            'filtered_positions_sha256':digest(dest/'positions.json'),'source_verification':verification,
            'bounds':bounds,'quality':payload['quality_filter'],'isolated_events':spikes,'discontinuities':jumps,
            'data':payload,'before':before,'raw':data,'row':row}


def scan(context,output):
    roots=(SHARE/'depth_group002_003_coordinates_20261105_01',SHARE/'depth_group004_005_coordinates_20261106_01')
    paths=sorted(p for r in roots for p in r.iterdir() if p.is_dir() and TAG.fullmatch(p.name))
    seen={}; failures=[]; records=[]
    for p in paths:
        m=TAG.fullmatch(p.name);key=(int(m[1]),m[2]);seen.setdefault(key,[]).append(p)
    for p in paths:
        m=TAG.fullmatch(p.name);key=(int(m[1]),m[2])
        try:
            if len(seen[key])!=1:raise ValueError('multiple coordinate results; manual review required')
            records.append(process(p,context,output))
        except (ValueError,KeyError,OSError,TypeError) as e:
            failures.append({'tag':p.name,'error':str(e)})
    return records,failures


def save_report(records,failures,destination):
    if destination.exists():raise FileExistsError(destination)
    destination.mkdir(parents=True);pages=destination/'replay';pages.mkdir()
    rows=[]; public=[]
    for r in records:
        q=r['quality'];tag=r['tag'];events=[]
        for e in r['isolated_events']:
            events.append({'kind':'isolated','frame':e['frame_index'],'end_frame':e['frame_index'],
                'time_s':round(e['elapsed_s'],3),'end_time_s':round(e['elapsed_s'],3),
                'detail':f'ID {e["track_id"]} の短い飛びを保留'})
        for e in r['discontinuities']:
            events.append({'kind':'discontinuity','frame':e['right_frame'],'end_frame':e['right_frame'],
                'time_s':round(e['right_time_s'],3),'end_time_s':round(e['right_time_s'],3),
                'detail':f'ID {e["track_id"]}: {e["interval_s"]:.3f}秒で {e["distance_m"]:.2f}m、両端を保留'})
        events.sort(key=lambda e:e['time_s'])
        group=r['group'];rec=r['recording'];body=(Path(r['row']['body_dir']) if group in (2,3) else
            SHARE/'group004_20261105_body_01'/rec/'body' if group==4 else None)
        images=snapshot_images(body,r['raw'])
        view={'frames':r['data']['frames'],'walls':r['data']['walls']}
        (pages/(tag+'.html')).write_text(make_replay(view,f'グループ{group} {rec}（10m・保留後）',events,pages,images),encoding='utf-8')
        before_link=''
        if spikes_or_jumps:=bool(r['isolated_events'] or r['discontinuities']):
            base={'frames':r['before'],'walls':r['data']['walls']}
            (pages/(tag+'_before.html')).write_text(make_replay(base,f'グループ{group} {rec}（10m・保留前）',events,pages,images),encoding='utf-8')
            before_link=f'<a href="replay/{html.escape(tag)}_before.html">保留前</a>'
        event_links=' / '.join(f'<a href="replay/{html.escape(tag)}.html#frame={e["frame"]}">{e["time_s"]:.2f}秒</a>' for e in events[:8]) or '—'
        rows.append('<tr>'+''.join(f'<td>{v}</td>' for v in [f'G{group} {html.escape(rec)}',
          str(q['outside_counts']['outside_x']),str(q['outside_counts']['outside_wall']),
          str(q['isolated_points_withheld']),str(q['discontinuity_events']),str(q['discontinuity_points_withheld']),
          f'{q["adjacent_jump_before"]} → {q["adjacent_jump_after"]}',f'<a href="replay/{html.escape(tag)}.html">保留後</a> {before_link}',event_links])+'</tr>')
        public.append({k:v for k,v in r.items() if k not in ('data','before','raw','row')})
    public.sort(key=lambda x:(x['group'],x['recording']))
    (destination/'report.json').write_text(json.dumps({'generated_at':datetime.now().astimezone().isoformat(timespec='seconds'),
      'records':public,'failures':failures,'limit':'not a validated improvement in physical accuracy; missing positions not reconstructed'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (destination/'recordings.csv').open('w',newline='',encoding='utf-8-sig') as f:
        keys=['group','recording','outside_x','outside_wall','isolated_withheld','discontinuities','discontinuity_points_withheld','jump_before','jump_after']
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for r in records:
            q=r['quality'];w.writerow({'group':r['group'],'recording':r['recording'],'outside_x':q['outside_counts']['outside_x'],
             'outside_wall':q['outside_counts']['outside_wall'],'isolated_withheld':q['isolated_points_withheld'],
             'discontinuities':q['discontinuity_events'],'discontinuity_points_withheld':q['discontinuity_points_withheld'],
             'jump_before':q['adjacent_jump_before'],'jump_after':q['adjacent_jump_after']})
    failure_html=''.join(f'<li>{html.escape(x["tag"])}: {html.escape(x["error"])}</li>' for x in failures) or '<li>なし</li>'
    text='''<!doctype html><html lang="ja"><meta charset="utf-8"><title>10m以内の深度位置</title>
<style>body{font:15px system-ui;margin:22px}table{border-collapse:collapse}th,td{border:1px solid #ccd;padding:6px}th{background:#eef}tr:nth-child(even){background:#fafafa}</style>
<h1>10m以内の深度位置・急変の保留</h1><p>X≤10mと推定壁の内側を使用。10mはカメラからの直線距離ではなく廊下方向Xです。位置が不明な候補は範囲を判定できず、欠測のままです。</p>
<p>前後に戻る短い飛びを保留し、それ以外の0.15秒以内・0.6m以上かつ4m/s以上の隣接急変は、どちらが不正か不明なため両端を欠測にします。補間や座標の捏造はしません。元座標とIDは変更しません。隣接急変が消えても、位置の真値・ID・速度の正確さや欠測を挟んだ不連続が解決したことにはなりません。</p>
<p>「保留前」は同じ10m範囲内で点を保留する前。「保留後」は除去後。欠測は線で結ばず、未確定IDの位置は黒い点です。近い時刻の元画像リンクは一部の録画のみです。SSDの既存リプレイは元の座標であり、この10m・保留処理は自動反映されていません。</p>
<p><a href="recordings.csv">録画別CSV</a> / <a href="report.json">詳細と元座標の記録</a></p>
<table><tr><th>録画</th><th>X&gt;10m除外</th><th>壁外除外</th><th>短い飛び保留点</th><th>未解決の急変</th><th>急変両端の保留点</th><th>隣接急変 前→後</th><th>上面再生</th><th>確認時刻</th></tr>__ROWS__</table><h2>処理保留</h2><ul>__FAIL__</ul></html>'''
    (destination/'index.html').write_text(text.replace('__ROWS__',''.join(rows)).replace('__FAIL__',failure_html),encoding='utf-8')
    return public


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root',type=Path,default=OUT)
    p.add_argument('--report',type=Path,help='new snapshot report directory')
    p.add_argument('--watch',action='store_true',help='keep scanning for new group 4/5 packets')
    p.add_argument('--interval-seconds',type=int,default=120)
    a=p.parse_args()
    if not a.report and not a.watch:p.error('provide --report or --watch')
    if a.interval_seconds<10:p.error('interval must be at least 10 seconds')
    a.output_root.mkdir(parents=True,exist_ok=True)
    with (a.output_root/'.trusted10.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another trusted-10m processor is running')
        context=load_context(); first=True
        while True:
            records,failures=scan(context,a.output_root)
            if first and a.report:save_report(records,failures,a.report)
            totals={k:sum(r['quality'][k] for r in records) for k in ('isolated_points_withheld','discontinuity_events','discontinuity_points_withheld','adjacent_jump_before','adjacent_jump_after')}
            print(json.dumps({'at':datetime.now().astimezone().isoformat(timespec='seconds'), 'recordings':len(records),'failures':failures,'totals':totals},ensure_ascii=False),flush=True)
            first=False
            if not a.watch:return 1 if failures else 0
            if not failures and sum(r['group'] in (4,5) for r in records)>=91:
                print('All expected group 4/5 recordings have been processed.',flush=True)
                return 0
            time.sleep(a.interval_seconds)


if __name__=='__main__':raise SystemExit(main())
