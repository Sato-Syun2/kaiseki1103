from pathlib import Path
import json
import pytest

from corridor_tracking.prepare_group006_009_bundle import digest, prepare, recording_inventory


def svo(folder):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (folder.name + '.svo2')
    path.write_bytes(b'svo')
    return path.resolve()


def make_inputs(tmp_path):
    roots = {g: tmp_path/f'date_group{g:03d}' for g in range(6, 10)}
    for root in roots.values(): svo(root/'recording_001')
    svo(roots[6]/'recording_002')
    svo(roots[6]/'calibration_001')
    test = tmp_path/'20261106_test'
    svo(test/'test_001'); svo(test/'test_002')
    return roots, test


def test_inventory_preserves_source_and_operator_interpretation(tmp_path):
    roots, test = make_inputs(tmp_path)
    rows = recording_inventory(roots, test)
    by_key = {(r['group'],r['recording']):r for r in rows}
    assert by_key['6','recording_900']['source_label'] == 'calibration_001'
    assert by_key['6','recording_001']['reported_trial'] == 'operator_reported_basic_trial_2'
    assert by_key['6','recording_002']['reported_trial'] == 'operator_reported_basic_trial_3'
    assert by_key['7','recording_901']['source_label'] == 'test_001'
    assert by_key['7','recording_902']['reported_trial'] == 'operator_reported_additional_trial_5_unverified'
    assert by_key['8','recording_001']['reported_trial'] == ''


def test_empty_folder_is_not_mistaken_for_svo(tmp_path):
    roots, test = make_inputs(tmp_path)
    (roots[8]/'recording_007').mkdir()
    assert all(r['recording'] != 'recording_007' for r in recording_inventory(roots, test))


def test_multiple_svo_or_alias_collision_is_an_error(tmp_path):
    roots, test = make_inputs(tmp_path)
    svo(roots[7]/'recording_900')
    with pytest.raises(ValueError, match='alias'):
        recording_inventory(roots, test)
    (roots[7]/'recording_900'/'recording_900.svo2').unlink()
    (roots[7]/'recording_900').rmdir()
    (roots[6]/'recording_001'/'second.svo2').write_bytes(b'svo')
    with pytest.raises(ValueError, match='exactly one'):
        recording_inventory(roots, test)


def test_bundle_uses_each_group_calibration_and_source_provenance(tmp_path, monkeypatch):
    roots, test = make_inputs(tmp_path)
    template = tmp_path/'template'; template.mkdir()
    (template/'tool.py').write_text('pass\n')
    (template/'template_manifest.json').write_text(json.dumps({'files_sha256':{'tool.py':digest(template/'tool.py')}}))
    local = tmp_path/'local'
    intrinsics = {'fx':100.,'fy':100.,'cx':50.,'cy':50.}
    for group in range(6, 10):
        source = svo(roots[group]/('calibration_002' if group == 6 else 'calibration_001'))
        tag = f'g{group:03d}_calibration_depth_20261107_01'
        export = local/'calibration_preparation'/tag
        depth = export/'depth'; depth.mkdir(parents=True)
        camera = {'source_svo':str(source), 'source_svo_sha256':digest(source), 'setup_id':f'setup{group}',
                  'serial_number':1, 'width':100, 'height':100, 'depth_mode':'NEURAL',
                  'coordinate_system':'IMAGE', 'coordinate_units':'meter', 'intrinsics_left':intrinsics}
        (depth/'camera.json').write_text(json.dumps(camera))
        (export/'batch_summary.json').write_text(json.dumps({'status':'validated','setup_id':f'setup{group}',
                                                               'source_svo_sha256':digest(source)}))
        applies = {k:camera[k] for k in ('serial_number','width','height','depth_mode','coordinate_system','coordinate_units','intrinsics_left')}
        cal = {'setup_id':f'setup{group}','provisional':True,'applies_to':applies,'source_depth_dir':str(depth),
               'camera_height_above_floor_m':2.,'visible_wall_Y_m':2.,
               'corridor_basis_camera_image':{'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}}
        candidate = local/'calibration_preparation'/(tag+'_floor_wall_candidate')
        candidate.mkdir(); (candidate/'zed_corridor_candidate.json').write_text(json.dumps(cal))

    def fake_run(cmd, check):
        source = Path(cmd[cmd.index('--svo')+1]); setup = cmd[cmd.index('--setup-id')+1]
        out = Path(cmd[cmd.index('--output')+1])
        camera = {'source_svo':str(source), 'source_svo_sha256':digest(source), 'setup_id':setup,
                  'serial_number':1,'width':100,'height':100,'depth_mode':'NEURAL','coordinate_system':'IMAGE',
                  'coordinate_units':'meter','intrinsics_left':intrinsics}
        out.write_text(json.dumps({'status':'complete','kind':'svo_sdk_timeline_no_body','camera':camera,
                                   'frames':[{'frame_index':'0','svo_frame_index':'0','image_timestamp_ns':'1'}]}))

    monkeypatch.setattr('corridor_tracking.prepare_group006_009_bundle.subprocess.run', fake_run)
    output = tmp_path/'bundle'
    prepare(template, output, roots, test, local, Path('sdk'), tmp_path/'cache')
    import csv
    with (output/'inventory.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    assert len(rows) == 8
    assert next(r for r in rows if r['group']=='6' and r['recording']=='recording_900')['source_label'] == 'calibration_001'
    for row in rows:
        assert json.loads((output/row['calibration']).read_text())['setup_id'] == 'setup'+row['group']
        assert row['calibration_sha256'] == digest(output/row['calibration'])
    with pytest.raises(FileExistsError):
        prepare(template, output, roots, test, local, Path('sdk'), tmp_path/'cache')
