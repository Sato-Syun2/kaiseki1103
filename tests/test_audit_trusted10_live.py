import json
from pathlib import Path

import pytest

from corridor_tracking.audit_depth_tracking import digest
from corridor_tracking.audit_trusted10_live import check_record, safe_trial
from corridor_tracking.spatial_filter import filter_frames
from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs, withhold_isolated_excursions


def test_condition_exceptions_are_not_guessed():
    plan={'plan_sha256':'p','groups':{'G09':{'trials':[{'global_trial_number':9,'condition_category':'追い越し'}]}}}
    progress={9:{'group':'G09','plan_sha256':'p','attempts':{'9':[{'recording_id':'recording_009','status':'complete'}]}}}
    assert safe_trial(plan,progress,6,'recording_001')[0] is None
    assert safe_trial(plan,progress,7,'recording_901')[0] is None
    assert safe_trial(plan,progress,9,'recording_009')[0] is None


def test_audit_uses_filtered_data_and_checks_source_hashes(tmp_path):
    raw=tmp_path/'g006_recording_001_compact_test';raw.mkdir()
    derived=tmp_path/'derived';derived.mkdir()
    def obs(x, ident):
        return {'track_id':ident,'association_reason':'new','depth_status':'ok','surface_corridor_m':[x,0.,1.]}
    original={'metadata':{'group':6,'recording':'recording_001','source_label':'recording_001'},
              'frames':[{'frame_index':0,'timestamp_ns':'1','elapsed_s':0.,'observations':[obs(1.,1),obs(11.,None)]},
                        {'frame_index':1,'timestamp_ns':'100000001','elapsed_s':.1,'observations':[obs(1.1,1)]}]}
    (raw/'positions.json').write_text(json.dumps(original))
    (raw/'manifest.json').write_text(json.dumps({'status':'complete','frame_count':2,'positions_sha256':digest(raw/'positions.json')}))
    bounds={'max_x_m':10.,'min_y_m':-1.,'max_y_m':2.}
    frames,_,_=filter_frames(original['frames'],bounds)
    frames,_=withhold_isolated_excursions(frames)
    frames,_,_=withhold_discontinuous_pairs(frames)
    screened={'metadata':original['metadata'],'frames':frames}
    (derived/'positions.json').write_text(json.dumps(screened))
    manifest={'status':'complete','frame_count':2,'positions_sha256':digest(derived/'positions.json'),
              'source_positions_sha256':digest(raw/'positions.json'),'source_manifest_sha256':digest(raw/'manifest.json'),'bounds':bounds}
    (derived/'manifest.json').write_text(json.dumps(manifest))
    record,_,_=check_record(raw,derived,{}, {})
    assert record['trial'] is None
    assert record['outside_counts']['outside_x']==1
    assert record['condition_category'] is None
    manifest['source_positions_sha256']='0'*64
    (derived/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='hash mismatch'):
        check_record(raw,derived,{}, {})
