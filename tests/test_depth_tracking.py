import pytest
from corridor_tracking.depth_tracking import associate_frames


def person(label, box, xyz):
    return {'label':label, 'region_bbox_xyxy':box, 'surface_camera_image_m':xyz,
            'status':'surface_candidate' if xyz else 'ambiguous_depth_modes'}


def frame(index, second, people):
    return {'frame_index':index,'timestamp_ns':str(1_000_000_000+int(second*1e9)),
            'elapsed_s':second,'review_image':f'images/{index}.jpg','people':people}


def test_ids_follow_positions_when_detector_order_changes():
    a=person('a',[0,0,10,30],[0.,0.,3.]); b=person('b',[60,0,70,30],[1.,0.,5.])
    a2=person('a2',[1,0,11,30],[.02,0.,3.]); b2=person('b2',[59,0,69,30],[.98,0.,5.])
    frames=associate_frames([frame(0,0,[a,b]),frame(1,.1,[b2,a2])])
    assert [o['track_id'] for o in frames[0]['observations']]==[1,2]
    assert [o['track_id'] for o in frames[1]['observations']]==[2,1]


def test_ambiguous_identity_does_not_force_match_or_create_new_track():
    # Two previous tracks become indistinguishable in image space, without depth support.
    frames=associate_frames([frame(0,0,[person('a',[0,0,10,20],None),person('b',[8,0,18,20],None)]),
        frame(1,.1,[person('ambiguous',[4,0,14,20],None)])])
    obs=frames[1]['observations'][0]
    assert obs['track_id'] is None and obs['association_reason']=='ambiguous_or_conflicting_association'
    assert obs['surface_camera_image_m'] is None and obs['position_source']=='no_depth_position'


def test_large_depth_jump_is_not_accepted_as_same_person_or_new_track():
    frames=associate_frames([frame(0,0,[person('a',[0,0,10,20],[0,0,3])]),
        frame(1,.1,[person('a2',[0,0,10,20],[0,0,15])])])
    assert frames[1]['observations'][0]['track_id'] is None
    assert frames[1]['observations'][0]['association_reason']=='ambiguous_or_conflicting_association'


def test_missing_depth_keeps_only_2d_id_and_expired_track_is_not_reused():
    frames=associate_frames([frame(0,0,[person('a',[0,0,10,20],[0,0,3])]),
        frame(1,.1,[person('b',[0,0,10,20],None)]), frame(2,.7,[person('c',[0,0,10,20],[0,0,3])])])
    assert frames[1]['observations'][0]['track_id']==1
    assert frames[1]['observations'][0]['surface_camera_image_m'] is None
    assert frames[2]['observations'][0]['track_id']==2


def test_timeline_must_be_monotonic():
    with pytest.raises(ValueError, match='strictly increasing'):
        associate_frames([frame(0,0,[]),frame(1,0,[])])
