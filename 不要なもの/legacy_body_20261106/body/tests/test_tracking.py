import itertools
import json
import csv

import cv2
import numpy as np
import pytest

from corridor_tracking.assignment import linear_sum_assignment
from corridor_tracking.data import load_export,transform
from body.corridor_tracking.tracker import Config,run_tracker,apply_anchors
from body.corridor_tracking.evaluation import diagnostics,time_weights


def observation(i,t,x=10.,y=1.,sdk=0,person=0,root=True,state='OK'):
    xyz=np.array([x,y,.9])
    joints=[xyz.tolist() for _ in range(34)]
    offsets={2:[0,0,.3],5:[0,-.2,.4],12:[0,.2,.4],18:[0,-.12,0],22:[0,.12,0],26:[0,0,.7]}
    for k,v in offsets.items():
        joints[k]=(xyz+v).tolist()
    uv=np.array([640+y*80,150+(15-x)*20])
    pixels=[uv.tolist() for _ in range(34)]
    for k,v in offsets.items():
        pixels[k]=(uv+[v[1]*80,-v[2]*70]).tolist()
    c=[99.]*34;c[0]=99. if root else 0.
    return dict(obs_id=f'{i}:{person}',frame_index=i,sample_index=i,t=t,
                timestamp_ns=str(10**18+round(t*1e9)),sdk_id=sdk,kind='body',state=state,
                pixels=pixels,joints=joints,joint_confidence=c,width=1280,height=720,
                confidence=99.,is_new=True,current_support=state=='OK',root_valid=root and state=='OK',
                legacy_valid=root and state=='OK',appearance=np.eye(18)[person].tolist())


def data(observations,times=None):
    times=times if times is not None else sorted(set((o['frame_index'],o['t']) for o in observations))
    frames=[dict(frame_index=i,t=t,timestamp_ns=str(10**18+round(t*1e9))) for i,t in times]
    return dict(observations=observations,frames=frames)


def test_assignment_matches_exhaustive_rectangular():
    rng=np.random.default_rng(19)
    for n,m in [(1,4),(2,3),(3,2),(4,4)]:
        for _ in range(8):
            a=rng.normal(size=(n,m))
            r,c=linear_sum_assignment(a)
            b=a if n<=m else a.T
            optimum=min(sum(b[i,j] for i,j in enumerate(p)) for p in itertools.permutations(range(b.shape[1]),b.shape[0]))
            assert a[r,c].sum()==pytest.approx(optimum)
            assert len(set(r))==len(r) and len(set(c))==len(c)


def test_overtake_and_sdk_id_swap_keep_people_separate():
    obs=[]
    for i in range(20):
        t=i*.1
        obs += [observation(i,t,10-t,1,0 if i<10 else 7,0),
                observation(i,t,11-2*t,1.6,7 if i<10 else 0,1)]
    r=run_tracker(data(obs),Config())
    identities=[{p['track_id'] for p in r['observations'] if p['obs_id'].endswith(f':{person}')} for person in [0,1]]
    assert all(len(v)==1 and None not in v for v in identities)
    assert identities[0]!=identities[1]


def test_sdk_id_change_does_not_fragment():
    obs=[observation(i,i*.1,10-i*.1,sdk=0 if i<5 else 42) for i in range(12)]
    r=run_tracker(data(obs),Config())
    assert len({p['track_id'] for p in r['observations']})==1
    assert len(r['tracks'][0]['sdk_ids'])==2


def test_same_sdk_id_impossible_jump_splits():
    obs=[observation(i,i*.1,15-i*.1) for i in range(5)]+[observation(5,.5,3,sdk=0)]
    r=run_tracker(data(obs),Config())
    assert r['observations'][0]['track_id']!=r['observations'][-1]['track_id']


