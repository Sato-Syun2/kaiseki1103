from copy import deepcopy
import pytest
from corridor_tracking.trajectory_quality import withhold_isolated_excursions
from corridor_tracking.spatial_filter import corridor_bounds, filter_frames


def frames(xs, *, ids=None):
    return [{'frame_index':i,'timestamp_ns':str(1+i*33333333),'elapsed_s':i*.033333333,
             'observations':[{'track_id': ids[i] if ids else 1,'surface_corridor_m':None if x is None else [x,0,1],
                              'depth_status':'surface_candidate'}]} for i,x in enumerate(xs)]


def test_isolated_spike_is_withheld_without_interpolating_or_changing_original():
    source=frames([2,2.02,2.80,2.04,2.06]);original=deepcopy(source)
    out,removed=withhold_isolated_excursions(source)
    assert source==original and len(removed)==1 and removed[0]['frame_index']==2
    assert out[2]['observations'][0]['surface_corridor_m'] is None
    assert out[2]['observations'][0]['track_id']==1
    assert out[2]['observations'][0]['position_quality']=='withheld_isolated_temporal_excursion'
    assert out[1]==source[1] and out[3]==source[3]


def test_two_frame_spike_but_not_stable_movement_or_missing_or_unknown_id():
    out,issues=withhold_isolated_excursions(frames([2,2.02,2.9,2.9,2.05,2.1]))
    assert [x['frame_index'] for x in issues]==[2,3]
    for source in (frames([2,2.05,2.10,2.15,2.2]),frames([2,2.02,2.9,None,2.05]),
                   frames([2,2.02,2.9,2.05],ids=[1,1,None,1]),frames([2,2.02,2.9,2.92,2.94])):
        assert withhold_isolated_excursions(source)[1]==[]


def test_crossing_keeps_separate_ids_and_does_not_smooth_them():
    data=frames([3,3.05,3.1,3.15,3.2])
    for i,f in enumerate(data):
        f['observations'].append({'track_id':2,'surface_corridor_m':[3.2-.05*i,.1,1], 'depth_status':'surface_candidate'})
    out,events=withhold_isolated_excursions(data)
    assert out==data and not events


def test_exact_ten_m_is_retained_and_wall_rules_remain():
    b=corridor_bounds({'visible_wall_Y_m':2},max_x_m=10,fallback_width_m=2.4)
    fs=frames([10,10.001,9.9]);fs[2]['observations'][0]['surface_corridor_m'][1]=2.1
    filtered,_,counts=filter_frames(fs,b)
    assert filtered[0]['observations'] and not filtered[1]['observations'] and not filtered[2]['observations']
    assert counts['outside_x']==1 and counts['outside_wall']==1


def test_nonmonotonic_time_rejected():
    data=frames([1,2,3]);data[2]['elapsed_s']=data[1]['elapsed_s']
    with pytest.raises(ValueError,match='strictly ordered'):withhold_isolated_excursions(data)


def test_discontinuous_pair_withholds_both_endpoints_without_inventing_data():
    from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs
    source=frames([2,2.03,2.90,2.95,3.0]);original=deepcopy(source)
    out,events,count=withhold_discontinuous_pairs(source)
    assert source==original and count==2 and len(events)==1
    assert out[1]['observations'][0]['surface_corridor_m'] is None
    assert out[2]['observations'][0]['surface_corridor_m'] is None
    assert out[0]==source[0] and out[3]==source[3]
    assert events[0]['left_frame']==1 and events[0]['right_frame']==2


def test_no_pair_across_missing_frame_or_different_id():
    from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs
    for f in (frames([2,None,3]),frames([2,3],ids=[1,2]),frames([2,2.05,2.10])):
        assert withhold_discontinuous_pairs(f)[1:]==([],0)
