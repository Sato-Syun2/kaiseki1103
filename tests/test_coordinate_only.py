import json

import pytest

from corridor_tracking.coordinate_only_replay import validate_input
from corridor_tracking.local_depth_pipeline import publish_coordinates


def test_only_coordinates_are_shared_and_verified(tmp_path):
    row = {'group':'2', 'recording':'recording_001', 'source_svo_sha256':'a'*64,
           'setup_id':'setup', 'calibration_sha256':'b'*64, 'body_manifest_sha256':'c'*64, 'frame_count':'2'}
    meta = {k: row[k] for k in ('recording','source_svo_sha256','setup_id','calibration_sha256','body_manifest_sha256')}
    meta['group'] = 2
    obs = {'track_id':1, 'association_reason':'new_track', 'depth_status':'surface_candidate',
           'surface_corridor_m':[1.,2.,3.], 'surface_camera_image_m':[4.,5.,6.],
           'region_bbox_xyxy':[1,2,3,4], 'detection_label':'detection_1'}
    frames = [{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'review_image':'private.jpg','observations':[obs]},
              {'frame_index':1,'timestamp_ns':'200','elapsed_s':.0000001,'review_image':'private2.jpg','observations':[]}]
    local, shared = tmp_path/'local', tmp_path/'shared'
    publish_coordinates(frames,meta,local,shared)
    assert {x.name for x in shared.iterdir()} == {'positions.json','manifest.json'}
    data=validate_input(shared,row)
    assert data['frames'][0]['observations'][0]['surface_corridor_m']==[1.,2.,3.]
    serialized=(shared/'positions.json').read_text()
    assert 'private.jpg' not in serialized and 'region_bbox' not in serialized and 'surface_camera' not in serialized
    (shared/'private.jpg').write_bytes(b'private')
    with pytest.raises(ValueError,match='unexpected'):
        validate_input(shared,row)
