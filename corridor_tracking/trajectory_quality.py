"""Conservatively withhold short, isolated trajectory excursions; never invent positions."""
from collections import defaultdict
from copy import deepcopy
import math


def withhold_isolated_excursions(frames, *, max_span_s=.30, max_inner_frames=4,
                                  min_excursion_m=.60, min_edge_speed_m_s=4.,
                                  anchor_base_m=.12, anchor_speed_m_s=2.5,
                                  min_residual_m=.50):
    """Only assigned ID tracks with nearby, mutually consistent anchors are eligible.

    Every intervening observation must be a positioned point of that ID in consecutive
    frames. The bridge is used solely to detect disagreement, never as output data.
    An excursion becomes an unlocated observation and is recorded for review.
    """
    if not frames:
        return [], []
    settings=(max_span_s,min_excursion_m,min_edge_speed_m_s,anchor_base_m,anchor_speed_m_s,min_residual_m)
    if any(not math.isfinite(x) or x<=0 for x in settings) or not 1<=max_inner_frames<=10:
        raise ValueError('invalid trajectory quality settings')
    tracks=defaultdict(list);previous=None
    for i,frame in enumerate(frames):
        t=float(frame['elapsed_s']);stamp=int(frame['timestamp_ns']);idx=int(frame['frame_index'])
        if not math.isfinite(t) or previous is not None and (idx<=previous[0] or stamp<=previous[1] or t<=previous[2]):
            raise ValueError('frames must be strictly ordered')
        previous=(idx,stamp,t)
        seen=set()
        for j,obs in enumerate(frame['observations']):
            ident=obs.get('track_id');p=obs.get('surface_corridor_m')
            if ident is None or p is None:continue
            if ident in seen:raise ValueError('multiple positioned observations with same ID in a frame')
            seen.add(ident)
            if len(p)!=3 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in p):
                raise ValueError('invalid position')
            tracks[ident].append((i,j,t,p))
    selected={}; protected=set()
    for ident,points in tracks.items():
        for start in range(len(points)-2):
            left=points[start]
            for inner_count in range(1,max_inner_frames+1):
                end=start+inner_count+1
                if end>=len(points):break
                right=points[end]; span=right[2]-left[2]
                if span>max_span_s:break
                sequence=points[start:end+1]
                if any(b[0]!=a[0]+1 for a,b in zip(sequence,sequence[1:])):continue
                first,last=sequence[1],sequence[-2]
                jump_in=math.dist(left[3][:2],first[3][:2]); jump_out=math.dist(last[3][:2],right[3][:2])
                in_dt=first[2]-left[2];out_dt=right[2]-last[2]
                if (min(jump_in,jump_out)<min_excursion_m or jump_in/in_dt<min_edge_speed_m_s
                        or jump_out/out_dt<min_edge_speed_m_s):continue
                if math.dist(left[3][:2],right[3][:2])>anchor_base_m+anchor_speed_m_s*span:continue
                residuals=[]
                for mid in sequence[1:-1]:
                    fraction=(mid[2]-left[2])/span
                    estimate=[left[3][k]+fraction*(right[3][k]-left[3][k]) for k in (0,1)]
                    residuals.append(math.dist(mid[3][:2],estimate))
                if min(residuals)<min_residual_m:continue
                # Do not chain or overlap removals: the two anchors must remain present.
                keys=[(x[0],x[1]) for x in sequence[1:-1]]
                anchors={(left[0],left[1]),(right[0],right[1])}
                if anchors & set(selected) or any(k in selected or k in protected for k in keys):continue
                protected.update(anchors)
                for mid,residual in zip(sequence[1:-1],residuals):
                    selected[(mid[0],mid[1])]={'frame_index':int(frames[mid[0]]['frame_index']),
                        'timestamp_ns':str(frames[mid[0]]['timestamp_ns']),'elapsed_s':mid[2],
                        'observation_index':mid[1],'track_id':ident,
                        'original_position_m':list(mid[3]),'reason':'isolated_temporal_excursion',
                        'left_anchor_frame':int(frames[left[0]]['frame_index']),
                        'right_anchor_frame':int(frames[right[0]]['frame_index']),
                        'bridge_residual_m':round(residual,6),'anchor_span_s':round(span,6)}
                break
    result=deepcopy(frames)
    for (i,j),_ in selected.items():
        o=result[i]['observations'][j]
        o['surface_corridor_m']=None
        o['position_quality']='withheld_isolated_temporal_excursion'
    return result,sorted(selected.values(),key=lambda x:(x['frame_index'],x['observation_index']))


def withhold_discontinuous_pairs(frames, *, jump_distance_m=.60, jump_speed_m_s=4., max_interval_s=.15):
    """Withhold both endpoints when a continuous ID has an implausible displacement.

    Without reliable evidence about which side is wrong, neither endpoint is
    presented as a measured position. Missing data and unknown IDs are not paired.
    """
    if any(not math.isfinite(x) or x<=0 for x in (jump_distance_m,jump_speed_m_s,max_interval_s)):
        raise ValueError('invalid discontinuity thresholds')
    selected={}; events=[]; previous=None
    for i,frame in enumerate(frames):
        t=float(frame['elapsed_s']);idx=int(frame['frame_index']); stamp=int(frame['timestamp_ns'])
        if previous is not None:
            old_i,old_idx,old_t,old_stamp,old_positions=previous
            if idx<=old_idx or t<=old_t or stamp<=old_stamp:raise ValueError('frames must be strictly ordered')
        current={}
        for j,o in enumerate(frame['observations']):
            ident=o.get('track_id');p=o.get('surface_corridor_m')
            if ident is None or p is None:continue
            if ident in current:raise ValueError('multiple positioned observations with same ID in a frame')
            if len(p)!=3 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in p):raise ValueError('invalid position')
            current[ident]=(j,p)
        if previous is not None and i==old_i+1 and idx==old_idx+1 and t-old_t<=max_interval_s:
            for ident in old_positions.keys() & current.keys():
                old_j,old_p=old_positions[ident];j,p=current[ident];dt=t-old_t;dist=math.dist(old_p[:2],p[:2])
                if dist>=jump_distance_m and dist/dt>=jump_speed_m_s:
                    events.append({'reason':'discontinuous_pair_unresolved','track_id':ident,
                        'left_frame':old_idx,'right_frame':idx,'left_time_s':old_t,'right_time_s':t,
                        'distance_m':round(dist,6),'interval_s':round(dt,6),'speed_m_s':round(dist/dt,6),
                        'left_position_m':list(old_p),'right_position_m':list(p)})
                    selected[(old_i,old_j)]=True;selected[(i,j)]=True
        previous=(i,idx,t,stamp,current)
    result=deepcopy(frames)
    for i,j in selected:
        o=result[i]['observations'][j]
        o['surface_corridor_m']=None
        o['position_quality']='withheld_unresolved_discontinuity'
    return result,events,len(selected)
