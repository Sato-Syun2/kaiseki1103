"""Create separate 10 m, wall-bounded, temporally screened coordinates for groups 6–9."""
import argparse
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
import re
import time

from corridor_tracking.audit_depth_tracking import digest, packet, read
from corridor_tracking.coordinate_only_replay import make_page
from corridor_tracking.filter_shared_positions import save_packet
from corridor_tracking.prepare_group004_005_bundle import scope_calibration
from corridor_tracking.spatial_filter import corridor_bounds
from corridor_tracking.trusted_depth_10m import derive
from corridor_tracking.analysis_exclusions import excluded, load_exclusions

ROOT = Path('/data/experiment_data/kaiseki1103/exchange')
INPUT = ROOT/'depth_group006_009_coordinates_20261107_01'
OUTPUT = ROOT/'depth_group006_009_trusted10_20261107_01'
CALIBRATIONS = ROOT/'calibration_review_metadata_20261107_131230_e63f2ed2'
REPORT = Path('results/tracking_v2/trusted_group006_009_20261107_01')
TAG = re.compile(r'^g(006|007|008|009)_(recording_\d{3})_compact_20261107_01(?:_retry\d+)?$')
WIDTH = 2.376029800280445


def verify_calibration(meta, calibration_path):
    base = read(calibration_path)
    source_hash = digest(calibration_path)
    if meta.get('base_calibration_sha256') != source_hash or meta.get('setup_id') != base['setup_id']:
        raise ValueError('base calibration or setup mismatch')
    actual = meta.get('camera_intrinsics_left')
    expected = base['applies_to']['intrinsics_left']
    if not isinstance(actual, dict) or any(k not in actual or not math.isfinite(float(actual[k])) or
            abs(float(actual[k])-float(expected[k])) > 1. for k in ('fx','fy','cx','cy')):
        raise ValueError('camera intrinsics differ or are invalid')
    # The SSD inventory serializes intrinsics with sorted keys, whereas the SDK
    # timeline used to create the scoped calibration emits this order. JSON key
    # order affects the file hash even though it does not change the values.
    actual_in_sdk_order = {k:actual[k] for k in ('fx','fy','cx','cy')}
    scoped = scope_calibration(base, {'intrinsics_left':actual_in_sdk_order}, source_hash)
    if scoped is None:
        candidates = {source_hash}
    else:
        text = json.dumps(scoped, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        candidates = {hashlib.sha256(x.encode('utf-8')).hexdigest() for x in (text, text.replace('\n','\r\n'))}
    if meta.get('calibration_sha256') not in candidates:
        raise ValueError('scoped calibration hash mismatch')
    return base


def process(path, output=OUTPUT, calibrations=CALIBRATIONS):
    match = TAG.fullmatch(path.name)
    if not match: raise ValueError('unexpected recording name')
    group, recording = int(match[1]), match[2]
    data, manifest = packet(path); meta = data['metadata']
    if (meta.get('group') != group or meta.get('recording') != recording or
            manifest.get('group') != group or manifest.get('recording') != recording or
            meta.get('source_svo_sha256') != manifest.get('source_svo_sha256') or
            not re.fullmatch(r'[0-9a-f]{64}', meta.get('source_svo_sha256','')) or
            not re.fullmatch(r'[0-9a-f]{64}', meta.get('timeline_sha256',''))):
        raise ValueError('source provenance mismatch')
    cal_path = calibrations/f'g{group:03d}_calibration_depth_20261107_01'/'zed_corridor_candidate.json'
    base = verify_calibration(meta, cal_path)
    bounds = corridor_bounds(base, max_x_m=10., fallback_width_m=WIDTH)
    payload, before, spikes, jumps = derive(data, bounds)
    payload['quality_filter']['source_verification'] = 'coordinate packet and calibration hash checked; SVO and timeline remain on Windows'
    record = {'status':'complete','source_positions_sha256':digest(path/'positions.json'),
              'source_manifest_sha256':digest(path/'manifest.json'), 'bounds':bounds,
              'group':group,'recording':recording,'frame_count':len(before),
              'allowed_files':['positions.json','manifest.json'],'quality_filter':payload['quality_filter'],
              'source_verification':'SVO and individual timeline remain on Windows; not independently verified here'}
    dest = output/'originals'/path.name
    save_packet(dest,payload,record)
    stored, saved = packet(dest)
    if stored != payload or saved['source_positions_sha256'] != record['source_positions_sha256']:
        raise ValueError('existing filtered result differs; preserve files')
    return {'tag':path.name,'group':group,'recording':recording,'source_label':meta.get('source_label'),
            'quality':payload['quality_filter'],'data':payload,'spikes':spikes,'jumps':jumps}


def scan(source=INPUT, output=OUTPUT, report=REPORT):
    paths = sorted(p for p in source.iterdir() if p.is_dir() and TAG.fullmatch(p.name)) if source.is_dir() else []
    keys = [(TAG.fullmatch(p.name)[1],TAG.fullmatch(p.name)[2]) for p in paths]
    records, failures = [], []
    for path, key in zip(paths, keys):
        try:
            if keys.count(key)>1: raise ValueError('multiple source runs require review')
            records.append(process(path,output))
        except Exception as exc:
            failures.append({'tag':path.name,'error':str(exc)})
    exclusions=load_exclusions()
    omitted=[{'tag':r['tag'],**excluded(r,exclusions)} for r in records if excluded(r,exclusions)]
    included=[r for r in records if not excluded(r,exclusions)]
    pages = report/'replays'; pages.mkdir(parents=True,exist_ok=True)
    rows = []
    for item in included:
        data = item['data']; tag = item['tag']
        page = make_page(data, f"グループ{item['group']} {item['recording']} 元録画 {item['source_label']}")
        page = page.replace('<p><a href="positions.json">時刻付き座標</a> / <a href="manifest.json">照合記録</a></p>', '')
        (pages/(tag+'.html')).write_text(page,encoding='utf-8')
        rows.append(f'<li><a href="replays/{html.escape(tag)}.html">{html.escape(tag)}</a> 元録画 {html.escape(str(item["source_label"]))}</li>')
    (report/'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>10m再生</title><h1>グループ６〜９：10m範囲の再生</h1><p>校正とIDは暫定。元録画名は表示名です。実験者指定の録画は一覧から除外しています。</p><ul>'+''.join(rows)+'</ul></html>',encoding='utf-8')
    summary = {'at':datetime.now().astimezone().isoformat(timespec='seconds'),'recordings':len(included),'excluded':omitted,'processed_source_count':len(records),'failures':failures,
               'limits':['calibration and IDs provisional','SVO and timelines remain local on Windows',
                         '10 m and corridor walls are based on visible surface candidates']}
    (report/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return failures


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=120)
    a=p.parse_args()
    if a.interval<30:p.error('interval must be at least 30 seconds')
    while True:
        failures = scan()
        if not a.watch:return 1 if failures else 0
        time.sleep(a.interval)


if __name__ == '__main__':
    raise SystemExit(main())