def test_pairwise_pixel_prediction_resists_alternating_frame_jitter():
    from body.corridor_tracking.tracker import Track
    times=np.arange(8)/30
    next_obs=observation(8,8/30)
    next_obs['pixels'][0]=[100*8/30,0.]
    history=[(float(t),np.array([100*t+jitter,0.]),25.)
             for t,jitter in zip(times,[0,4,0,4,0,4,0,4])]
    adjacent=Track(1,observation(0,0),Config());adjacent.pixel_history=history
    pairwise=Track(1,observation(0,0),Config(pixel_velocity_method='pairwise'));pairwise.pixel_history=history
    assert pairwise.pixel_forecast_error(next_obs)<.1
    assert adjacent.pixel_forecast_error(next_obs)>.7
    with pytest.raises(ValueError,match='pixel velocity method'):
        Config.from_dict({'pixel_velocity_method':'unknown'})


def test_experimental_sdk_hold_leaves_outlier_unassigned_and_recovers():
    obs=[observation(i,i*.1,10-i*.05) for i in range(4)]
    obs += [observation(4,.4,3), observation(5,.5,9.75)]
    r=run_tracker(data(obs),Config(unmatched_sdk_hold_s=.25))
    outlier, recovery = r['observations'][-2:]
    assert outlier['track_id'] is None and outlier['xyz'] is None
    assert outlier['association_reason']['reason']=='unmatched_recent_sdk_id_hold'
    assert recovery['track_id']==r['observations'][0]['track_id']
    assert recovery['xyz'] is not None


def test_experimental_sdk_hold_expires_and_does_not_suppress_other_ids():
    obs=[observation(0,0,10,sdk=0), observation(1,.1,3,sdk=0),
         observation(1,.1,4,sdk=5,person=1), observation(3,.3,3,sdk=0)]
    r=run_tracker(data(obs),Config(unmatched_sdk_hold_s=.2))
    points={p['obs_id']:p for p in r['observations']}
    assert points['1:0']['track_id'] is None
    assert points['1:1']['track_id'] is not None
    assert points['3:0']['track_id'] is not None
    assert points['3:0']['track_id']!=points['0:0']['track_id']


def test_partial_recovery_uses_visible_geometry_and_keeps_source():
    obs=[observation(i,i*.1,10-i*.1,root=i>=3) for i in range(10)]
    r=run_tracker(data(obs),Config())
    assert all(p['xyz'] is not None for p in r['observations'])
    assert all(p['position_source']=='partial_observation_estimate' for p in r['observations'][:3])
    assert all(p['xyz'][0]==pytest.approx(10-p['t']) for p in r['observations'])
    assert obs[0]['joint_confidence'][0]==0 # raw observation is intact


def test_searching_and_stale_are_not_current_measurements():
    obs=[observation(i,i*.1) for i in range(5)]
    obs[3].update(state='SEARCHING',root_valid=False,current_support=False,legacy_valid=False)
    obs[4].update(is_new=False,root_valid=False,current_support=False)
    r=run_tracker(data(obs),Config())
    assert all(p['xyz'] is None for p in r['observations'][3:])


def test_long_occlusion_is_not_bridged():
    obs=[observation(0,0),observation(1,.1),observation(50,5)]
    r=run_tracker(data(obs,[(i,i*.1) for i in range(51)]),Config())
    assert r['observations'][0]['track_id']!=r['observations'][-1]['track_id']
    assert not any(.4 < p['t'] < 4.9 for p in r['derived'])


def test_interpolation_does_not_inflate_supported_count():
    obs=[observation(0,0),observation(2,.2,x=9.8)]
    d=data(obs,[(0,0),(1,.1),(2,.2)])
    r=run_tracker(d,Config(interpolate_s=.3))
    assert len(r['derived'])==1 and r['derived'][0]['position_source']=='interpolated'
    assert diagnostics(d,r)['candidate_points']==2


def test_partial_foreground_depth_disagreement_is_rejected():
    obs=[observation(i,i*.1,root=i!=5) for i in range(10)]
    obs[5]['joints'][26][0]+=5
    r=run_tracker(data(obs),Config())
    assert r['observations'][5]['xyz'] is None


def test_full_occlusion_without_prior_geometry_stays_two_d():
    obs=[observation(i,i*.1,root=False) for i in range(5)]
    r=run_tracker(data(obs),Config())
    assert all(p['xyz'] is None for p in r['observations'])


def test_anchors_cannot_merge_simultaneous_people():
    r=run_tracker(data([observation(0,0),observation(0,0,y=2,sdk=3,person=1)]),Config())
    with pytest.raises(ValueError,match='simultaneous'):
        apply_anchors(r,[dict(obs_id='0:0',person_key='A'),dict(obs_id='0:1',person_key='A')])


