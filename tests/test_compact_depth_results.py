import csv
import json
import shutil
import sys
from types import SimpleNamespace

import pytest

from corridor_tracking import compact_depth_results as compact
from corridor_tracking import recompute_compact_depth as recompute
from corridor_tracking.portable_depth_replay import create_replay
from depth_person_prototype import digest


def setup_recording(tmp_path):
    root, bundle = tmp_path/'source', tmp_path/'bundle'
    bundle.mkdir(); (bundle/'cal.json').write_text(json.dumps({'visible_wall_Y_m': 2.1}))
    (bundle/'timeline.json').write_text(json.dumps({'body_manifest_sha256': 'body', 'frames':[{'frame_index':'0', 'image_timestamp_ns':'100'}]}))
    svo = tmp_path/'recording_001.svo2'; svo.write_bytes(b'original svo')
    row = {'group':'2','recording':'recording_001','svo_path':str(svo),
           'source_svo_sha256':'svo','setup_id':'setup', 'calibration_sha256':digest(bundle/'cal.json'),
           'body_manifest_sha256':'body','frame_count':'1','calibration':'cal.json','timeline':'timeline.json'}
    with (bundle/'inventory.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=row); writer.writeheader(); writer.writerow(row)
    tag = 'g002_recording_001_20261105_01'
    merged = root/'analysis'/tag/'merged'; (merged/'images').mkdir(parents=True)
    (merged/'images'/'frame.jpg').write_bytes(b'original image')
    person = {'status':'surface_candidate','surface_corridor_m':[1.,2.,3.], 'region_bbox_xyxy':[1,2,3,4]}
    data = {'metadata': {'source_svo_sha256':'svo','calibration_sha256':row['calibration_sha256']},
            'frames':[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'review_image':'images/frame.jpg','people':[person]}]}
    (merged/'results.json').write_text(json.dumps(data))
    (merged/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256': {
        'results.json':digest(merged/'results.json'), 'images/frame.jpg':digest(merged/'images'/'frame.jpg')}}))
    coords = root/'coordinates'/tag; coords.mkdir(parents=True)
    observation = {'track_id':None,'depth_status':'surface_candidate','surface_corridor_m':[1.,2.,3.],'association_reason':'test'}
    meta = {k:row[k] for k in ('recording','source_svo_sha256','setup_id','calibration_sha256','body_manifest_sha256')}
    meta.update(group=2, person_run_manifest_sha256=digest(merged/'manifest.json'))
    (coords/'positions.json').write_text(json.dumps({'metadata':meta,'frames':[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'observations':[observation]}]}))
    (coords/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':digest(coords/'positions.json')}))
    create_replay(root, bundle, 2, 'recording_001', '20261105_01')
    depth = root/'depth_clips'/f'{tag}_000000_000000'/'depth'; depth.mkdir(parents=True)
    (depth/'zed_depth_points.npz').write_bytes(b'intermediate point cloud')
    part = root/'analysis'/tag/'part_000000'; part.mkdir()
    (part/'duplicate.jpg').write_bytes(b'duplicate')
    return root, bundle, tag


def test_compact_preserves_originals_and_replay_after_relocation(tmp_path, monkeypatch):
    root, bundle, tag = setup_recording(tmp_path)
    output = tmp_path/'compact'
    monkeypatch.setattr(sys, 'argv', ['compact', '--source',str(root),'--bundle',str(bundle),'--output',str(output),'--all-complete'])
    compact.main()
    record = json.loads((output/'compact_manifest.json').read_text())
    assert record['status'] == 'complete' and record['recording_count'] == 1
    assert record['recordings'][0]['source_svo_path'].endswith('.svo2')
    for name, expected in record['files_sha256'].items():
        assert digest(output/name) == expected
    assert not (output/'depth_clips').exists()
    assert not (output/'analysis'/tag/'part_000000').exists()
    assert (root/'depth_clips'/f'{tag}_000000_000000'/'depth'/'zed_depth_points.npz').read_bytes() == b'intermediate point cloud'
    assert (root/'analysis'/tag/'part_000000'/'duplicate.jpg').exists()
    relocated = tmp_path/'relocated'; shutil.move(output, relocated)
    assert (relocated/'depth_replay_index.html').is_file()
    assert (relocated/'analysis'/tag/'merged'/'images'/'frame.jpg').read_bytes() == b'original image'
    assert 'images/frame.jpg' in (relocated/'analysis'/tag/'merged'/'portable_replay.html').read_text()


def test_compact_refuses_changed_source_and_existing_or_nested_output(tmp_path, monkeypatch):
    root, bundle, tag = setup_recording(tmp_path)
    output = tmp_path/'compact'
    (root/'analysis'/tag/'merged'/'images'/'frame.jpg').write_bytes(b'tampered')
    monkeypatch.setattr(sys, 'argv', ['compact','--source',str(root),'--bundle',str(bundle),'--output',str(output),'--tag',tag])
    with pytest.raises(ValueError, match='hash mismatch'):
        compact.main()
    assert (root/'analysis'/tag/'merged'/'images'/'frame.jpg').read_bytes() == b'tampered'
    monkeypatch.setattr(sys, 'argv', ['compact','--source',str(root),'--bundle',str(bundle),'--output',str(root/'nested'),'--tag',tag])
    with pytest.raises(SystemExit): compact.main()
    monkeypatch.setattr(sys, 'argv', ['compact','--source',str(root),'--bundle',str(bundle),'--output',str(output),'--tag',tag])
    with pytest.raises(SystemExit): compact.main()


def test_recompute_uses_original_svo_and_fresh_run_after_provenance_check(tmp_path, monkeypatch):
    root, bundle, tag = setup_recording(tmp_path)
    output = tmp_path/'compact'
    monkeypatch.setattr(sys, 'argv', ['compact', '--source',str(root),'--bundle',str(bundle),'--output',str(output),'--tag',tag])
    compact.main()
    sdk = tmp_path/'sdk_python'; sdk.touch()
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(recompute.subprocess, 'run', run)
    arguments = ['recompute', '--compact-root',str(output),'--tag',tag,'--bundle',str(bundle),'--sdk-python',str(sdk),
                 '--local-root',str(tmp_path/'new_analysis'),'--shared-root',str(tmp_path/'new_coordinates'),'--new-run-id','retry02']
    monkeypatch.setattr(sys, 'argv', arguments)
    assert recompute.main() == 0
    assert calls[0][calls[0].index('--run-id')+1] == 'retry02'
    assert calls[0][calls[0].index('--recording')+1] == 'recording_001'
    assert (tmp_path/'recording_001.svo2').read_bytes() == b'original svo'
    (tmp_path/'recording_001.svo2').unlink()
    with pytest.raises(FileNotFoundError, match='original SVO'):
        recompute.main()
