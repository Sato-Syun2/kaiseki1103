from corridor_tracking.propose_trusted10_identities import evaluate as old_evaluate
from corridor_tracking.short_anchor_identity_v2 import evaluate
from tests.test_reassign_depth_identity_temporal import frames_for_short_anchor


def test_five_frame_anchor_is_considered_without_weakening_temporal_gates():
    frames=frames_for_short_anchor()
    old,_=old_evaluate(frames);new,counts=evaluate(frames)
    assert old==[]
    assert counts[8]==6
    assert len(new)==1
    target,reference,changed,assignments,diagnostics=new[0]
    assert (target,reference,len(assignments))==(8,1,18)
    assert diagnostics['settings']['min_anchor_observations']==5
    assert all(f['observations'][0]['track_id'] is None for f in frames[:18])
    assert all(f['observations'][0]['track_id']==8 for f in changed[:18])


def test_short_anchor_without_consistent_motion_stays_unassigned():
    frames=frames_for_short_anchor()
    for f in frames[18:]:f['observations'][0]['surface_corridor_m'][0]=9.0
    options,_=evaluate(frames)
    assert options==[]
