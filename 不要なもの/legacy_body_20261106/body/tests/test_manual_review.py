import copy

import pytest

from body.corridor_tracking.manual_review import exclude_reviewed_observations,label_visual_review_scope


def test_review_exclusion_preserves_original_and_never_bridges_with_derived_points():
    original={'observations':[
        dict(obs_id='a',track_id=1,id_status='associated',xyz=[3,1,1],sigma_m=.2,
             parts=[0],position_source='sdk_estimate',association_reason={},sdk_id=0,t=0),
        dict(obs_id='b',track_id=1,id_status='associated',xyz=[2,1,1],sigma_m=.2,
             parts=[0],position_source='sdk_estimate',association_reason={},sdk_id=0,t=.1),
        dict(obs_id='c',track_id=1,id_status='associated',xyz=[1,1,1],sigma_m=.2,
             parts=[0],position_source='sdk_estimate',association_reason={},sdk_id=0,t=.2)],
        'derived':[dict(frame_index=1,position_source='interpolated')],
        'tracks':[dict(track_id=1,start_s=0,end_s=.2)]}
    saved=copy.deepcopy(original)
    out=exclude_reviewed_observations(original,{'b':{'frame_index':1}})
    assert original==saved
    assert out['observations'][0]==original['observations'][0]
    assert out['observations'][2]==original['observations'][2]
    assert out['observations'][1]['track_id'] is None and out['observations'][1]['xyz'] is None
    assert out['observations'][1]['manual_original']['xyz']==[2,1,1]
    assert out['observations'][1]['association_reason']['manual_evidence']=={'frame_index':1}
    assert out['derived']==[] and out['tracks'][0]['track_id']==1
    with pytest.raises(ValueError,match='absent'):
        exclude_reviewed_observations(original,{'nonexistent':{}})


def test_review_scope_keeps_unreviewed_points_but_distinguishes_them():
    observations=[dict(obs_id=str(i),frame_index=i,t=t,track_id=1,xyz=[i,1,1],
        sigma_m=.2,parts=[0],position_source='sdk_estimate',id_status='associated',
        association_reason={},sdk_id=0) for i,t in enumerate([0,.1,.15,.2,.3])]
    original={'observations':observations,'tracks':[],'derived':[]}
    manual=exclude_reviewed_observations(original,{'1':{'frame_index':1}})
    labelled=label_visual_review_scope(manual,[1,3],.1,.2)
    assert [p['visual_review_status'] for p in labelled['observations']]==[
        'unreviewed_outside_review_window','reviewed_cross_person_excluded',
        'unreviewed_between_images_with_crossing','other_observation_on_reviewed_image_not_adjudicated',
        'unreviewed_outside_review_window']
    assert labelled['observations'][2]['xyz']==observations[2]['xyz']
    assert 'visual_review_status' not in manual['observations'][0]
    with pytest.raises(ValueError,match='outside'):
        label_visual_review_scope(manual,[3],.1,.2)