def test_irregular_time_weights_preserve_actual_duration():
    frames=[dict(frame_index=i,t=t) for i,t in enumerate([0,.1,.233,.333,.8])]
    w=time_weights(frames)
    assert sum(w.values())==pytest.approx(.8)
    assert len(set(round(x,3) for x in w.values()))>1


def make_export(tmp_path,full_frame=False):
    if full_frame:
        from tests.sdk_fakes import FakeSource
        from zed_sdk_package.tracking_v2.export_tracking import stream_export,Settings
        # stream_export intentionally refuses an existing directory.
        folder=tmp_path/'generated'
        stream_export(FakeSource(),folder,Settings(),'a'*64,'test.svo2')
        for f in folder.iterdir():
            f.rename(tmp_path/f.name)
        folder.rmdir()
        return {'transform_camera_to_corridor':np.eye(4).tolist()}
    camera=dict(schema_version=2 if full_frame else 1,body_format='BODY_34',coordinate_units='meter',width=1280,height=720)
    (tmp_path/'camera.json').write_text(json.dumps(camera))
    if full_frame:
        (tmp_path/'manifest.json').write_text(json.dumps(dict(status='complete')))
    cv2.imwrite(str(tmp_path/'image.jpg'),np.zeros((720,1280,3),dtype=np.uint8))
    frames=[];bodies=[]
    for i in range(3):
        o=observation(i,i*.033333333)
        frames.append(dict(frame_index=i,sample_index=i,image_timestamp_ns=o['timestamp_ns'],image_file='image.jpg' if i!=1 or not full_frame else ''))
        bodies.append(dict(frame_index=i,sample_index=i,image_timestamp_ns=o['timestamp_ns'],body_id=0,tracking_state='OK',confidence=99,
                           keypoints_2d_json=json.dumps(o['pixels']),keypoints_3d_camera_json=json.dumps(o['joints']),keypoint_confidence_json=json.dumps(o['joint_confidence'])))
    for filename,rows in [('frames.csv',frames),('bodies.csv',bodies)]:
        with (tmp_path/filename).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return {'transform_camera_to_corridor':np.eye(4).tolist()}


@pytest.mark.parametrize('full_frame',[False,True])
def test_old_and_new_exports_preserve_ns_and_unsaved_image_frames(tmp_path,full_frame):
    calibration=make_export(tmp_path,full_frame)
    d=load_export(tmp_path,calibration)
    assert len(d['observations'])==3
    assert d['frames'][1]['timestamp_ns']=='1000000000033333333'
    assert d['observations'][1]['t']==pytest.approx(.033333333)
    if full_frame:
        assert d['frames'][1]['image_path'] is None


def test_incomplete_sdk_export_is_rejected(tmp_path):
    calibration=make_export(tmp_path,True)
    (tmp_path/'manifest.json').write_text('{"status":"failed"}')
    with pytest.raises(ValueError,match='incomplete'):
        load_export(tmp_path,calibration)


def test_rigid_transform_and_legacy_transform_agree():
    legacy={'floor_plane_camera_image':{'normal_down':[0,1,0],'offset_m':-2},
            'corridor_basis_camera_image':{'X_into_hallway':[0,0,1],'Y_positive_toward_ZED_visible_far_wall':[-1,0,0],'Z_up':[0,-1,0]}}
    rigid={'transform_camera_to_corridor':[[0,0,1,0],[-1,0,0,0],[0,-1,0,2],[0,0,0,1]]}
    assert transform([1,1,5],legacy)==transform([1,1,5],rigid)==[5,-1,1]


def test_manual_anchors_join_fragments_and_split_reviewed_intervals():
    obs=[observation(0,0),observation(1,.1),observation(50,5),observation(51,5.1)]
    r=run_tracker(data(obs),Config())
    corrected=apply_anchors(r,[dict(obs_id='0:0',person_key='A'),dict(obs_id='50:0',person_key='A')])
    assert {p['track_id'] for p in corrected['observations']}=={'manual:A'}
    assert len({p['track_id'] for p in r['observations']})==2
    split=apply_anchors(r,[dict(obs_id='0:0',person_key='A',end_s=0),
                           dict(obs_id='1:0',person_key='B',start_s=.1)])
    assert split['observations'][0]['track_id']!=split['observations'][1]['track_id']


