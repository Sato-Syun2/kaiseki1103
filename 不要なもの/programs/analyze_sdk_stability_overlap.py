#!/usr/bin/env python3
"""Compare SDK 2D anchors against the existing frozen group-3 overlap annotations."""
import argparse
import json
from pathlib import Path
from compare_sdk_stability import load, compare_identity, digest
from corridor_tracking.evaluation import cross_person_anchors
from corridor_tracking.data import joint_ok


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',action='append',default=[])
    p.add_argument('--annotations',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('Output must be a new file')
    base=load(a.baseline); data={'baseline':base}
    for item in a.candidate:
        name,path=item.split('=',1);other=load(Path(path));compare_identity(base,other);data[name]=other
    ann=json.loads(a.annotations.read_text()); reviewed=ann['intervals'][0]['frames']
    times={f['image_timestamp_ns']:f for f in base['frames']}
    samples=[]
    for image in reviewed:
        f=times[image['timestamp_ns']];idx=int(f['frame_index'])
        if digest((base['folder']/f['image_file']).resolve())!=ann['image_sha256'][str(idx)]:raise ValueError('Reviewed image hash does not match')
        sample={'frame':idx,'t':float(f['elapsed_s']),'conditions':{}}
        for name,d in data.items():
            obs=[]
            for i,r in enumerate(d['bodies'].get(idx,[])):
                obs.append(dict(obs_id=f'{idx}:{i}',kind='body',current_support=(r['tracking_state']=='OK' and r.get('is_new','true').lower()!='false' and (not r.get('detection_timestamp_ns') or abs(int(r['detection_timestamp_ns'])-int(r['image_timestamp_ns']))<=1000000)),
                                pixels=r['pixels'],joint_confidence=r['conf'],width=d['camera']['width'],height=d['camera']['height']))
            crossed=cross_person_anchors(obs,image['people'])
            hits={p['person']:[] for p in image['people'] if p.get('bbox') is not None}
            for o in obs:
                if not o['current_support']:continue
                for person in image['people']:
                    if person.get('bbox') is None:continue
                    x0,y0,x1,y1=person['bbox']
                    if any(joint_ok(o,k,need3d=False) and x0<=o['pixels'][k][0]<=x1 and y0<=o['pixels'][k][1]<=y1 for k in [0,2,26]):
                        hits[person['person']].append(o['obs_id'])
            sample['conditions'][name]={'body_observations':len(obs),'crossed':crossed,'person_regions_with_anchor':hits}
        samples.append(sample)
    summary={name:{'images':len(samples),'images_with_crossed_anchors':sum(bool(s['conditions'][name]['crossed']) for s in samples),'crossed_observations':sum(len(s['conditions'][name]['crossed']) for s in samples),'images_with_no_body':sum(s['conditions'][name]['body_observations']==0 for s in samples),
                   'images_with_anchor_in_region':{p:sum(bool(s['conditions'][name]['person_regions_with_anchor'].get(p)) for s in samples) for p in ['red','blue']}} for name in data}
    result={'scope':'10 previously reviewed images in group003 recording002; anchor crossing in approximate person regions is ambiguity, not proof of identification, nor a measure of false detection or recall',
            'annotations_path':str(a.annotations),'annotations_sha256':digest(a.annotations),'summary':summary,'samples':samples}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
