import copy

import pytest

from corridor_tracking.reassign_depth_identity import _EXCEPTION_PLAN, pixel_from_corridor, propose, trial_condition


def make_frames():
    frames = []
    for i in range(20):
        target = {'track_id':3 if i >= 10 else None, 'surface_corridor_m':[10-i*.05,1.5,1.0],
                  'depth_status':'surface_candidate', 'association_reason':'test'}
        reference = {'track_id':1, 'surface_corridor_m':[10-i*.04,.5,1.0],
                     'depth_status':'surface_candidate', 'association_reason':'test'}
        frames.append({'frame_index':i, 'timestamp_ns':str(1_000_000_000+i*33_000_000),
                       'elapsed_s':i*.033, 'observations':[target,reference]})
    return frames


def test_backwards_reassociation_keeps_uncertain_and_never_changes_positions():
    frames=make_frames()
    frames[8]['observations'].append(copy.deepcopy(frames[8]['observations'][0]))
    frames[6]['observations'][0]['surface_corridor_m'][2]=.2
    frames[5]['observations'][1]['surface_corridor_m']=None
    frames[3]['observations'][0]['surface_corridor_m']=None
    before=copy.deepcopy(frames)
    updated, changes, info=propose(frames,3,1)
    assert frames == before
    assert {x['frame_index'] for x in changes} == {0,1,2,4,7,9}
    for i in (3,5,6,8):
        assert updated[i]['observations'][0]['track_id'] is None
    assert updated[7]['observations'][0]['track_id'] == 3
    assert updated[7]['observations'][0]['identity_assignment'] == 'proposed'
    assert updated[7]['observations'][0]['surface_corridor_m'] == before[7]['observations'][0]['surface_corridor_m']
    assert info['anchor_frame'] == 10 and info['rejection_counts']['ambiguous_candidates'] == 1


def test_condition_requires_matching_recording_plan():
    trial={'global_trial_number':1,'condition_category':'追い越し','condition_id':'E03'}
    plan={'plan_sha256':'matching','groups':{'G02':{'trials':[trial]}}}
    progress={'group':'G02','plan_sha256':'matching','attempts':{'1':[{'recording_id':'recording_001','status':'complete'}]}}
    assert trial_condition(plan,progress,2,'recording_001')['condition_id'] == 'E03'
    progress['plan_sha256']='different'
    with pytest.raises(ValueError,match='do not match'):
        trial_condition(plan,progress,2,'recording_001')


@pytest.mark.parametrize('group,trial_number,blocked',[(6,1,True),(6,12,True),(7,54,False),
                                                       (7,55,True),(9,8,False),(9,9,True)])
def test_reported_condition_exceptions_prevent_unsafe_automatic_mapping(group,trial_number,blocked):
    trial={'global_trial_number':trial_number,'condition_category':'追い越し','condition_id':'example'}
    plan={'plan_sha256':_EXCEPTION_PLAN,'groups':{f'G{group:02d}':{'trials':[trial]}}}
    progress={'group':f'G{group:02d}','plan_sha256':_EXCEPTION_PLAN,
              'attempts':{str(trial_number):[{'recording_id':'recording_001','status':'complete'}]}}
    if blocked:
        with pytest.raises(ValueError,match='exception requires review'):
            trial_condition(plan,progress,group,'recording_001')
    else:
        assert trial_condition(plan,progress,group,'recording_001') == trial


def test_reported_exceptions_do_not_apply_to_a_different_plan():
    trial={'global_trial_number':9,'condition_category':'追い越し','condition_id':'example'}
    plan={'plan_sha256':'another-plan','groups':{'G09':{'trials':[trial]}}}
    progress={'group':'G09','plan_sha256':'another-plan',
              'attempts':{'9':[{'recording_id':'recording_009','status':'complete'}]}}
    assert trial_condition(plan,progress,9,'recording_009') == trial


def test_project_corridor_to_original_image():
    camera={'intrinsics_left':{'fx':100.,'fy':100.,'cx':100.,'cy':100.}, 'width':1000,'height':1000}
    cal={'floor_plane_camera_image':{'normal_down':[0,0,1],'offset_m':0},
         'corridor_basis_camera_image':{'X_into_hallway':[1,0,0],'Y_positive_toward_ZED_visible_far_wall':[0,1,0],'Z_up':[0,0,1]}}
    assert pixel_from_corridor([1,2,4],camera,cal) == [125.,150.]
    assert pixel_from_corridor([1,2,-4],camera,cal) is None
