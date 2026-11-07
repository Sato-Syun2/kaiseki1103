import copy
import json

import pytest

from corridor_tracking.spatial_filter import corridor_bounds, filter_frames
from corridor_tracking.filter_shared_positions import filter_candidate
from depth_person_prototype import digest


def test_corridor_bounds_require_opposite_wall_and_keep_boundary():
    cal={'visible_wall_Y_m':2.,'other_wall_inference':None}
    with pytest.raises(ValueError,match='opposite wall'):
        corridor_bounds(cal)
    b=corridor_bounds(cal, fallback_width_m=2.4)
    obs=lambda p:{'track_id':None,'surface_corridor_m':p}
    frames=[{'frame_index':0,'observations':[obs([15.,2.,1.]),obs([15.01,1.,1.]),obs([4.,2.01,1.]),
                                              obs([4.,-0.41,1.]),obs(None)]}]
    result,indices,stats=filter_frames(frames,b)
    assert indices==[[0,4]] and stats['outside_any']==3 and stats['outside_x']==1 and stats['outside_wall']==2
    assert stats['unlocated_retained']==1 and len(result[0]['observations'])==2
    assert len(frames[0]['observations'])==5


def test_candidate_filter_drops_outside_assignments_without_touching_inside(tmp_path):
    bounds=corridor_bounds({'visible_wall_Y_m':2.},fallback_width_m=2.4)
    obs=lambda p:{'track_id':None,'surface_corridor_m':p,'depth_status':'surface_candidate'}
    original={'metadata':{'group':4,'recording':'recording_001'},'frames':[{'frame_index':0,'timestamp_ns':'1','elapsed_s':0.,
               'observations':[obs([5.,1.,1.]),obs([16.,1.,1.])]}]}
    source=tmp_path/'source';source.mkdir();(source/'positions.json').write_text(json.dumps(original))
    (source/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':digest(source/'positions.json'),'frame_count':1}))
    candidate=copy.deepcopy(original);candidate['reassignment_candidate']={'status':'proposed_not_verified','target_id':2,
                                        'source_positions_sha256':digest(source/'positions.json')}
    for o in candidate['frames'][0]['observations']:
        o.update(track_id=2,original_track_id=None,identity_assignment='proposed')
    # The same target must not occur twice in one frame, so use a second frame for the excluded point.
    original['frames'][0]['observations'].pop();original['frames'].append({'frame_index':1,'timestamp_ns':'2','elapsed_s':.1,'observations':[obs([16.,1.,1.])]})
    candidate['frames'][0]['observations'].pop();candidate['frames'].append({'frame_index':1,'timestamp_ns':'2','elapsed_s':.1,'observations':[dict(obs([16.,1.,1.]),track_id=2,original_track_id=None,identity_assignment='proposed')]})
    (source/'positions.json').write_text(json.dumps(original));(source/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':digest(source/'positions.json'),'frame_count':2}))
    candidate['reassignment_candidate']['source_positions_sha256']=digest(source/'positions.json')
    cand=tmp_path/'candidate';cand.mkdir();(cand/'positions.json').write_text(json.dumps(candidate));(cand/'manifest.json').write_text(json.dumps({'status':'proposed_not_verified','positions_sha256':digest(cand/'positions.json'),'source_positions_sha256':digest(source/'positions.json'),'proposed_count':2}))
    frames,_,_=filter_frames(original['frames'],bounds);filtered=copy.deepcopy(original);filtered['frames']=frames;filtered['spatial_filter']={'bounds':bounds}
    old=tmp_path/'filtered';old.mkdir();(old/'positions.json').write_text(json.dumps(filtered));(old/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':digest(old/'positions.json'),'source_positions_sha256':digest(source/'positions.json'),'bounds':bounds}))
    output=tmp_path/'out';created,count=filter_candidate(source,cand,old,output,bounds)
    assert created and count==1
    result=json.loads((output/'positions.json').read_text())
    assert result['frames'][0]['observations'][0]['track_id']==2 and result['frames'][1]['observations']==[]
    assert result['reassignment_candidate']['source_positions_sha256']==digest(old/'positions.json')
