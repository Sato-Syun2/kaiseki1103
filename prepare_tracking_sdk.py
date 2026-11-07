#!/usr/bin/env python3
"""Create a hash-verified NEW SDK distribution; never overwrite the shared old exporter."""
import argparse
import json
from pathlib import Path
import shutil

from corridor_tracking.data import sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--legacy-sdk',type=Path,default=Path('/data/experiment_data/kaiseki1103/zed_sdk_package'))
    a=p.parse_args()
    source=Path(__file__).resolve().parent/'zed_sdk_package/tracking_v2'
    files=sorted([*source.glob('*.py'),*source.glob('*.ps1'),*source.glob('*.md'),*source.glob('*.csv')])
    a.destination.mkdir(parents=True,exist_ok=False)
    hashes={}
    for f in files:
        shutil.copyfile(f,a.destination/f.name)
        hashes[f.name]=sha256(f)
        if sha256(a.destination/f.name)!=hashes[f.name]:
            raise OSError('Copy hash mismatch: '+f.name)
    legacy={f.name:sha256(f) for f in sorted(a.legacy_sdk.glob('*.py'))}
    manifest=dict(package='tracking_v2',version='2.0.0',status='prepared_not_hardware_validated',
                  canonical_source=str(source),files=hashes,legacy_reference_hashes=legacy,
                  legacy_source=str(a.legacy_sdk),hardware_validation='pending_windows_smoke_and_full_svo',
                  tools=['full_frame_body_export','sparse_depth_and_image_export',
                         'test_20261104_batch_orchestration','recursive_svo_directory_body_export',
                         'indexed_batch_continuation','recording_directory_filter',
                         'batch_calibration_depth_export','local_first_export_and_transactional_shared_mirror',
                         'offline_exchange_sync','controlled_sdk_stability_comparison',
                         'selected_frame_depth_export','body18_format_comparison',
                         'contiguous_depth_clip_local_first_orchestration',
                         'inventory_selected_full_recording_depth_clips'])
    (a.destination/'package_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(a.destination)


if __name__=='__main__':
    main()
