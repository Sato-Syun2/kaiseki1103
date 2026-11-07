"""Publish only a validated, separate coordinate identity proposal."""
import argparse
import json
from pathlib import Path
import shutil

from corridor_tracking.portable_depth_replay import validate_candidate
from depth_person_prototype import digest
from zed_sdk_package.tracking_v2.exchange_copy import copy_batch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--local-packet',type=Path,required=True)
    p.add_argument('--shared-packet',type=Path,required=True)
    a=p.parse_args()
    if a.local_packet.exists() or a.shared_packet.exists():
        raise FileExistsError('packet destination already exists')
    original_file=a.original/'positions.json'; candidate_file=a.candidate/'positions.json'
    original_manifest=json.loads((a.original/'manifest.json').read_text(encoding='utf-8-sig'))
    candidate_manifest=json.loads((a.candidate/'manifest.json').read_text(encoding='utf-8-sig'))
    if original_manifest.get('status')!='complete' or original_manifest.get('positions_sha256')!=digest(original_file):
        raise ValueError('original coordinate output failed verification')
    if candidate_manifest.get('status')!='proposed_not_verified' or candidate_manifest.get('files_sha256',{}).get('positions.json')!=digest(candidate_file):
        raise ValueError('candidate output failed verification')
    original=json.loads(original_file.read_text(encoding='utf-8-sig'));candidate=json.loads(candidate_file.read_text(encoding='utf-8-sig'))
    if set(candidate) != {'metadata','frames','reassignment_candidate','walls'}:
        raise ValueError('candidate contains unexpected data')
    count=validate_candidate(original,candidate,digest(original_file))
    a.local_packet.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(candidate_file,a.local_packet/'positions.json')
    meta={'status':'proposed_not_verified','positions_sha256':digest(a.local_packet/'positions.json'),
          'source_positions_sha256':digest(original_file),'source_candidate_manifest_sha256':digest(a.candidate/'manifest.json'),
          'proposed_count':count,'allowed_files':['positions.json','manifest.json']}
    (a.local_packet/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if {x.name for x in a.local_packet.iterdir()} != set(meta['allowed_files']):
        raise ValueError('packet contains unexpected files')
    copied,message=copy_batch(a.local_packet,a.shared_packet);print(message,flush=True)
    if not copied or digest(a.shared_packet/'positions.json')!=meta['positions_sha256']:
        raise OSError('coordinate-only candidate copy failed; local packet retained')
    print(f'Published {count} provisional assignments; no images or depth files copied.')


if __name__=='__main__':main()
