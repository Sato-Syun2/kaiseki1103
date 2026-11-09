import copy
import json

from corridor_tracking.audit_depth_tracking import digest
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.propose_trusted10_identities_live import process


def test_unknown_condition_remains_unverified_and_original_is_unchanged(tmp_path, monkeypatch):
    source_root=tmp_path/'source';source_root.mkdir()
    tag='g006_recording_003_compact_test';source=source_root/tag;source.mkdir()
    original={'metadata':{'group':6,'recording':'recording_003'},'walls':{'visible':2.,'opposite':-0.3},
              'frames':[{'frame_index':0,'timestamp_ns':'1','elapsed_s':0.,
                         'observations':[{'track_id':None,'surface_corridor_m':[1.,0.,1.]}]}]}
    (source/'positions.json').write_text(json.dumps(original))
    (source/'manifest.json').write_text(json.dumps({'status':'complete','frame_count':1,
        'positions_sha256':digest(source/'positions.json'),'bounds':{'max_x_m':10.}}))
    row={'tag':tag,'group':6,'recording':'recording_003','source_label':'recording_003',
         'condition_id':None,'condition_category':None,'condition_basis':'保留',
         'filtered_positions_sha256':digest(source/'positions.json'),'filtered_manifest_sha256':digest(source/'manifest.json')}
    changed=copy.deepcopy(original['frames'])
    changed[0]['observations'][0].update(track_id=3,original_track_id=None,identity_assignment='proposed')
    assignment={'frame_index':0,'elapsed_s':0.,'observation_index':0}
    diagnostics={'anchor_frame':0,'anchor_elapsed_s':0.}
    monkeypatch.setattr('corridor_tracking.propose_trusted10_identities_live.candidate_root',lambda group:source_root)
    monkeypatch.setattr('corridor_tracking.propose_trusted10_identities_live.image_root',lambda row:None)
    monkeypatch.setattr('corridor_tracking.propose_trusted10_identities_live.evaluate',
                        lambda frames: ([(3,1,changed,[assignment],diagnostics)],{3:10,1:10}))
    result=process(row,tmp_path/'out')
    assert result['condition_id'] is None
    assert result['status']=='candidate'
    dest=__import__('pathlib').Path(result['candidate_path']).parent
    proposal=json.loads((dest/'positions.json').read_text())
    assert validate_candidate(original,proposal,digest(source/'positions.json'))==1
    assert '画像・人物との照合前' in (dest/'index.html').read_text()
    assert '実験条件は保留中' in (dest/'index.html').read_text()
    assert json.loads((source/'positions.json').read_text())==original
    assert process(row,tmp_path/'out')['status']=='candidate'


def test_planned_single_walker_is_not_two_person_reassigned(tmp_path, monkeypatch):
    source_root=tmp_path/'source';source_root.mkdir()
    tag='g007_recording_001_compact_test';source=source_root/tag;source.mkdir()
    original={'metadata':{'group':7,'recording':'recording_001'},'frames':[{'frame_index':0,'timestamp_ns':'1',
               'elapsed_s':0.,'observations':[]}]}
    (source/'positions.json').write_text(json.dumps(original))
    (source/'manifest.json').write_text(json.dumps({'status':'complete','frame_count':1,
        'positions_sha256':digest(source/'positions.json'),'bounds':{'max_x_m':10.}}))
    row={'tag':tag,'group':7,'recording':'recording_001','source_label':'recording_001',
         'condition_id':'E01','condition_category':'単独歩行','condition_basis':'plan',
         'filtered_positions_sha256':digest(source/'positions.json'),'filtered_manifest_sha256':digest(source/'manifest.json')}
    monkeypatch.setattr('corridor_tracking.propose_trusted10_identities_live.candidate_root',lambda group:source_root)
    result=process(row,tmp_path/'out')
    assert result['status']=='planned_single_walker'
