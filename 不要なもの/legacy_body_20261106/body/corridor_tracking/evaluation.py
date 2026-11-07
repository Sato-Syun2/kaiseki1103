"""Diagnostics and sparse, image-annotated checks; never use predictions as observations."""
from collections import Counter, defaultdict

import numpy as np
from corridor_tracking.assignment import linear_sum_assignment

from corridor_tracking.data import joint_ok


SUPPORTED = {'sdk_estimate','partial_observation_estimate'}


def time_weights(frames):
    times = np.array([f['t'] for f in frames])
    if len(times)<2:
        return {f['frame_index']:0. for f in frames}
    edges = np.r_[times[0],(times[1:]+times[:-1])/2,times[-1]]
    return {f['frame_index']:float(w) for f,w in zip(frames,np.diff(edges))}


def continuity(points,frames):
    """Diagnostics within each produced span, NOT labelled person recall."""
    weights = time_weights(frames)
    by_track = defaultdict(list)
    for p in points:
        if p.get('track_id') is not None and p.get('xyz') is not None and p.get('position_source') in SUPPORTED:
            by_track[p['track_id']].append(p)
    details = []
    for identity,values in by_track.items():
        values.sort(key=lambda x:x['t'])
        covered = {p['frame_index'] for p in values}
        interval = [f for f in frames if values[0]['t'] <= f['t'] <= values[-1]['t']]
        missing, longest = 0.,0.
        for f in interval:
            missing = missing+weights[f['frame_index']] if f['frame_index'] not in covered else 0.
            longest = max(longest,missing)
        total = sum(weights[f['frame_index']] for f in interval)
        support = sum(weights[k] for k in covered)
        details.append(dict(track_id=identity,points=len(values),start_s=values[0]['t'],end_s=values[-1]['t'],
                            support_proxy_s=support,span_support_fraction=support/total if total else None,
                            max_internal_missing_s=longest))
    return details


def baseline_points(data):
    return [dict(obs_id=o['obs_id'],frame_index=o['frame_index'],t=o['t'],track_id=f'sdk:{o["sdk_id"]}',
                 sdk_id=o['sdk_id'],subject_id=None,id_status='sdk_id_unreconciled',
                 association_reason={'rule':'legacy_OK_finite_pelvis_confidence_ge_20'},
                 xyz=o['joints'][0],position_source='sdk_estimate') for o in data['observations'] if o['legacy_valid']]


def diagnostics(data,result):
    base = baseline_points(data)
    supported = [p for p in result['observations'] if p['xyz'] is not None and p['position_source'] in SUPPORTED]
    return dict(frames=len(data['frames']),raw_observations=len(data['observations']),
                baseline_points=len(base),candidate_points=len(supported),
                baseline_tracks=len({p['track_id'] for p in base}),
                candidate_tracks=len({p['track_id'] for p in supported}),
                sources=dict(Counter(p['position_source'] for p in result['observations'])),
                id_status=dict(Counter(p['id_status'] for p in result['observations'])),
                derived_sources=dict(Counter(p['position_source'] for p in result['derived'])),
                baseline_continuity=continuity(base,data['frames']),
                candidate_continuity=continuity(supported,data['frames']),
                absolute_position_accuracy='not_evaluated_no_surveyed_ground_truth',
                limitation='All-sequence counts are diagnostics, not identity accuracy or measured-position recall')


def match_boxes(observations, people):
    matrix = np.full((len(people),len(observations)),1e6)
    for i,person in enumerate(people):
        x0,y0,x1,y1 = person['bbox']
        for j,o in enumerate(observations):
            # Pelvis or chest: do not match a head elsewhere in an incorrectly fitted skeleton.
            k = next((k for k in [0,2,18,22,26] if joint_ok(o,k,need3d=False)),None)
            if k is None:
                continue
            u,v = o['pixels'][k]
            if x0<=u<=x1 and y0<=v<=y1:
                matrix[i,j] = abs(u-(x0+x1)/2)/(x1-x0)+.2*abs(v-(y0+y1)/2)/(y1-y0)
    if not people or not observations:
        return {}
    rr,cc = linear_sum_assignment(matrix)
    return {people[i]['person']:observations[j]['obs_id'] for i,j in zip(rr,cc) if matrix[i,j]<1e5}


