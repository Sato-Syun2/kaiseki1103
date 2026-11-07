import json
import sys

import pytest

from corridor_tracking import build_group004_pilot_bundle as builder


def test_known_image_coordinate_names_are_equivalent():
    assert builder.same_image_coordinates('IMAGE', 'IMAGE (x right, y down, z forward)', 'IMAGE')
    assert not builder.same_image_coordinates('IMAGE', 'IMAGE (x left, y down, z forward)')
    assert not builder.same_image_coordinates('IMAGE', None)


def test_build_checks_coordinates_before_output(tmp_path, monkeypatch):
    template = tmp_path/'template'
    (template/'timelines').mkdir(parents=True)
    camera = {'setup_id': 'test', 'coordinate_system': 'IMAGE', 'coordinate_units': 'meter',
              'source_svo_sha256': 'a'*64, 'serial_number': 123}
    timeline = template/'timelines/g004_recording_006.json'
    timeline.write_text(json.dumps({'camera': camera}), encoding='utf-8')
    inv = template/'pilot_inventory.json'
    inv.write_text(json.dumps({'group': '4', 'recording': 'recording_006'}), encoding='utf-8')
    (template/'template_manifest.json').write_text(json.dumps({'files_sha256': {
        'timelines/g004_recording_006.json': builder.digest(timeline),
        'pilot_inventory.json': builder.digest(inv)}}), encoding='utf-8')
    export = tmp_path/'export'
    (export/'depth').mkdir(parents=True)
    depth_camera = dict(camera, coordinate_system='IMAGE (x right, y down, z forward)')
    (export/'depth/camera.json').write_text(json.dumps(depth_camera), encoding='utf-8')
    (export/'batch_summary.json').write_text(json.dumps({'status': 'validated', 'setup_id': 'test',
                                                        'source_svo_sha256': 'a'*64}), encoding='utf-8')
    cal = {'setup_id': 'test', 'provisional': True, 'source_depth_dir': str(export/'depth'),
           'applies_to': {'coordinate_system': depth_camera['coordinate_system'], 'coordinate_units': 'meter', 'serial_number': 123},
           'camera_height_above_floor_m': 2.3, 'visible_wall_Y_m': 2.1,
           'corridor_basis_camera_image': {'x': [1, 0, 0], 'y': [0, 1, 0], 'z': [0, 0, 1]}}
    cal_path = tmp_path/'candidate.json'
    cal_path.write_text(json.dumps(cal), encoding='utf-8')
    output = tmp_path/'output'
    monkeypatch.setattr(sys, 'argv', ['builder', '--template', str(template), '--calibration', str(cal_path),
                                      '--calibration-export', str(export), '--output', str(output)])
    builder.main()
    assert (output/'bundle_manifest.json').is_file()
    assert (output/'inventory.csv').is_file()

    depth_camera['coordinate_system'] = 'RIGHT_HANDED_Y_UP'
    (export/'depth/camera.json').write_text(json.dumps(depth_camera), encoding='utf-8')
    output2 = tmp_path/'rejected'
    sys.argv[-1] = str(output2)
    with pytest.raises(ValueError, match='coordinate_system'):
        builder.main()
    assert not output2.exists()
