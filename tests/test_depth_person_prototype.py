import csv
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from depth_person_prototype import digest, estimate_surface, mask_from_region, run
from corridor_tracking.depth_person_comparison import match_regions


def test_depth_modes_refuse_distinct_plausible_surfaces():
    # A sparse bridge makes simple adjacent-gap clustering join background to the person.
    z = np.r_[np.full(30, 3.0), np.arange(3.2, 5.0, 0.2), np.full(25, 5.0)]
    xyz = np.column_stack([np.zeros(len(z)), np.zeros(len(z)), z])
    chosen, info = estimate_surface(xyz, min_points=5, window_m=.5, ambiguity_ratio=.5)
    assert info['status'] == 'ambiguous_depth_modes'
    assert not chosen.any()
    assert 'surface_camera_image_m' not in info


def test_depth_mode_selects_single_surface_and_rejects_missing_data():
    xyz = np.array([[1., 2., 3.], [1.1, 2., 3.1], [.9, 2., 3.2], [0., 0., 12.], [0., 0., np.nan]])
    chosen, info = estimate_surface(xyz, min_points=2, window_m=.5, ambiguity_ratio=.8)
    assert info['status'] == 'surface_candidate'
    assert chosen.tolist() == [True, True, True, False, False]
    assert info['surface_camera_image_m'] == [1., 2., 3.1]
    chosen, info = estimate_surface(xyz, min_points=10)
    assert info['status'] == 'insufficient_depth' and not chosen.any()


def make_depth_export(root):
    root.mkdir(); (root/'images').mkdir()
    image = np.full((12, 12, 3), 100, np.uint8)
    assert cv2.imwrite(str(root/'images/frame.jpg'), image)
    image_hash = digest(root/'images/frame.jpg')
    camera = {'source_svo_sha256': 'a'*64, 'setup_id': 'setup', 'width': 12, 'height': 12,
              'coordinate_system': 'IMAGE (x right, y down, z forward)', 'coordinate_units': 'meter',
              'intrinsics_left': {'fx': 1., 'fy': 1., 'cx': 0., 'cy': 0.}}
    (root/'camera.json').write_text(json.dumps(camera))
    fields = ['sample_index','frame_index','svo_frame_index','image_timestamp_ns','elapsed_s','image_file','image_width','image_height','image_sha256','valid_depth_points']
    with (root/'frames.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        w.writerow(dict(sample_index=0, frame_index=3, svo_frame_index=3, image_timestamp_ns='1234567890123456789',
                        elapsed_s=.1, image_file='images/frame.jpg', image_width=12, image_height=12,
                        image_sha256=image_hash, valid_depth_points=6))
    # Points project onto pixels (1,1), (2,1), (3,1), (7,1), (8,1), (9,1).
    z = np.array([3., 3.1, 3.2, 5., 5.1, 5.2], np.float32)
    xyz = np.column_stack([np.array([1, 2, 3, 7, 8, 9])*z, z, z]).astype(np.float32)
    np.savez(root/'zed_depth_points.npz', points_camera_image_m=xyz, point_frame_index=np.zeros(6, np.int32),
             frame_indices=np.array([0]), frame_timestamps_ns=np.array([1234567890123456789]))
    names = ['camera.json', 'frames.csv', 'zed_depth_points.npz', 'images/frame.jpg']
    (root/'manifest.json').write_text(json.dumps({'status':'complete', 'sample_count':1, 'source_svo_sha256':'a'*64,
        'setup_id':'setup', 'files_sha256':{n:digest(root/n) for n in names}}))
    regions = {'source_svo_sha256':'a'*64, 'description':'synthetic', 'frames':[{'frame_index':3, 'image_sha256':image_hash,
        'regions':[{'label':'one', 'bbox_xyxy':[0,0,5,5]}, {'label':'two','bbox_xyxy':[7,0,11,5]}]}]}
    regions_path = root.parent/'regions.json'; regions_path.write_text(json.dumps(regions))
    return regions_path


def options(root, regions, output):
    return SimpleNamespace(depth=root, regions=regions, output=output, method='manual', model=None, calibration=None,
                           min_points=2, window_m=.5, ambiguity_ratio=.8, erode_px=0, confidence=.15, imgsz=1280)


def test_manual_analysis_uses_depth_only_and_rejects_tampering(tmp_path):
    root = tmp_path/'depth'; regions = make_depth_export(root); out = tmp_path/'out'
    run(options(root, regions, out))
    result = json.loads((out/'results.json').read_text())
    assert result['frames'][0]['timestamp_ns'] == '1234567890123456789'
    assert [p['status'] for p in result['frames'][0]['people']] == ['surface_candidate', 'surface_candidate']
    assert np.allclose([p['surface_camera_image_m'][2] for p in result['frames'][0]['people']], [3.1, 5.1])
    assert (out/'manifest.json').exists() and all((out/p['region_mask']).exists() for p in result['frames'][0]['people'])
    with pytest.raises(FileExistsError):
        run(options(root, regions, out))
    (root/'images/frame.jpg').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash mismatch'):
        run(options(root, regions, tmp_path/'invalid'))
    assert not (tmp_path/'invalid').exists()


def test_manual_regions_reject_out_of_bounds():
    with pytest.raises(ValueError):
        mask_from_region({'bbox_xyxy':[-1, 0, 5, 5]}, 10, 10)


def test_comparison_does_not_force_a_remote_detection_to_match():
    manual = [{'region_bbox_xyxy':[0, 0, 10, 10]}, {'region_bbox_xyxy':[20, 0, 30, 10]}]
    detected = [{'region_bbox_xyxy':[1, 0, 11, 10]}, {'region_bbox_xyxy':[50, 0, 60, 10]}]
    matched, unmatched = match_regions(manual, detected)
    assert list(matched) == [0]
    assert unmatched == [1]


def test_overlapping_regions_do_not_reuse_depth_points(tmp_path):
    root = tmp_path/'depth'; regions = make_depth_export(root)
    data = json.loads(regions.read_text())
    data['frames'][0]['regions'] = [
        {'label':'left', 'bbox_xyxy':[0, 0, 4, 5]},
        {'label':'right', 'bbox_xyxy':[2, 0, 6, 5]},
    ]
    regions.write_text(json.dumps(data))
    out = tmp_path/'out'; run(options(root, regions, out))
    people = json.loads((out/'results.json').read_text())['frames'][0]['people']
    assert [p['overlap_points_excluded'] for p in people] == [2, 2]
    assert [p['status'] for p in people] == ['insufficient_depth', 'insufficient_depth']
def test_manifest_relative_paths_are_portable_on_windows():
    from pathlib import PureWindowsPath
    from depth_person_prototype import manifest_relative_path
    assert manifest_relative_path(PureWindowsPath('C:/run/images/frame.jpg'), PureWindowsPath('C:/run')) == 'images/frame.jpg'