def test_stereo_spike_keeps_identity_but_excludes_position():
    obs=[observation(i,i*.1,x=10-i*.1) for i in range(10)]
    for k in range(34):
        obs[5]['joints'][k][0]+=8
    r=run_tracker(data(obs),Config())
    assert len({p['track_id'] for p in r['observations']})==1
    assert r['observations'][5]['position_source']=='rejected_position'
    assert r['observations'][5]['xyz'] is None


def test_duplicate_sdk_detections_do_not_become_second_person():
    obs=[observation(i,i*.1) for i in range(5)]
    duplicate=observation(3,3*.1,sdk=42);duplicate['obs_id']='duplicate'
    obs.append(duplicate)
    r=run_tracker(data(obs),Config())
    assert next(p for p in r['observations'] if p['obs_id']=='duplicate')['position_source']=='duplicate_observation'
    assert diagnostics(data(obs),r)['candidate_points']==5


def test_calibration_is_rejected_for_other_camera_setup(tmp_path):
    make_export(tmp_path)
    with pytest.raises(ValueError,match='setup_id'):
        load_export(tmp_path,dict(transform_camera_to_corridor=np.eye(4).tolist(),setup_id='new',applies_to={'width':1280}))


def test_position_recovers_after_depth_outage_while_image_identity_continues():
    obs=[observation(i,i*.1,x=10-i*.1) for i in range(40)]
    # Stereo depth settles onto a different but temporally consistent surface.
    # Uncertain early points are excluded, but the old 3D gate must eventually expire.
    for o in obs[5:]:
        for joint in o['joints']:
            joint[0]+=4
    r=run_tracker(data(obs),Config())
    assert len({p['track_id'] for p in r['observations']})==1
    assert r['observations'][5]['xyz'] is None
    assert all(p['xyz'] is not None for p in r['observations'][-10:])


def test_interval_metrics_count_missing_time_not_interpolated_positions():
    from body.corridor_tracking.evaluation import evaluate_intervals
    obs=[observation(0,0),observation(2,.2)]
    d=data(obs,[(0,0),(1,.1),(2,.2)])
    annotations={'intervals':[dict(id='visible',recording='r',frames=[dict(timestamp_ns=f['timestamp_ns'],
                 people=[dict(person='A',bbox=[650,100,800,400],visibility='visible')]) for f in d['frames']])]}
    r=run_tracker(d,Config(interpolate_s=.3))
    rows=evaluate_intervals(d,r,annotations,'r')
    assert len(r['derived'])==1
    assert all(x['support_fraction']==pytest.approx(.5) and x['max_missing_s']==pytest.approx(.1) for x in rows)
    assert all(x['pre_overtake_support_s'] is None for x in rows)
    annotations['intervals'][0].update(rear_person='A',overtaking_bracket_s=[.3,.4],overtaking_status='confirmed_visual_bracket')
    assert all(x['pre_overtake_support_s']==pytest.approx(.1) for x in evaluate_intervals(d,r,annotations,'r'))
    annotations['intervals'][0]['frames'].pop(1)
    with pytest.raises(ValueError,match='every saved frame'):
        evaluate_intervals(d,r,annotations,'r')


