import csv
import json
from types import SimpleNamespace

import numpy as np
import pytest

from corridor_tracking.upper_body_pose import axis_yaw, combine_yaw, joint_depth, trusted_mapping, velocity, write_csv, write_gaps
from corridor_tracking.spatial_filter import filter_frames
from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs, withhold_isolated_excursions
from corridor_tracking.upper_body_replay import make_page


def joint(xyz, score=.8):
    return {'corridor_m':xyz, 'score':score}


def test_yaw_convention_confidence_and_abstention():
    shoulder=axis_yaw(joint([0,0,1]),joint([0,-.4,1], .6))
    assert shoulder['yaw_deg'] == pytest.approx(0)
    assert shoulder['confidence'] == .6
    hip=axis_yaw(joint([0,0,0]),joint([.4,0,0]))
    assert hip['yaw_deg'] == pytest.approx(90)
    assert combine_yaw(shoulder,hip)['reason'] == 'shoulder_hip_disagreement'
    assert axis_yaw(joint(None),joint([1,0,0]))['yaw_deg'] is None
    assert axis_yaw(joint([0,0,0]),joint([.01,0,0]))['reason'] == 'horizontal_baseline_too_short'
    a={'yaw_deg':179,'confidence':.7}; b={'yaw_deg':-179,'confidence':.6}
    assert abs(combine_yaw(a,b)['yaw_deg']) == pytest.approx(180)


def test_depth_backprojection_and_quality():
    intr={'fx':100.,'fy':100.,'cx':50.,'cy':50.}
    pts=np.array([[0,0,2], [.02,0,2],[-.02,0,2]])
    good=joint_depth(np.array([50.,50.]),.8,pts,intr,100,100)
    assert good['camera_m'] == pytest.approx([0,0,2])
    assert good['depth_points'] == 3
    assert joint_depth(np.array([50.,50.]),.1,pts,intr,100,100)['reason'] == 'low_keypoint_score'
    assert joint_depth(np.array([50.,50.]),.8,pts[:2],intr,100,100)['reason'] == 'insufficient_depth'
    mixed=np.array([[0,0,1],[0,0,2],[0,0,3]])
    assert joint_depth(np.array([50.,50.]),.8,mixed,intr,100,100)['reason'] == 'ambiguous_depth'


def test_trusted_mapping_excludes_outside_without_shifting_observations():
    bounds={'max_x_m':10.,'min_y_m':-1.,'max_y_m':1.}
    frames=[{'frame_index':0,'timestamp_ns':'1','elapsed_s':0.,'observations':[{'track_id':1,'surface_corridor_m':[11,0,0]}, {'track_id':None,'surface_corridor_m':None}, {'track_id':2,'surface_corridor_m':[2,0,0]}]}]
    raw={'metadata':{'id':'a'},'frames':frames}
    filtered,_,_=filter_frames(frames,bounds)
    filtered,_=withhold_isolated_excursions(filtered)
    filtered,_,_=withhold_discontinuous_pairs(filtered)
    trusted={'metadata':raw['metadata'],'frames':filtered}
    mapping=trusted_mapping(raw,trusted,bounds)[0]
    assert list(mapping)==[1,2] and mapping[2]['track_id']==2
    trusted['frames'][0]['observations'][1]['surface_corridor_m']=[3,0,0]
    with pytest.raises(ValueError): trusted_mapping(raw,trusted,bounds)


