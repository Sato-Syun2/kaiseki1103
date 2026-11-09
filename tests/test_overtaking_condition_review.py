from corridor_tracking.overtaking_condition_review import assess


def walk(heading=-1, side='右', exchange=True, target_is_passer=True):
    # At the start the passer is behind, then ends ahead. Both walk along X.
    frames=[]
    right_y=-heading
    side_y=right_y if side=='右' else -right_y
    for i in range(61):
        t=i/10
        leader_x=heading*t
        relative=(-1+2*t/6) if exchange else -1
        passer_x=leader_x+heading*relative
        first=[passer_x,side_y*.6,1.] if target_is_passer else [leader_x,0.,1.]
        second=[leader_x,0.,1.] if target_is_passer else [passer_x,side_y*.6,1.]
        frames.append({'elapsed_s':t,'frame_index':i,'observations':[
            {'track_id':3,'surface_corridor_m':first},
            {'track_id':1,'surface_corridor_m':second}]})
    return frames


def test_both_walking_directions_and_both_sides():
    for heading in (-1,1):
        for side in ('左','右'):
            r=assess(walk(heading,side),3,1,side,1.)
            assert r['status']=='consistent'
            assert r['estimated_side']==side
            assert r['estimated_overtaker_track_id']==3
            opposite='左' if side=='右' else '右'
            assert assess(walk(heading,side),3,1,opposite,1.)['status']=='conflict'


def test_passer_can_be_reference_and_order_exchange_is_required():
    r=assess(walk(target_is_passer=False),3,1,'右',1.)
    assert r['status']=='consistent' and r['estimated_overtaker_track_id']==1
    assert assess(walk(exchange=False),3,1,'右',1.)['status']=='insufficient'


def test_degenerate_basis_and_ambiguous_side_are_not_classified():
    assert assess(walk(),3,1,'右',0.)['status']=='insufficient'
    frames=walk()
    for f in frames:f['observations'][0]['surface_corridor_m'][1]=.01
    assert assess(frames,3,1,'右',1.)['status']=='insufficient'
