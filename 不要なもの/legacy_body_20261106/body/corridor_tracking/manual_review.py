"""Keep explicit visual exclusions separate from automatic tracking results."""
from collections import defaultdict
from copy import deepcopy


def exclude_reviewed_observations(tracking, evidence_by_obs):
    """Remove only reviewed observations from an independent tracking copy.

    No unreviewed sample is assigned or removed. Derived points are omitted
    entirely because they could bridge an excluded observation; callers can
    still access the original automatic result separately.
    """
    output=deepcopy(tracking)
    by_id={o['obs_id']:o for o in output['observations']}
    if len(by_id)!=len(output['observations']):
        raise ValueError('Duplicate observation ID in tracking result')
    missing=set(evidence_by_obs)-set(by_id)
    if missing:raise ValueError('Reviewed observations absent from tracking result')
    for obs_id,evidence in evidence_by_obs.items():
        point=by_id[obs_id]
        before={key:deepcopy(point.get(key)) for key in
                ['track_id','id_status','xyz','sigma_m','parts','position_source','association_reason']}
        point.update(track_id=None,xyz=None,sigma_m=None,parts=[],position_source='manual_review_excluded',
            id_status='ambiguous',association_reason={'reason':'cross_person_skeleton_review',
            'manual_evidence':deepcopy(evidence)},manual_original=before)
    output['derived']=[]
    retained=defaultdict(list)
    for point in output['observations']:
        if point.get('track_id') is not None:retained[point['track_id']].append(point)
    output['tracks']=[dict(track_id=identity,subject_id=None,
        sdk_ids=sorted({p['sdk_id'] for p in points}),
        start_s=min(p['t'] for p in points),end_s=max(p['t'] for p in points))
        for identity,points in retained.items()]
    output['manual_review']={'kind':'exclude_cross_person_skeleton','reviewed_observation_count':len(evidence_by_obs),
        'derived_points_omitted':True,
        'scope':'Only explicitly reviewed image-frame observations; all other frames remain unreviewed.'}
    return output


def label_visual_review_scope(tracking, reviewed_frame_indices, first_t, last_t):
    """Label review scope without treating unreviewed points as safe or invalid.

    This adds metadata to a separate result copy. A warning between reviewed
    images is not evidence that every intermediate frame contains a mismatch.
    """
    if not reviewed_frame_indices or first_t>last_t:
        raise ValueError('A nonempty reviewed frame set and ordered interval are required')
    if 'manual_review' not in tracking:
        raise ValueError('Review scope can only label a manually reviewed result')
    reviewed=set(reviewed_frame_indices)
    output=deepcopy(tracking)
    for point in output['observations']:
        if point.get('position_source')=='manual_review_excluded':
            if point['frame_index'] not in reviewed or not first_t<=point['t']<=last_t:
                raise ValueError('A reviewed exclusion lies outside the reviewed frames or interval')
            status='reviewed_cross_person_excluded'
        elif point['frame_index'] in reviewed:
            status='other_observation_on_reviewed_image_not_adjudicated'
        elif first_t<=point['t']<=last_t:
            status='unreviewed_between_images_with_crossing'
        else:
            status='unreviewed_outside_review_window'
        point['visual_review_status']=status
    output['manual_review']['review_window_s']=[first_t,last_t]
    output['manual_review']['reviewed_frame_indices']=sorted(reviewed)
    output['manual_review']['visual_review_status_note']='Unreviewed does not mean correct or incorrect; no labels are interpolated.'
    return output
