"""Package a small SSD identity-candidate viewer without SDK or image assets."""
import argparse
import json
from pathlib import Path
import shutil

from depth_person_prototype import digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args()
    if a.destination.exists():
        raise FileExistsError('viewer package already exists')
    project=Path(__file__).resolve().parent
    names=['depth_person_prototype.py','corridor_tracking/data.py','corridor_tracking/assignment.py',
           'corridor_tracking/depth_person_comparison.py','corridor_tracking/depth_corridor_replay.py',
           'corridor_tracking/portable_depth_replay.py','corridor_tracking/spatial_filter.py','corridor_tracking/verify_portable_bundle.py',
           'corridor_tracking/bootstrap_identity_viewer.ps1','corridor_tracking/create_group004_identity_replays.ps1',
           'corridor_tracking/create_spatial_replays.ps1']
    a.destination.mkdir(parents=True,exist_ok=False)
    for name in names:
        dst=a.destination/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(project/name,dst)
        if digest(dst)!=digest(project/name):
            raise OSError(f'copy mismatch: {name}')
    manifest={'status':'prepared_not_windows_validated',
              'files_sha256':{f.relative_to(a.destination).as_posix():digest(f) for f in a.destination.rglob('*') if f.is_file()},
              'scope':'candidate identity replay only; no images, depth, SDK or model included'}
    (a.destination/'bundle_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(a.destination)


if __name__=='__main__':main()