def test_speed_no_unknown_identity_or_gap_and_gap_csv(tmp_path):
    angles={k:{'yaw_deg':None,'reason':'missing_joint_depth','confidence':None} for k in ('shoulder','hip','torso','head')}
    def o(ident,pos): return {'track_id':ident,'position_m':pos,'angles':angles,'joints':{},'observation_index':0,'position_status':'available','pose_reason':'ok'}
    frames=[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'observations':[o(1,[0,0,0]),o(None,[0,0,0])]}, {'frame_index':1,'timestamp_ns':'100000100','elapsed_s':.1,'observations':[o(1,[.1,0,0])]}, {'frame_index':2,'timestamp_ns':'200000100','elapsed_s':.2,'observations':[]}, {'frame_index':3,'timestamp_ns':'300000100','elapsed_s':.3,'observations':[o(1,[.3,0,0])]}]
    velocity(frames)
    assert frames[1]['observations'][0]['speed_m_s']==pytest.approx(1)
    assert frames[0]['observations'][1]['speed_m_s'] is None
    assert frames[3]['observations'][0]['speed_m_s'] is None
    data={'metadata':{'trial_id':'t','group':2,'recording':'recording_001'},'frames':frames}
    write_gaps(tmp_path/'gaps.csv',data); write_csv(tmp_path/'pose.csv',data)
    with (tmp_path/'gaps.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    assert any(r['measure']=='head' and r['first_frame']=='0' and r['last_frame']=='3' and 'id_not_observed' in r['reasons'] for r in rows)
    with (tmp_path/'pose.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    assert any(r['pose_reason']=='no_person_detection' and r['frame_index']=='2' for r in rows)
    assert any(r['frame_index']=='0' and r['track_id']=='' for r in rows)


def test_replay_escapes_embedded_script():
    page=make_page({'metadata':{'trial_id':'</script><script>bad()'},'frames':[]})
    assert '</script><script>bad()' not in page
    assert '\\u003c/script>' in page


def test_complete_pipeline_with_matched_inputs_and_unknown_id(tmp_path, monkeypatch):
    from corridor_tracking import upper_body_pose as module
    from corridor_tracking.spatial_filter import filter_frames
    from depth_person_prototype import digest
    import cv2
    root=tmp_path/'depth'; root.mkdir()
    image=root/'frame.jpg'; cv2.imwrite(str(image),np.zeros((60,80,3),np.uint8))
    cal=tmp_path/'cal.json'; cal.write_text('{}')
    model=tmp_path/'config.py'; model.write_text('config')
    checkpoint=tmp_path/'model.pth'; checkpoint.write_text('weights')
    pr=tmp_path/'person'; pr.mkdir(); (pr/'manifest.json').write_text('person manifest')
    rawdir=tmp_path/'raw'; rawdir.mkdir(); trustdir=tmp_path/'trusted'; trustdir.mkdir()
    metadata={'group':2,'recording':'recording_001','source_svo_sha256':'a'*64,'setup_id':'s','calibration_sha256':digest(cal),'person_run_manifest_sha256':digest(pr/'manifest.json')}
    obs={'track_id':None,'surface_corridor_m':[2,0,1],'depth_status':'ok'}
    frame={'frame_index':0,'timestamp_ns':'10','elapsed_s':0.,'observations':[obs]}
    raw={'metadata':metadata,'frames':[frame]}
    bounds={'max_x_m':10.,'min_y_m':-1.,'max_y_m':1.}
    filtered,_,_=filter_frames(raw['frames'],bounds)
    trusted={'metadata':metadata,'frames':filtered,'walls':{}}
    (rawdir/'positions.json').write_text(json.dumps(raw)); (rawdir/'manifest.json').write_text('manifest')
    (trustdir/'positions.json').write_text(json.dumps(trusted))
    tm={'source_positions_sha256':digest(rawdir/'positions.json'),'source_manifest_sha256':digest(rawdir/'manifest.json'),'bounds':bounds}
    monkeypatch.setattr(module,'packet',lambda p: (raw,{}) if p==rawdir else (trusted,tm))
    monkeypatch.setattr(module,'load_run',lambda p:{'metadata':metadata,'frames':[{'frame_index':0,'timestamp_ns':'10','image_sha256':digest(image),'people':[{'status':'ok','surface_corridor_m':[2,0,1],'region_bbox_xyxy':[0,0,80,60]}]}]})
    camera={'source_svo_sha256':'a'*64,'setup_id':'s','width':80,'height':60,'intrinsics_left':{'fx':100.,'fy':100.,'cx':40.,'cy':30.}}
    df={'frame_index':0,'image_timestamp_ns':'10','image_file':'frame.jpg','image_sha256':digest(image),'sample_index':0}
    points=np.array([[0,0,2],[.02,0,2],[-.02,0,2]])
    monkeypatch.setattr(module,'load_depth_export',lambda p:(root,camera,[df],points,np.zeros(3,int),'depthhash'))
    monkeypatch.setattr(module,'calibration_for_camera',lambda *args:{'transform_camera_to_corridor':np.eye(4).tolist()})
    monkeypatch.setattr(module,'make_estimator',lambda *args:lambda image,bbox:{name:(np.array([40.,30.]),.8) for name in module.JOINTS})
    monkeypatch.setattr(module.importlib.metadata,'version',lambda _: 'test')
    args=SimpleNamespace(output=tmp_path/'output',positions=rawdir,trusted=trustdir,person_run=pr,calibration=cal,model_config=model,model_checkpoint=checkpoint,depth=[root],trial_id='trial1',backend='mmpose',threads=2,depth_region='all',device='cpu',keypoint_threshold=.3,radius=5.,min_points=3,max_spread=.35)
    module.run(args)
    result=json.loads((args.output/'pose.json').read_text())
    detected=result['frames'][0]['observations'][0]
    assert detected['track_id'] is None and detected['position_m']==[2,0,1]
    assert detected['joints']['nose']['reason']=='ok'
    assert detected['speed_m_s'] is None
    assert (args.output/'pose_replay.html').is_file() and (args.output/'gaps.csv').is_file()
    with pytest.raises(FileExistsError): module.run(args)


def test_indexed_depth_matches_direct_neighborhood(monkeypatch):
    from corridor_tracking import upper_body_pose as module
    if module.spatial_tree_type() is None: pytest.skip('compatible SciPy unavailable')
    rng=np.random.default_rng(17)
    intr={'fx':100.,'fy':110.,'cx':50.,'cy':45.}
    z=rng.uniform(1.5,2.0,1000)
    u=rng.uniform(30,70,1000);v=rng.uniform(25,65,1000)
    pts=np.column_stack(((u-intr['cx'])*z/intr['fx'],(v-intr['cy'])*z/intr['fy'],z))
    indexed=module.prepare_depth(pts,intr)
    xy=np.array([50.3,45.7])
    a=module.joint_depth(xy,.9,pts,intr,100,100,max_spread=1.,prepared=indexed)
    b=module.joint_depth(xy,.9,pts,intr,100,100,max_spread=1.,prepared=(indexed[0],indexed[1],None))
    assert a==b


def test_person_mask_excludes_background_and_overlapping_people():
    from corridor_tracking.upper_body_pose import prepare_depth
    intr={'fx':100.,'fy':100.,'cx':50.,'cy':50.}
    points=np.array([[0,0,2],[.02,0,2],[-.02,0,2],[0,.3,10],[.1,0,10]])
    mask=np.zeros((100,100),np.uint8); mask[49:52,48:53]=1
    membership=mask.astype(np.uint16); membership[50,51]=2
    prepared=prepare_depth(points,intr)
    raw=joint_depth(np.array([50.,50.]),.9,points,intr,100,100,radius=5.,min_points=2,prepared=prepared)
    filtered=joint_depth(np.array([50.,50.]),.9,points,intr,100,100,radius=5.,min_points=2,prepared=prepared,mask=mask,membership=membership)
    assert raw['reason']=='ambiguous_depth'
    assert filtered['reason']=='ok' and filtered['depth_points_before_mask']==5 and filtered['depth_points']==2
    assert filtered['camera_m'][2]==pytest.approx(2)
