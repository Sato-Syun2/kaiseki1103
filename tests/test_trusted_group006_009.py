import json
import hashlib
import pytest

from corridor_tracking.audit_depth_tracking import digest, packet
from corridor_tracking.trusted_group006_009 import process, verify_calibration
from corridor_tracking.prepare_group004_005_bundle import scope_calibration


def test_ten_m_and_wall_limits_preserve_original_and_source(tmp_path):
    calibration_root=tmp_path/'calibrations'
    calpath=calibration_root/'g006_calibration_depth_20261107_01'/'zed_corridor_candidate.json'
    calpath.parent.mkdir(parents=True)
    intr={'fx':100.,'fy':100.,'cx':50.,'cy':50.}
    cal={'setup_id':'setup6','applies_to':{'intrinsics_left':intr},'visible_wall_Y_m':2.,'other_wall_inference':None}
    calpath.write_text(json.dumps(cal))
    sha=digest(calpath); svo='a'*64
    source=tmp_path/'g006_recording_900_compact_20261107_01';source.mkdir()
    meta={'group':6,'recording':'recording_900','source_svo_sha256':svo,'timeline_sha256':'b'*64,
          'setup_id':'setup6','base_calibration_sha256':sha,'calibration_sha256':sha,
          'camera_intrinsics_left':intr,'source_label':'calibration_001'}
    def obs(x,y):return {'track_id':None,'association_reason':'new','depth_status':'ok','surface_corridor_m':[x,y,1.]}
    data={'metadata':meta,'frames':[{'frame_index':0,'timestamp_ns':'1','elapsed_s':0.,
                                    'observations':[obs(10.,2.),obs(10.1,0.),obs(1.,2.1)]}]}
    (source/'positions.json').write_text(json.dumps(data))
    manifest={'status':'complete','positions_sha256':digest(source/'positions.json'),'source_svo_sha256':svo,
              'group':6,'recording':'recording_900','frame_count':1}
    (source/'manifest.json').write_text(json.dumps(manifest))
    output=tmp_path/'output'
    result=process(source,output,calibration_root)
    assert result['source_label']=='calibration_001'
    derived,_=packet(output/'originals'/source.name)
    assert [o['surface_corridor_m'] for o in derived['frames'][0]['observations']] == [[10.,2.,1.]]
    assert len(json.loads((source/'positions.json').read_text())['frames'][0]['observations'])==3
    meta['calibration_sha256']='f'*64
    (source/'positions.json').write_text(json.dumps(data))
    manifest['positions_sha256']=digest(source/'positions.json')
    (source/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='calibration hash'):
        process(source,output,calibration_root)


def test_scoped_calibration_hash_uses_sdk_intrinsics_order(tmp_path):
    calpath=tmp_path/'calibration.json'
    intr={'fx':100.,'fy':100.,'cx':50.,'cy':50.}
    base={'setup_id':'setup6','applies_to':{'intrinsics_left':intr},'visible_wall_Y_m':2.}
    calpath.write_text(json.dumps(base))
    base_hash=digest(calpath)
    target={'fx':100.01,'fy':100.01,'cx':50.01,'cy':50.01}
    scoped=scope_calibration(base,{'intrinsics_left':target},base_hash)
    raw=(json.dumps(scoped,ensure_ascii=False,indent=2,allow_nan=False)+'\n').replace('\n','\r\n').encode()
    meta={'base_calibration_sha256':base_hash,'setup_id':'setup6',
          'camera_intrinsics_left':dict(sorted(target.items())),
          'calibration_sha256':hashlib.sha256(raw).hexdigest()}
    assert verify_calibration(meta,calpath)==base
    meta['calibration_sha256']='f'*64
    with pytest.raises(ValueError,match='calibration hash'):
        verify_calibration(meta,calpath)