def test_review_excludes_mixed_skeleton_instead_of_attributing_pelvis():
    from body.corridor_tracking.evaluation import cross_person_anchors,evaluate_intervals
    first=observation(0,0,sdk=0)
    first['pixels'][0]=[700,250];first['pixels'][2]=[700,240];first['pixels'][26]=[800,150]
    later_a=observation(1,.1,sdk=0);later_b=observation(1,.1,sdk=1,person=1)
    for k in [0,2,26]:
        later_a['pixels'][k]=[700,250];later_b['pixels'][k]=[800,150]
    d=data([first,later_a,later_b]);r=run_tracker(d,Config())
    people=[dict(person='A',bbox=[680,200,730,300],visibility='visible'),
            dict(person='B',bbox=[780,110,830,180],visibility='visible')]
    detected=cross_person_anchors([first],people)
    assert detected[0]['people']=={'A':[0,2],'B':[26]}
    labels={'intervals':[dict(id='two_people',recording='r',frames=[
        dict(timestamp_ns=f['timestamp_ns'],people=people) for f in d['frames']])]}
    strict=evaluate_intervals(d,r,labels,'r',reject_cross_person=True)
    for person in strict:
        assert person['samples'][0]['exclusion_reason']=='cross_person_skeleton'
        assert person['samples'][0]['included'] is False
        assert person['evaluated_s']==pytest.approx(.05)
    standard=evaluate_intervals(d,r,labels,'r',reject_cross_person=False)
    assert all(x['evaluated_s']==pytest.approx(.1) for x in standard)
    from body.corridor_tracking.evaluation import evaluate_checkpoints
    check={'checkpoints':[dict(recording='r',timestamp_ns=d['frames'][0]['timestamp_ns'],people=people)]}
    scores=evaluate_checkpoints(d,r,check,'r')['scores']
    for score in scores.values():
        assert score['person_checkpoints']==0 and score['excluded_person_checkpoints']==2
        assert score['checkpoint_support_fraction'] is None
    both_mixed=observation(1,.1,sdk=0)
    both_mixed['pixels'][0]=[700,250];both_mixed['pixels'][2]=[700,240];both_mixed['pixels'][26]=[800,150]
    all_mixed=data([first,both_mixed])
    labels['intervals'][0]['frames']=[dict(timestamp_ns=f['timestamp_ns'],people=people) for f in all_mixed['frames']]
    undefined=evaluate_intervals(all_mixed,run_tracker(all_mixed,Config()),labels,'r')
    assert all(x['evaluated_s']==0 and x['support_fraction'] is None and x['max_missing_s'] is None for x in undefined)


def test_sdk_branch_rejects_blended_boundary_without_filling_it():
    from body.corridor_tracking.tracker import review_sdk_branches
    # At the next instant SDK 1 follows B while A is still present under SDK 4.
    points=[dict(frame_index=0,t=0,kind='body',sdk_id=1,track_id=10,obs_id='boundary',
                 xyz=[10,1,1],association_reason={'pixel_prediction_error':.4}),
            dict(frame_index=1,t=.1,kind='body',sdk_id=4,track_id=10,obs_id='A',xyz=[9.9,1,1],association_reason={}),
            dict(frame_index=1,t=.1,kind='body',sdk_id=1,track_id=11,obs_id='B',xyz=[10.2,1.3,1],association_reason={})]
    assert review_sdk_branches(points,Config())==[(10,0)]
    assert points[0]['track_id'] is None and points[0]['xyz'] is None
    assert points[0]['association_reason']['candidate_tracks']==[10,11]


def test_reachability_is_not_centered_on_stale_extrapolation():
    from body.corridor_tracking.tracker import Track,cost
    cfg=Config()
    tr=Track(1,observation(0,0,x=16),cfg)
    tr.x=np.array([16.,1.,3.5,0.]);tr.state_t=0
    tr.last=observation(49,4.9,x=9.1);tr.last_t=4.9
    # After uncertain stereo depth, a point 7 m from the previous state is
    # physically reachable in 5 s even if the old velocity predicted 33.5 m.
    score,reason=cost(tr,observation(50,5,x=9),cfg)
    assert score<cfg.match_cost
    assert not reason.get('position_rejected_motion_outlier',False)


def test_separate_head_pass_requires_same_recording_and_preserves_head_identity(tmp_path):
    from tests.sdk_fakes import FakeSource
    from zed_sdk_package.tracking_v2.export_tracking import stream_export,Settings
    stream_export(FakeSource(),tmp_path/'body',Settings(),'a'*64,'test.svo2')
    stream_export(FakeSource(mode='heads'),tmp_path/'heads',Settings(mode='heads'),'a'*64,'test.svo2')
    calibration={'transform_camera_to_corridor':np.eye(4).tolist()}
    d=load_export(tmp_path/'body',calibration,heads_folder=tmp_path/'heads')
    assert len(d['observations'])==6
    assert len({o['obs_id'] for o in d['observations']})==6
    r=run_tracker(d,Config())
    assert len([p for p in r['observations'] if p['position_source']=='supplemental_head'])==3
    stream_export(FakeSource(mode='heads'),tmp_path/'wrong',Settings(mode='heads'),'b'*64,'other.svo2')
    with pytest.raises(ValueError,match='matching source_svo_sha256'):
        load_export(tmp_path/'body',calibration,heads_folder=tmp_path/'wrong')