def cross_person_anchors(observations, people):
    """Find skeletons whose reliable 2D anchors fall in multiple labelled people.

    A crossing is evidence of ambiguous attribution, not proof of an SDK ID
    switch. Visible-region boxes should be annotated without using detections.
    """
    crossed=[]
    for o in observations:
        if o.get('kind')!='body' or not o.get('current_support'):
            continue
        hits=defaultdict(list)
        for k in [0,2,26]:
            if not joint_ok(o,k,need3d=False):
                continue
            u,v=o['pixels'][k]
            for person in people:
                if person.get('bbox') is None or person.get('visibility')=='uncertain':
                    continue
                x0,y0,x1,y1=person['bbox']
                if x0<=u<=x1 and y0<=v<=y1:
                    hits[person['person']].append(k)
        if len(hits)>1:
            crossed.append(dict(obs_id=o['obs_id'],people=dict(hits)))
    return crossed


def evaluate_checkpoints(data,result,annotations,recording,reject_cross_person=True):
    checkpoints = sorted([c for c in annotations.get('checkpoints',[]) if c['recording']==recording],
                         key=lambda c:int(c['timestamp_ns']))
    raw_by_frame = defaultdict(list)
    for o in data['observations']:
        raw_by_frame[o['frame_index']].append(o)
    candidate = {p['obs_id']:p for p in result['observations']}
    baseline = {p['obs_id']:p for p in baseline_points(data)}
    frames = {f['timestamp_ns']:f for f in data['frames']}
    rows,score = [],{}
    for mode,points in [('baseline',baseline),('candidate',candidate)]:
        hits,total,excluded = 0,0,0
        identities = defaultdict(list)
        tracks_to_people = defaultdict(set)
        for c in checkpoints:
            frame = frames.get(c['timestamp_ns'])
            if frame is None:
                raise ValueError('Annotation timestamp absent from evaluated export')
            crossed=cross_person_anchors(raw_by_frame[frame['frame_index']],c['people']) if reject_cross_person else []
            contested={person for item in crossed for person in item['people']}
            eligible = [o for o in raw_by_frame[frame['frame_index']] if o['obs_id'] in points
                        and points[o['obs_id']].get('xyz') is not None
                        and points[o['obs_id']].get('track_id') is not None
                        and points[o['obs_id']].get('position_source') in SUPPORTED]
            matches = match_boxes(eligible,c['people'])
            for person in c['people']:
                if person['person'] in contested:
                    excluded += 1
                    rows.append(dict(mode=mode,t=frame['t'],person=person['person'],obs_id=None,
                                     track_id=None,has_supported_position=None,
                                     exclusion_reason='cross_person_skeleton'))
                    continue
                total += 1
                obs_id = matches.get(person['person'])
                p = points.get(obs_id)
                identity = p['track_id'] if p else None
                if p:
                    hits += 1
                    identities[person['person']].append(identity)
                    tracks_to_people[identity].add(person['person'])
                rows.append(dict(mode=mode,t=frame['t'],person=person['person'],obs_id=obs_id,
                                 track_id=identity,has_supported_position=p is not None))
        score[mode] = dict(person_checkpoints=total,excluded_person_checkpoints=excluded,matched_positions=hits,
                           checkpoint_support_fraction=hits/total if total else None,
                           identity_changes_lower_bound=sum(sum(a!=b for a,b in zip(v,v[1:])) for v in identities.values()),
                           fragmented_identities_lower_bound=sum(max(0,len(set(v))-1) for v in identities.values()),
                           cross_person_id_reuse_lower_bound=sum(len(v)-1 for v in tracks_to_people.values()),
                           person_track_ids={p:list(dict.fromkeys(v)) for p,v in identities.items()})
    return dict(recording=recording,scope='sparse visually annotated checkpoints, not continuous truth',
                continuous_identity_accuracy=None,continuous_recall=None,continuous_max_missing_s=None,
                overtaking_lead_time_s=None,
                unavailable_reason='Sparse labels do not establish continuous visibility, identity or precise event time',
                scores=score,rows=rows)


