import json
from pathlib import Path
import pytest
from tests.test_recover_merged_depth import make_fixture
from corridor_tracking import recover_merged_depth as recovery
from corridor_tracking import trusted_depth_10m as trusted
from corridor_tracking import build_trusted10_replays as builder
from corridor_tracking import spatial_filter, trajectory_quality


def test_replay_uses_existing_images_and_rejects_changed_coordinates(tmp_path,monkeypatch):
    root,shared,bundle,row,work=make_fixture(tmp_path,monkeypatch)
    tag=recovery.recover(bundle,root,shared,4,'recording_032','compact_test','compact_test')
    original=root/'coordinates'/tag
    raw=json.loads((original/'positions.json').read_text())
    bounds=spatial_filter.corridor_bounds({'visible_wall_Y_m':2.},max_x_m=10,fallback_width_m=2.4)
    payload,_,_,_=trusted.derive(raw,bounds)
    source=tmp_path/'trusted'/tag;source.mkdir(parents=True)
    (source/'positions.json').write_text(json.dumps(payload))
    (source/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':builder.digest(source/'positions.json'),
        'source_positions_sha256':builder.digest(original/'positions.json'),'bounds':bounds,
        'algorithm_sha256':builder.digest(Path(trusted.__file__)),'trajectory_quality_sha256':builder.digest(Path(trajectory_quality.__file__))}))
    output=tmp_path/'replay'/tag
    assert builder.prepare_one(root,bundle,source,output,spatial_filter,trajectory_quality,builder.digest(Path(trusted.__file__)))
    assert (output/'index.html').is_file() and (output/'manifest.json').is_file()
    assert not list(output.glob('*.jpg'))
    assert not builder.prepare_one(root,bundle,source,output,spatial_filter,trajectory_quality,builder.digest(Path(trusted.__file__)))
    payload['frames'][0]['observations'][0]['surface_corridor_m']=[9,9,9]
    (source/'positions.json').write_text(json.dumps(payload));m=json.loads((source/'manifest.json').read_text())
    m['positions_sha256']=builder.digest(source/'positions.json');(source/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='does not match source'):
        builder.prepare_one(root,bundle,source,tmp_path/'other',spatial_filter,trajectory_quality,builder.digest(Path(trusted.__file__)))