def test_uncalibrated_head_box_cannot_reuse_body_joint_offset_as_3d_position():
    from body.corridor_tracking.tracker import Track
    cfg=Config();initial=observation(0,0)
    tr=Track(1,initial,cfg)
    for i in range(4):
        body=observation(i,i*.1,x=10-i*.1)
        xyz,sigma,_,_=tr.estimate(body)
        tr.update(body,xyz,sigma)
    assert len(tr.offsets[26])>=3
    head=observation(4,.4,x=9.6)
    head.update(kind='head',root_valid=False)
    # This is an object-box position, not a calibrated BODY_34 joint.
    head['joints'][26][0]+=1.0
    for offline in [False,True]:
        xyz,sigma,parts,source=tr.estimate(head,offline=offline)
        assert xyz is None and sigma is None and parts==[26] and source=='two_d_only'


def _head_observation(frame,t,sdk,uv):
    head=observation(frame,t,sdk=sdk)
    head.update(obs_id=f'head:{frame}:{sdk}',kind='head',root_valid=False,legacy_valid=False,appearance=None)
    head['pixels']=[None]*34;head['pixels'][26]=list(uv)
    head['joints']=[None]*34;head['joints'][26]=[10,1,1.6]
    return head


def test_multiple_head_boxes_near_one_body_remain_ambiguous_not_suppressed():
    body=observation(0,0);uv=np.asarray(body['pixels'][26]);
    heads=[_head_observation(0,0,11,uv+[2,0]),_head_observation(0,0,12,uv+[-2,0])]
    r=run_tracker(data([body,*heads]),Config())
    points=[x for x in r['observations'] if x['kind']=='head']
    assert len(points)==2
    assert all(p['id_status']=='ambiguous' and p['xyz'] is None and p['track_id'] is None for p in points)
    assert all(p['association_reason']['reason']=='ambiguous_head_body_proximity' for p in points)
    assert all(len(p['association_reason']['competing_head_obs_ids'])==2 for p in points)
    assert len([p for p in r['observations'] if p['kind']=='body' and p['xyz'] is not None])==1


def test_one_head_near_two_bodies_is_not_assigned_to_either():
    a=observation(0,0,sdk=0,person=0);b=observation(0,0,y=2,sdk=1,person=1)
    b['pixels'][26]=list(np.asarray(a['pixels'][26])+[4,0])
    h=_head_observation(0,0,11,np.asarray(a['pixels'][26])+[2,0])
    r=run_tracker(data([a,b,h]),Config());point=next(x for x in r['observations'] if x['kind']=='head')
    assert point['id_status']=='ambiguous' and point['xyz'] is None and point['track_id'] is None
    assert set(point['association_reason']['candidate_body_obs_ids'])=={a['obs_id'],b['obs_id']}


def test_head_pass_rejects_extra_frame_even_without_a_detection(tmp_path):
    from tests.sdk_fakes import FakeSource
    from zed_sdk_package.tracking_v2.export_tracking import stream_export,Settings
    stream_export(FakeSource(),tmp_path/'body',Settings(),'a'*64,'test.svo2')
    source=FakeSource(frames=4,mode='heads');read=source.read
    def read_with_empty_last():
        frame=read()
        if frame is not None and source.i==4:frame['detections']=[]
        return frame
    source.read=read_with_empty_last
    stream_export(source,tmp_path/'heads',Settings(mode='heads'),'a'*64,'test.svo2')
    calibration={'transform_camera_to_corridor':np.eye(4).tolist()}
    with pytest.raises(ValueError,match='full frame timeline mismatch'):
        load_export(tmp_path/'body',calibration,heads_folder=tmp_path/'heads')
