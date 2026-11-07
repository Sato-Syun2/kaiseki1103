"""Propose conservative retrospective IDs using a visually checked later track and local motion."""
import copy
import math
import statistics


def propose_backwards(frames, target_id, reference_id, *, max_gap=.40, base_gate=.12, speed_gate=2.5,
                      min_separation=.35, candidate_margin=.15, height_step=.40, height_speed=.5,
                      backward_tolerance=.18, min_anchor=5, min_height=.65, max_height=1.65):
    """Backtrack unknown IDs only; positions are never changed or interpolated."""
    if target_id == reference_id:
        raise ValueError('target and reference must differ')
    if (min_anchor < 3 or min_height >= max_height or
            any(not math.isfinite(x) or x <= 0 for x in
                (max_gap, base_gate, speed_gate, min_separation, candidate_margin, height_step, height_speed, backward_tolerance))):
        raise ValueError('invalid reassociation thresholds')
    for before, after in zip(frames, frames[1:]):
        if int(after['frame_index']) <= int(before['frame_index']) or float(after['elapsed_s']) <= float(before['elapsed_s']) or int(after['timestamp_ns']) <= int(before['timestamp_ns']):
            raise ValueError('frames must be strictly ordered')
    for frame in frames:
        ids=[o['track_id'] for o in frame['observations'] if o['track_id'] is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate assigned IDs in one frame')
    anchored = [(f, o) for f in frames for o in f['observations']
                if o['track_id'] == target_id and o.get('surface_corridor_m') is not None]
    if len(anchored) < min_anchor:
        raise ValueError('insufficient target observations for anchor')
    seed, target = anchored[0]
    sample = [(f, o) for f, o in anchored if 0 <= f['elapsed_s']-seed['elapsed_s'] <= 1.0]
    speeds = [(b[1]['surface_corridor_m'][0]-a[1]['surface_corridor_m'][0])/(b[0]['elapsed_s']-a[0]['elapsed_s'])
              for a, b in zip(sample, sample[1:]) if 0 < b[0]['elapsed_s']-a[0]['elapsed_s'] <= .15]
    if len(speeds) < 3 or abs(statistics.median(speeds)) < .25:
        raise ValueError('anchor does not establish a clear walking direction')
    velocity = statistics.median(speeds); sign = 1 if velocity > 0 else -1
    updated = copy.deepcopy(frames)
    seed_index = next(i for i, f in enumerate(updated) if f['frame_index'] == seed['frame_index'])
    last_time = float(seed['elapsed_s']); last_point = target['surface_corridor_m']
    changes=[]; reasons={'missing_reference':0, 'no_eligible_candidate':0, 'ambiguous_candidates':0, 'target_already_present':0}
    stop='start_of_recording'
    for frame in reversed(updated[:seed_index]):
        dt=last_time-float(frame['elapsed_s'])
        if dt <= 0: raise ValueError('non-increasing time')
        if dt > max_gap:
            stop='gap_exceeded'; break
        if any(o['track_id'] == target_id for o in frame['observations']):
            reasons['target_already_present'] += 1; continue
        reference=[o for o in frame['observations'] if o['track_id']==reference_id and o.get('surface_corridor_m') is not None]
        if len(reference)!=1:
            reasons['missing_reference']+=1;continue
        options=[]
        for i, o in enumerate(frame['observations']):
            point=o.get('surface_corridor_m')
            if o['track_id'] is not None or point is None or not min_height <= point[2] <= max_height:continue
            distance=math.dist(point[:2],last_point[:2]); separation=math.dist(point[:2],reference[0]['surface_corridor_m'][:2])
            height_diff=abs(point[2]-last_point[2]);reverse_advance=sign*(point[0]-last_point[0])
            if (distance <= base_gate+speed_gate*dt and separation >= min_separation and
                    height_diff <= height_step+height_speed*dt and reverse_advance <= backward_tolerance):
                score=distance + .2*height_diff
                options.append((score,i,point,separation,distance,height_diff))
        options.sort(key=lambda x:(x[0],x[1]))
        if not options:reasons['no_eligible_candidate']+=1;continue
        if len(options)>1 and options[1][0]-options[0][0] < candidate_margin:
            reasons['ambiguous_candidates']+=1;continue
        _,index,point,separation,distance,height_diff=options[0];o=frame['observations'][index]
        o['original_track_id']=None;o['track_id']=target_id;o['identity_assignment']='proposed'
        changes.append({'frame_index':frame['frame_index'],'observation_index':index,'timestamp_ns':frame['timestamp_ns'],
                        'elapsed_s':frame['elapsed_s'],'original_track_id':None,'proposed_track_id':target_id,
                        'surface_corridor_m':point,'time_to_next_s':round(dt,6),'distance_to_next_xy_m':round(distance,6),
                        'reference_separation_xy_m':round(separation,6),'height_difference_m':round(height_diff,6),
                        'status':'proposed_not_verified'})
        last_time,last_point=float(frame['elapsed_s']),point
    changes.reverse()
    diagnostics={'target_id':target_id,'reference_id':reference_id,'anchor_frame':seed['frame_index'],
                 'anchor_elapsed_s':seed['elapsed_s'],'anchor_sample_count':len(sample),
                 'anchor_median_x_velocity_m_s':velocity,'stop_reason':stop,'rejection_counts':reasons,
                 'settings':{'max_gap_s':max_gap,'base_gate_m':base_gate,'speed_gate_m_s':speed_gate,
                             'min_reference_separation_m':min_separation,'candidate_margin_m':candidate_margin,
                             'height_step_m':height_step,'height_speed_m_s':height_speed,'backward_tolerance_m':backward_tolerance,
                             'min_anchor_observations':min_anchor,'height_range_m':[min_height,max_height]}}
    return updated,changes,diagnostics