def evaluate_intervals(data,result,annotations,recording,reject_cross_person=True):
    """Time-weighted checks on EVERY saved image in explicitly reviewed intervals.

    These are estimates at the legacy saved-image cadence, not 30fps truth.
    Bounds are first/last reviewed timestamps; no label extrapolation outside them.
    """
    raw=defaultdict(list)
    for o in data['observations']:
        raw[o['frame_index']].append(o)
    by_stamp={f['timestamp_ns']:f for f in data['frames']}
    output=[]
    baseline={p['obs_id']:p for p in baseline_points(data)}
    candidate={p['obs_id']:p for p in result['observations']}
    for interval in annotations.get('intervals',[]):
        if interval['recording']!=recording:
            continue
        labels=sorted(interval['frames'],key=lambda x:int(x['timestamp_ns']))
        fs=[by_stamp[c['timestamp_ns']] for c in labels]
        expected=[f for f in data['frames'] if fs[0]['t']<=f['t']<=fs[-1]['t']]
        if [f['timestamp_ns'] for f in expected]!=[f['timestamp_ns'] for f in fs]:
            raise ValueError('Interval labels must cover every saved frame; sparse checkpoints cannot become continuous truth')
        weights=time_weights(fs)
        people=set(p['person'] for c in labels for p in c['people'])
        if any({p['person'] for p in c['people']}!=people for c in labels):
            raise ValueError('Split interval when annotated people change; label uncertainty explicitly')
        for mode,points in [('baseline',baseline),('candidate',candidate)]:
            rows=defaultdict(list)
            for c,f in zip(labels,fs):
                valid_people=[p for p in c['people'] if p.get('bbox') is not None and p.get('visibility')!='uncertain']
                crossed=cross_person_anchors(raw[f['frame_index']],valid_people) if reject_cross_person else []
                contested={person for item in crossed for person in item['people']}
                supported=[o for o in raw[f['frame_index']] if o['obs_id'] in points
                           and points[o['obs_id']].get('xyz') is not None
                           and points[o['obs_id']].get('track_id') is not None
                           and points[o['obs_id']].get('position_source') in SUPPORTED]
                matches=match_boxes(supported,valid_people)
                raw_matches=match_boxes(raw[f['frame_index']],valid_people)
                for person in c['people']:
                    name=person['person'];oid=matches.get(name);p=points.get(oid)
                    raw_point=points.get(raw_matches.get(name),{})
                    rows[name].append(dict(t=f['t'],weight_s=weights[f['frame_index']],
                        included=person.get('visibility')!='uncertain' and name not in contested,
                        exclusion_reason='cross_person_skeleton' if name in contested else None,obs_id=oid,
                        track_id=p['track_id'] if p else None,supported=p is not None,
                        ambiguous=raw_point.get('id_status')=='ambiguous',
                        position_source=p.get('position_source') if p else None))
            id_people=defaultdict(set)
            for person,items in rows.items():
                for x in items:
                    if x['included'] and x['track_id'] is not None:
                        id_people[x['track_id']].add(person)
            for person,items in rows.items():
                known=[x for x in items if x['included']]
                total=sum(x['weight_s'] for x in known)
                support=sum(x['weight_s'] for x in known if x['supported'])
                longest=missing=0.
                uncertain_runs=0;was_uncertain=False
                identities=[]
                for x in items:
                    if not x['included']:
                        missing=0.;was_uncertain=False;continue
                    missing=0. if x['supported'] else missing+x['weight_s']
                    longest=max(longest,missing)
                    uncertain_runs+=bool(x['ambiguous'] and not was_uncertain)
                    was_uncertain=x['ambiguous']
                    if x['track_id'] is not None:
                        identities.append(x['track_id'])
                bracket=interval.get('overtaking_bracket_s') if (person==interval.get('rear_person')
                    and interval.get('overtaking_status')=='confirmed_visual_bracket') else None
                before=[x for x in known if bracket and x['t']<bracket[0] and x['supported']]
                first=before[0]['t'] if before else None
                output.append(dict(interval_id=interval['id'],recording=recording,mode=mode,person=person,
                    start_s=fs[0]['t'],end_s=fs[-1]['t'],evaluated_s=total,support_proxy_s=support,
                    support_fraction=support/total if total else None,max_missing_s=longest if total else None,
                    ambiguous_s=sum(x['weight_s'] for x in known if x['ambiguous']),ambiguous_runs=uncertain_runs,
                    identity_changes=sum(a!=b for a,b in zip(identities,identities[1:])),
                    fragmentation_lower_bound=max(0,len(set(identities))-1),
                    reused_ids=[k for k in dict.fromkeys(identities) if len(id_people[k])>1],
                    pre_overtake_support_s=sum(x['weight_s'] for x in before) if bracket else None,
                    pre_overtake_first_support_s=first,
                    lead_time_bracket_s=[bracket[0]-first,bracket[1]-first] if first is not None else None,
                    overtaking_metric_status='evaluated_with_visual_bracket' if bracket else 'not_evaluated_unconfirmed_event_or_not_designated_rear_person',
                    scope='Only the reviewed interval; midpoint time weights at saved-image cadence; SDK current support is a proxy',
                    samples=items))
    return output
