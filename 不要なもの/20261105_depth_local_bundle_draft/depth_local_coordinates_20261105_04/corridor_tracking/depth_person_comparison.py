"""Compare per-frame depth prototypes using approximate manual boxes, not ground truth."""
import argparse
import csv
import html
import json
from pathlib import Path

import cv2
import numpy as np

from corridor_tracking.assignment import linear_sum_assignment
from depth_person_prototype import digest, safe_asset


def load_run(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('status') != 'complete':
        raise ValueError('prototype output is incomplete')
    hashes = manifest.get('files_sha256', {})
    if 'results.json' not in hashes:
        raise ValueError('results missing from prototype manifest')
    for name, expected in hashes.items():
        if digest(safe_asset(root, name)) != expected:
            raise ValueError(f'prototype output hash mismatch: {name}')
    return json.loads((root/'results.json').read_text())


def box_iou(a, b):
    if a is None or b is None:
        return 0.0
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    area_a = (a[2]-a[0])*(a[3]-a[1]); area_b = (b[2]-b[0])*(b[3]-b[1])
    return overlap/(area_a+area_b-overlap) if area_a+area_b-overlap else 0.


def match_regions(reference, detected, threshold=.25):
    if not reference or not detected:
        return {}, list(range(len(detected)))
    scores = np.array([[box_iou(a['region_bbox_xyxy'], b['region_bbox_xyxy']) for b in detected] for a in reference])
    # Dummy columns allow the assignment to leave weak matches unassigned.
    cost = np.concatenate([1-scores, np.full((len(reference), len(reference)), 1-threshold)], axis=1)
    rows, cols = linear_sum_assignment(cost)
    matches = {int(i): (int(j), float(scores[i, j])) for i, j in zip(rows, cols) if j < len(detected) and scores[i, j] >= threshold}
    used = {x[0] for x in matches.values()}
    return matches, [j for j in range(len(detected)) if j not in used]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manual', 'box', 'mask', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('output already exists')
    roots = {name: getattr(args, name).resolve() for name in ('manual', 'box', 'mask')}
    runs = {name: load_run(root) for name, root in roots.items()}
    for name, run in runs.items():
        if run['metadata']['method'] != name:
            raise ValueError('run method mismatch: '+name)
        if run['metadata']['depth_manifest_sha256'] != runs['manual']['metadata']['depth_manifest_sha256']:
            raise ValueError('runs do not use the same depth export')
        timeline = [(f['frame_index'], f['timestamp_ns'], f['image_sha256']) for f in run['frames']]
        if timeline != [(f['frame_index'], f['timestamp_ns'], f['image_sha256']) for f in runs['manual']['frames']]:
            raise ValueError('run image timelines differ')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'images').mkdir()
    rows = []; sections = []; frame_summary = []
    for k, manual in enumerate(runs['manual']['frames']):
        candidates = {name:runs[name]['frames'][k] for name in ('box', 'mask')}
        matches = {}; unmatched = {}
        for mode in candidates:
            matches[mode], unmatched[mode] = match_regions(manual['people'], candidates[mode]['people'])
        for i, reference in enumerate(manual['people']):
            for mode in ('box','mask'):
                match = matches[mode].get(i)
                found = candidates[mode]['people'][match[0]] if match else None
                rows.append({'frame_index':manual['frame_index'], 'elapsed_s':manual['elapsed_s'], 'reference':reference['label'],
                    'reference_status':reference['status'], 'reference_z_m':(reference.get('surface_camera_image_m') or [None]*3)[2],
                    'method':mode, 'detection':found['label'] if found else '', 'bbox_iou':round(match[1], 3) if match else '',
                    'status':found['status'] if found else 'unmatched',
                    'z_m':(found.get('surface_camera_image_m') or [None]*3)[2] if found else None})
        all_people = manual['people'] + candidates['box']['people'] + candidates['mask']['people']
        boxes = [p['region_bbox_xyxy'] for p in all_people if p['region_bbox_xyxy']]
        images = [cv2.imread(str(roots[m]/runs[m]['frames'][k]['review_image'])) for m in ('manual','box','mask')]
        if any(image is None for image in images):
            raise ValueError('missing review image')
        h,w = images[0].shape[:2]
        if boxes:
            x0=max(0, min(b[0] for b in boxes)-30); y0=max(0, min(b[1] for b in boxes)-30)
            x1=min(w, max(b[2] for b in boxes)+30); y1=min(h, max(b[3] for b in boxes)+30)
        else: x0,y0,x1,y1=0,0,w,h
        panels=[]
        for mode, image in zip(('manual','box','mask'), images):
            crop=image[y0:y1,x0:x1]; width=400; height=max(1,round(crop.shape[0]*width/crop.shape[1]))
            panel=cv2.resize(crop,(width,height)); cv2.rectangle(panel,(0,0),(width,28),(0,0,0),-1)
            cv2.putText(panel,mode,(8,20),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1,cv2.LINE_AA);panels.append(panel)
        name=f'frame_{manual["frame_index"]:08d}.jpg'
        if not cv2.imwrite(str(args.output/'images'/name),np.concatenate(panels,axis=1)):
            raise OSError('could not write comparison image')
        frame_rows=[r for r in rows if r['frame_index']==manual['frame_index']]
        lines=''.join('<tr>'+''.join('<td>'+html.escape(str(r[x] if r[x] is not None else '—'))+'</td>' for x in ('reference','reference_status','method','detection','bbox_iou','status','z_m'))+'</tr>' for r in frame_rows)
        sections.append(f'<section><h2>Frame {manual["frame_index"]} / {manual["elapsed_s"]:.3f}秒</h2><img src="images/{name}"><table><tr><th>手動の仮枠</th><th>仮枠の状態</th><th>方法</th><th>検出</th><th>枠IoU</th><th>状態</th><th>深度Z m</th></tr>{lines}</table><p>仮枠と対応しない検出: box {len(unmatched["box"])}, mask {len(unmatched["mask"])}</p></section>')
        frame_summary.append({'frame_index':manual['frame_index'], 'unmatched_detections':{n:len(v) for n,v in unmatched.items()}})
    fields=['frame_index','elapsed_s','reference','reference_status','reference_z_m','method','detection','bbox_iou','status','z_m']
    with (args.output/'comparison.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    payload={'scope':'approximate fixed manual boxes; IoU matching is provisional and not ground truth or an identity track',
             'depth_manifest_sha256':runs['manual']['metadata']['depth_manifest_sha256'],
             'input_manifests':{name:digest(root/'manifest.json') for name,root in roots.items()},
             'match_threshold_bbox_iou':.25,'frames':frame_summary,'rows':rows}
    (args.output/'comparison.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    page='<!doctype html><meta charset="utf-8"><title>人物深度の比較</title><style>body{font:16px sans-serif;margin:24px}img{max-width:100%}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:5px}section{border-top:1px solid #bbb}</style><h1>録画の人物領域と深度の試作比較</h1><p>左から手動の仮枠、検出枠、人物マスク。色の点は選択候補、赤点は除外、十字は表面代表点。手動枠は全フレームで固定した概略で正解ではありません。IoUは枠の重なりによる仮対応でありIDや精度の評価ではありません。深度の閾値は未検証です。</p><p><a href="comparison.csv">比較CSV</a> / <a href="comparison.json">比較条件と全行</a></p>'+''.join(sections)
    (args.output/'index.html').write_text(page,encoding='utf-8')
    files=sorted(p for p in args.output.rglob('*') if p.is_file())
    (args.output/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':{p.relative_to(args.output).as_posix():digest(p) for p in files}},indent=2)+'\n')
    print(f'Saved {len(frame_summary)} frames to {args.output}')


if __name__ == '__main__':
    main()
