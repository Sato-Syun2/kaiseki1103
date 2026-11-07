import json
from pathlib import Path
import sys

import pytest

from corridor_tracking import prepare_group004_005_bundle as prep


def test_prepares_both_groups_and_reuses_cached_svo_timeline(tmp_path, monkeypatch):
    template=tmp_path/'template';(template/'timelines').mkdir(parents=True)
    group5=tmp_path/'g5'; (group5/'recording_001').mkdir(parents=True)
    svo5=group5/'recording_001'/'recording_001.svo2';svo5.write_bytes(b'five')
    svo4=tmp_path/'four.svo2';svo4.write_bytes(b'four')
    camera={'setup_id':'setup','coordinate_system':'IMAGE','coordinate_units':'meter','serial_number':123,
            'intrinsics_left':{'fx':1000.,'fy':1000.,'cx':500.,'cy':300.},
            'source_svo_sha256':prep.digest(svo4)}
    frames=[{'frame_index':'0','svo_frame_index':'0','image_timestamp_ns':'100'},
            {'frame_index':'1','svo_frame_index':'1','image_timestamp_ns':'200'}]
    tl4=template/'timelines/g004_recording_001.json'
    tl4.write_text(json.dumps({'camera':camera,'frames':frames,'body_manifest_sha256':'body'}))
    rows=[{'group':'4','recording':'recording_001','svo_path':str(svo4),'setup_id':'setup',
           'source_svo_sha256':prep.digest(svo4),'frame_count':'2','body_manifest_sha256':'body',
           'timeline':'timelines/g004_recording_001.json'}]
    (template/'group4_inventory.json').write_text(json.dumps(rows))
    (template/'group5_recordings.json').write_text('["recording_001"]')
    hashes={p.relative_to(template).as_posix():prep.digest(p) for p in template.rglob('*') if p.is_file()}
    (template/'template_manifest.json').write_text(json.dumps({'files_sha256':hashes}))
    export=tmp_path/'export';(export/'depth').mkdir(parents=True)
    (export/'batch_summary.json').write_text(json.dumps({'status':'validated','setup_id':'setup','source_svo_sha256':'a'*64}))
    cc=dict(camera,source_svo_sha256='a'*64,coordinate_system='IMAGE (x right, y down, z forward)')
    (export/'depth/camera.json').write_text(json.dumps(cc))
    cal={'setup_id':'setup','provisional':True,'source_depth_dir':str(export/'depth'),
         'applies_to':{'coordinate_system':cc['coordinate_system'],'coordinate_units':'meter','serial_number':123,
                       'intrinsics_left':cc['intrinsics_left']},
         'camera_height_above_floor_m':2.3,'visible_wall_Y_m':2.1,
         'corridor_basis_camera_image':{'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}}
    cal_path=tmp_path/'candidate.json';cal_path.write_text(json.dumps(cal))
    cache=tmp_path/'cache';cache.mkdir()
    cam5=dict(camera,source_svo_sha256=prep.digest(svo5),
              intrinsics_left={'fx':1000.2,'fy':1000.2,'cx':500.,'cy':300.})
    (cache/'recording_001.json').write_text(json.dumps({'kind':'svo_sdk_timeline_no_body','status':'complete',
                                                       'camera':cam5,'frames':frames}))
    monkeypatch.setattr(prep.subprocess,'run',lambda *a,**kw:pytest.fail('cached timeline should be reused'))
    output=tmp_path/'out';sdk=tmp_path/'python';sdk.touch()
    monkeypatch.setattr(sys,'argv',['prepare','--template',str(template),'--output',str(output),
        '--calibration',str(cal_path),'--calibration-export',str(export),'--group5-root',str(group5),
        '--timeline-cache',str(cache),'--sdk-python',str(sdk)])
    prep.main()
    manifest=json.loads((output/'bundle_manifest.json').read_text())
    assert manifest['recording_count']==2
    timeline=output/'timelines/g005_recording_001.json'
    assert manifest['files_sha256']['timelines/g005_recording_001.json']==prep.digest(timeline)
    assert (output/'inventory.csv').is_file()
    scoped=json.loads((output/'calibrations/g005_recording_001.json').read_text())
    assert scoped['applies_to']['intrinsics_left']==cam5['intrinsics_left']
    assert scoped['scope_transfer']['source_calibration_sha256']==prep.digest(cal_path)
    with pytest.raises(FileExistsError):
        prep.main()

    changed=dict(camera,intrinsics_left={'fx':1002.,'fy':1000.,'cx':500.,'cy':300.})
    with pytest.raises(ValueError,match='intrinsics_left'):
        prep.validate_calibration(cal, json.loads((export/'batch_summary.json').read_text()), cc,
                                  changed, export, max_intrinsics_delta_px=1.0)
