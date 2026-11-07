import copy
import pytest

from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.reassign_depth_identity_temporal import propose_backwards


def frames_for_short_anchor():
    result=[]
    for i in range(24):
        target={'track_id':8 if i>=18 else None,'surface_corridor_m':[10-i*.05,1.5,1.25 if i>=18 else 1.0],
                'depth_status':'surface_candidate','association_reason':'test'}
        reference={'track_id':1,'surface_corridor_m':[10-i*.04,.5,1.0],
                   'depth_status':'surface_candidate','association_reason':'test'}
        result.append({'frame_index':i,'timestamp_ns':str(1_000_000_000+i*33_000_000),
                       'elapsed_s':i*.033,'observations':[target,reference]})
    return result


def test_short_later_anchor_links_unknown_ids_without_changing_positions():
    frames=frames_for_short_anchor();before=copy.deepcopy(frames)
    updated,changes,info=propose_backwards(frames,8,1)
    assert frames==before
    assert len(changes)==18 and info['anchor_frame']==18 and info['anchor_sample_count']==6
    assert all(o['track_id']==8 for frame in updated for o in frame['observations'][:1])
    for old,new in zip(before,updated):
        assert [x['surface_corridor_m'] for x in old['observations']] == [x['surface_corridor_m'] for x in new['observations']]
    original={'metadata':{'source':'svo'},'frames':before}
    candidate={'metadata':original['metadata'],'frames':updated,'reassignment_candidate':{
        'status':'proposed_not_verified','source_positions_sha256':'hash','target_id':8}}
    assert validate_candidate(original,candidate,'hash')==18


def test_ambiguous_missing_reference_and_low_height_are_not_assigned():
    frames=frames_for_short_anchor()
    frames[16]['observations'].append(copy.deepcopy(frames[16]['observations'][0]))
    frames[14]['observations'][0]['surface_corridor_m'][2]=.3
    frames[12]['observations'][1]['surface_corridor_m']=None
    updated,changes,info=propose_backwards(frames,8,1)
    for index in (12,14,16):
        assert updated[index]['observations'][0]['track_id'] is None
    assert info['rejection_counts']['ambiguous_candidates']>=1
    assert info['rejection_counts']['missing_reference']>=1
    assert updated[17]['observations'][0]['track_id']==8


def test_no_extrapolation_across_long_gap_or_without_anchor():
    frames=frames_for_short_anchor()
    for i in range(5,18): frames[i]['observations'][0]['surface_corridor_m']=None
    updated,changes,info=propose_backwards(frames,8,1)
    assert not changes and info['stop_reason']=='gap_exceeded'
    assert all(updated[i]['observations'][0]['track_id'] is None for i in range(18))
    for i in range(18,24):frames[i]['observations'][0]['surface_corridor_m']=None
    with pytest.raises(ValueError,match='insufficient target'):
        propose_backwards(frames,8,1)


def test_rejects_duplicate_ids_and_nonmonotonic_frames():
    frames=frames_for_short_anchor(); frames[0]['observations'][0]['track_id']=1
    with pytest.raises(ValueError,match='duplicate assigned IDs'):
        propose_backwards(frames,8,1)
    frames=frames_for_short_anchor();frames[1]['timestamp_ns']=frames[0]['timestamp_ns']
    with pytest.raises(ValueError,match='strictly ordered'):
        propose_backwards(frames,8,1)
