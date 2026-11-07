#!/usr/bin/env python3
"""Verify run outputs, unchanged original inputs, and the frozen legacy baseline."""
import argparse
import json
from pathlib import Path

from corridor_tracking.data import sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--heads-root',type=Path,help='Original separate head export, if this single-recording run used heads')
    p.add_argument('--report',type=Path,required=True,help='New JSON report path')
    a=p.parse_args()
    if a.report.exists():
        p.error('Verification report already exists')
    summary=json.loads((a.run/'summary.json').read_text())
    if summary['failures']:
        raise ValueError('Run has processing failures')
    baseline=json.loads(a.baseline.read_text()) if a.baseline else None
    frozen={r['recording']:r for r in baseline['records']} if baseline else {}
    project=Path(__file__).resolve().parent.parent
    results=[]
    for r in summary['records']:
        folder=a.run/r['recording'];m=json.loads((folder/'manifest.json').read_text())
        source=Path(m['source'])
        if m['status']!='complete':
            raise ValueError('Incomplete analysis: '+r['recording'])
        for name,h in m['output_hashes'].items():
            if sha256(folder/name)!=h:
                raise ValueError('Output changed: '+str(folder/name))
        for name,h in m['input_hashes'].items():
            if name.startswith('heads/'):
                if a.heads_root is None:
                    raise ValueError('Head input verification requires --heads-root')
                input_path=a.heads_root/name.removeprefix('heads/')
            else:
                input_path=source/name
            if sha256(input_path)!=h:
                raise ValueError('Original input changed: '+str(source/name))
        raw=json.loads((folder/'observations.json').read_text())
        for f in raw['frames']:
            if f['image_path']:
                h=m['image_hashes'][f['image']]
                if sha256(Path(f['image_path']))!=h:
                    raise ValueError('Original image changed: '+f['image_path'])
                replay_image=folder/'images'/f'{f["frame_index"]:07d}.jpg'
                if replay_image.exists() and sha256(replay_image)!=h:
                    raise ValueError('Replay image changed: '+str(replay_image))
        if r['recording'] in frozen:
            b=frozen[r['recording']]
            if any(m['input_hashes'].get(k)!=v for k,v in b['hashes'].items()):
                raise ValueError('Input differs from frozen baseline: '+r['recording'])
            if r['metrics']['baseline_points']!=b['accepted']:
                raise ValueError('Legacy acceptance regression: '+r['recording'])
        differing_code=[name for name,h in m['code_hashes'].items() if not (project/name).is_file() or sha256(project/name)!=h]
        results.append(dict(recording=r['recording'],files_verified=len(m['output_hashes']),
                            images_verified=len(m['image_hashes']),baseline_matches=r['recording'] in frozen,
                            code_changed_since_run=differing_code))
    report=dict(status='verified',recordings=len(results),records=results,
                note='Code differences are recorded; byte-identical inputs/outputs and baseline acceptance are required')
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))


if __name__=='__main__':
    main()
