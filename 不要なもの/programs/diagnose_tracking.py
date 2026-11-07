#!/usr/bin/env python3
"""Freeze legacy tracking counts/input hashes before tuning; optional contact sheets."""
import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def rows(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def legacy_valid(row):
    joints = json.loads(row['keypoints_3d_camera_json'])
    conf = json.loads(row['keypoint_confidence_json'])
    return bool(row['tracking_state'] == 'OK' and joints and conf and conf[0] is not None
                and conf[0] >= 20 and joints[0] and len(joints[0]) == 3
                and all(isinstance(v, (float, int)) and math.isfinite(v) for v in joints[0]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exchange-root', type=Path, default=Path('/data/experiment_data/kaiseki1103/exchange'))
    p.add_argument('--tag', default='20261103')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--contact-sheets', action='store_true')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    records = []
    for n in range(1, 49):
        folder = a.exchange_root / f'recording_{n:03d}' / f'model_comparison_{a.tag}' / 'ACCURATE_GEN2'
        frames, bodies = rows(folder/'frames.csv'), rows(folder/'bodies.csv')
        good = [b for b in bodies if legacy_valid(b)]
        by_id = collections.defaultdict(list)
        for b in good:
            by_id[b['body_id']].append(float(b['elapsed_s']))
        records.append(dict(recording=f'recording_{n:03d}', frames=len(frames), raw=len(bodies),
                            accepted=len(good), states=dict(collections.Counter(b['tracking_state'] for b in bodies)),
                            tracks={k:dict(points=len(v),start=v[0],end=v[-1],
                                           gaps_over_04=sum(y-x > .4 for x,y in zip(v,v[1:]))) for k,v in by_id.items()},
                            hashes={f:digest(folder/f) for f in ['camera.json','frames.csv','bodies.csv']},
                            camera=json.loads((folder/'camera.json').read_text()), source=str(folder)))
        if a.contact_sheets and n in [1,2,3,25,44,48]:
            from PIL import Image, ImageDraw
            indices = sorted(set([1, *range(20,len(frames),20),len(frames)-1]))
            sheet = Image.new('RGB', (1280, ((len(indices)+1)//2)*380), 'white')
            draw = ImageDraw.Draw(sheet)
            for cell, i in enumerate(indices):
                im = Image.open(folder/frames[i]['image_file']).convert('RGB').resize((640,360))
                x,y = cell%2*640, cell//2*380
                sheet.paste(im,(x,y+20))
                draw.text((x+8,y+3),f'{n:03d} sample {i}  t={float(frames[i]["elapsed_s"]):.3f}s  image scale=0.5',fill='black')
            sheet.save(a.output/f'recording_{n:03d}_contact.jpg',quality=94)
    manifest = dict(schema_version=1, purpose='frozen pre-tuning legacy baseline, not ground truth',
                    split={'development':[1,3,25], 'evaluation':[2,44,48]}, records=records,
                    code_hashes={f:digest(f) for f in ['build_group001_replay.py','group001_replay_template.html']})
    (a.output/'baseline.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(dict(recordings=len(records), accepted=sum(r['accepted'] for r in records), output=str(a.output))))


if __name__ == '__main__':
    main()
