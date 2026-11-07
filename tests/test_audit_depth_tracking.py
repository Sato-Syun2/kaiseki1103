import pytest
from corridor_tracking.audit_depth_tracking import metrics, matched_trial, windows, make_replay


def frame(i, obs):
    return {'frame_index':i,'elapsed_s':i*.1,'timestamp_ns':str(i*100000000+1),
            'observations':[{'track_id':track,'surface_corridor_m':pos,'depth_status':'surface_candidate',
                             'association_reason':'test'} for track,pos in obs]}


def test_two_person_unknown_and_jump_prioritized_without_connecting_unknown():
    frames=[frame(i,[(1,[1 if i<20 else 2,0,1]),(None,[3,0,1])]) for i in range(40)]
    result=metrics(frames,2)
    assert result['rank']=='優先'
    assert result['two_ids_fraction']==0 and result['unassigned_positioned_fraction']==1
    assert result['jump_count']==1
    assert {x['code'] for x in result['flags']} >= {'unassigned_many','two_person_little_overlap','position_jump'}
    page=make_replay({'frames':frames,'walls':{'visible':2,'opposite':0}},'test',result['events'],__import__('pathlib').Path('/tmp'),[])
    assert "if(o.track_id!==null&&j>0" in page and "id===null?'#222'" in page and 'location.hash' in page


def test_solo_does_not_trigger_two_person_under_detection():
    frames=[frame(i,[(1,[i*.01,0,1])]) for i in range(30)]
    result=metrics(frames,1)
    assert result['rank']=='低' and not result['flags']
    for i in range(10,25): frames[i]['observations'].append(frame(i,[(2,[2,0,1])])['observations'][0])
    assert 'solo_multiple' in {x['code'] for x in metrics(frames,1)['flags']}


def test_discontinuous_id_swap_is_flagged_but_normal_crossing_is_not():
    before=frame(0,[(1,[0,0,1]),(2,[2,0,1])])
    after=frame(1,[(1,[2,0,1]),(2,[0,0,1])])
    assert 'possible_id_swap' in {x['code'] for x in metrics([before,after],2)['flags']}
    smooth=[frame(0,[(1,[0,0,1]),(2,[1,0,1])]),
            frame(1,[(1,[.49,0,1]),(2,[.51,0,1])]),
            frame(2,[(1,[1,0,1]),(2,[0,0,1])])]
    assert 'possible_id_swap' not in {x['code'] for x in metrics(smooth,2)['flags']}


def test_condition_mapping_uses_completed_attempt_not_recording_number():
    plan={'plan_sha256':'abc','groups':{'G02':{'trials':[{'global_trial_number':17,'condition_category':'単独歩行'}]}}}
    progress={'plan_sha256':'abc','group':'G02','attempts':{'17':[{'status':'complete','recording_id':'recording_018'}]}}
    assert matched_trial(plan,progress,2,'recording_018')['global_trial_number']==17
    progress['attempts']['18']=[{'status':'complete','recording_id':'recording_018'}]
    with pytest.raises(ValueError,match='2 completed'):
        matched_trial(plan,progress,2,'recording_018')


def test_missing_time_gaps_do_not_form_continuous_events():
    frames=[frame(i,[]) for i in range(20)]
    frames[10]['elapsed_s']+=.2
    assert not windows(frames,[i in (9,10) for i in range(20)],.15)
