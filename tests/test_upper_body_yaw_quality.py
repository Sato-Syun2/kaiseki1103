from copy import deepcopy
import pytest
from corridor_tracking.upper_body_yaw_quality import withhold_yaw_discontinuities


def obs(ident, shoulder=0,hip=0,torso=0,head=0):
    return {'track_id':ident,'angles':{name:{'yaw_deg':value,'confidence':.7,'reason':'ok'} for name,value in [('shoulder',shoulder),('hip',hip),('torso',torso),('head',head)]},'position_m':[3,0,1]}


def test_discontinuity_withholds_both_and_torso_preserves_input():
    frames=[{'frame_index':0,'elapsed_s':0.,'observations':[obs(1),obs(None)]},
            {'frame_index':1,'elapsed_s':.03,'observations':[obs(1,shoulder=50,head=55),obs(None,head=100)]}]
    original=deepcopy(frames)
    out,events,counts=withhold_yaw_discontinuities(frames)
    assert frames == original and len(events)==2
    assert counts == {'shoulder':2,'hip':0,'torso':2,'head':2}
    assert out[0]['observations'][0]['angles']['shoulder']['original_yaw_deg']==0
    assert out[1]['observations'][0]['angles']['head']['yaw_deg'] is None
    assert out[0]['observations'][0]['angles']['torso']['reason']=='withheld_component_discontinuity'
    assert out[1]['observations'][1]['angles']['head']['yaw_deg']==100
    assert out[0]['observations'][0]['position_m']==[3,0,1]


def test_wrap_and_missing_frame_do_not_trigger():
    frames=[{'frame_index':0,'elapsed_s':0.,'observations':[obs(1,head=179)]},
            {'frame_index':1,'elapsed_s':.03,'observations':[obs(1,head=-179)]},
            {'frame_index':3,'elapsed_s':.06,'observations':[obs(1,head=0)]}]
    out,events,counts=withhold_yaw_discontinuities(frames)
    assert not events and not any(counts.values()) and out==frames


def test_duplicate_and_invalid_thresholds_rejected():
    frames=[{'frame_index':0,'elapsed_s':0.,'observations':[obs(1),obs(1)]}, {'frame_index':1,'elapsed_s':.03,'observations':[obs(1)]}]
    with pytest.raises(ValueError): withhold_yaw_discontinuities(frames)
    with pytest.raises(ValueError): withhold_yaw_discontinuities([],min_delta_deg=181)


def test_quality_output_keeps_original_data_and_points_at_original_image(tmp_path):
    import json
    from urllib.parse import unquote
    from corridor_tracking.upper_body_pose import write_csv, write_gaps
    from corridor_tracking.upper_body_replay import make_page
    from corridor_tracking.upper_body_yaw_quality import run
    from depth_person_prototype import digest
    image=tmp_path/'image.jpg';image.write_bytes(b'image')
    frames=[{'frame_index':i,'timestamp_ns':str(i+10),'elapsed_s':.03*i,'image':'../image.jpg','observations':[obs(1,head=y)]} for i,y in enumerate((0,60))]
    for frame in frames:
        frame['observations'][0].update(observation_index=0,joints={},position_status='available',speed_m_s=None,speed_reason='no_previous_position',pose_reason='ok')
    data={'metadata':{'trial_id':'trial','group':2,'recording':'recording_001'},'frames':frames}
    source=tmp_path/'original';source.mkdir()
    (source/'pose.json').write_text(json.dumps(data),encoding='utf-8')
    write_csv(source/'pose.csv',data);write_gaps(source/'gaps.csv',data)
    (source/'pose_replay.html').write_text(make_page(data),encoding='utf-8')
    files={name:digest(source/name) for name in ('pose.json','pose.csv','gaps.csv','pose_replay.html')}
    (source/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':files}),encoding='utf-8')
    output=tmp_path/'reviewed';run(source,output)
    updated=json.loads((output/'pose.json').read_text())
    assert updated['frames'][1]['observations'][0]['angles']['head']['yaw_deg'] is None
    assert updated['frames'][1]['observations'][0]['angles']['head']['original_yaw_deg']==60
    assert (output/unquote(updated['frames'][0]['image'])).resolve()==image
    assert json.loads((source/'pose.json').read_text())==data
    with pytest.raises(FileExistsError): run(source,output)
