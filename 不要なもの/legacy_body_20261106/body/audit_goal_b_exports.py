#!/usr/bin/env python3
"""Audit recorded newness/timestamps and repeated asset hashes in body exports."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from corridor_tracking.data import sha256
from zed_sdk_package.tracking_v2.validate_export import validate_export


def rows(path):
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--roots',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    records=[];failures=[]
    for root in a.roots:
        for path in sorted(root.glob('recording_*/body')):
            try:
                validate_export(path)
                frame_rows=rows(path/'frames.csv');assets=rows(path/'assets.csv')
                counts=Counter();hashes=defaultdict(list);max_delta=0
                for r in frame_rows:
                    counts['frames']+=1;counts['is_new_'+r['is_new']]+=1
                    counts['saved_images']+=bool(r['image_file'])
                    delta=int(r['image_timestamp_ns'])-int(r['detection_timestamp_ns'])
                    counts['timestamp_differences']+=delta!=0;max_delta=max(max_delta,abs(delta))
                for asset in assets:
                    if asset['kind']=='image':hashes[asset['sha256']].append(asset['frame_index'])
                duplicates=[v for v in hashes.values() if len(v)>1]
                manifest=json.loads((path/'manifest.json').read_text())
                records.append(dict(source=str(path),counts=dict(counts),max_abs_timestamp_difference_ns=max_delta,
                    repeated_image_hashes=duplicates,manifest_sha256=sha256(path/'manifest.json'),
                    recorded_elapsed_wall_s=manifest.get('elapsed_wall_s'),scope=manifest.get('completion_scope')))
            except Exception as exc:
                failures.append(dict(source=str(path),error=str(exc)))
    result=dict(records=records,failures=failures,script_sha256=sha256(Path(__file__)),
        caveats=['is_new and timestamps are SDK/exporter recorded metadata, not independent proof of a new detector result',
                 'Unique image hashes do not prove accurate synchronization',
                 'No frozen old-processing baseline was supplied for these recordings'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('recordings:',len(records),'failures:',len(failures),'report:',a.output)
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
