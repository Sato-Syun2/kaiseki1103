"""Conservative association; raw joints are never overwritten by estimates."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import copy

import cv2
import numpy as np
from corridor_tracking.assignment import linear_sum_assignment

from corridor_tracking.data import finite, joint_ok


@dataclass
class Config:
    retain_s: float = 2.0
    max_speed_m_s: float = 3.5
    acceleration_noise: float = 2.0
    match_cost: float = 3.0
    ambiguity_margin: float = .12
    appearance_weight: float = .8
    pixel_prediction_weight: float = 2.0
    appearance_veto: float = .88
    interpolate_s: float = .2
    predict_s: float = .2
    partial_max_sigma_m: float = .7
    offset_max_age_s: float = 3.0
    partial_enabled: bool = True
    birth_min_x_m: float = .5
    roi_polygon: list | None = None
    smoothing_s: float = 0.0
    branch_review_s: float = .2
    branch_pixel_jump: float = .25
    # Experimental: hold an unmatched, recently seen SDK ID before creating
    # a new track. This never assigns the observation to the previous person.
    unmatched_sdk_hold_s: float = 0.0
    # Experimental alternative for noisy full-frame SDK skeletons.
    pixel_velocity_method: str = 'adjacent'

    @classmethod
    def from_dict(cls, data):
        cfg = cls(**data)
        for k,v in asdict(cfg).items():
            if isinstance(v,(int,float)) and (not np.isfinite(v) or v<0):
                raise ValueError(f'Invalid nonnegative setting: {k}')
        if cfg.retain_s <= 0 or cfg.max_speed_m_s <= 0 or cfg.match_cost <= 0:
            raise ValueError('Retention, speed and match cost must be positive')
        if cfg.predict_s > cfg.retain_s:
            raise ValueError('Prediction must not outlive track retention')
        if cfg.pixel_velocity_method not in ('adjacent','pairwise'):
            raise ValueError('Unknown pixel velocity method')
        if cfg.roi_polygon is not None and (len(cfg.roi_polygon)<3 or not all(finite(p,2) for p in cfg.roi_polygon)):
            raise ValueError('ROI must contain >=3 finite image-coordinate vertices')
        return cfg


PARTS = [18,22,2,5,12,26]


def noise(xyz):
    # A conservative heuristic, not a calibrated confidence interval.
    return .09 + .018 * abs(xyz[0])


def appearance_distance(a,b):
    if a is None or b is None:
        return None
    return float(np.sqrt(max(0.,1-float(np.sum(np.sqrt(np.asarray(a)*np.asarray(b)))))))


def pixel_distance(a,b):
    pairs = [k for k in [0,2,5,12,18,22,26] if joint_ok(a,k,need3d=False) and joint_ok(b,k,need3d=False)]
    if not pairs:
        return None
    distances = [np.linalg.norm(np.asarray(a['pixels'][k])-b['pixels'][k]) for k in pairs]
    scale = 25.
    for o in [a,b]:
        if joint_ok(o,0,need3d=False) and joint_ok(o,26,need3d=False):
            scale = max(scale,float(np.linalg.norm(np.asarray(o['pixels'][0])-o['pixels'][26])))
    return float(np.median(distances))/scale


class Track:
    def __init__(self, identity, obs, config):
        self.id, self.config = identity, config
        self.last = obs
        self.last_t = obs['t']
        self.state_t = obs['t']
        self.x = None
        self.P = np.diag([.2,.2,4.,4.])
        self.appearance = None
        self.appearance_count = 0
        self.offsets = defaultdict(list)
        self.observations = []
        self.pixel_history = []

    def pixel_forecast_error(self,obs):
        if not joint_ok(obs,0,need3d=False) or len(self.pixel_history)<3:
            return None
        history=self.pixel_history[-8:]
        dt=np.diff([v[0] for v in history])
        uv=np.array([v[1] for v in history])
        if self.config.pixel_velocity_method == 'pairwise':
            # Wider, irregular-time baselines reduce amplification of a
            # single-frame pixel jitter. If the history is short, retain the
            # original estimate rather than manufacture a velocity.
            slopes=[(uv[j]-uv[i])/(history[j][0]-history[i][0])
                    for i in range(len(history)) for j in range(i+1,len(history))
                    if history[j][0]-history[i][0] >= .1]
            velocity=np.median(slopes,axis=0) if slopes else np.median(np.diff(uv,axis=0)/dt[:,None],axis=0)
        else:
            velocity=np.median(np.diff(uv,axis=0)/dt[:,None],axis=0)
        predicted=np.median([v[1]+velocity*(obs['t']-v[0]) for v in history],axis=0)
        scale=max(25.,float(np.median([v[2] for v in history])))
        return float(np.linalg.norm(np.asarray(obs['pixels'][0])-predicted))/scale

    def forecast(self,t):
        dt = max(0.,t-self.state_t)
        F = np.eye(4); F[0,2] = F[1,3] = dt
        G = np.array([[dt*dt/2,0],[0,dt*dt/2],[dt,0],[0,dt]])
        return (F@self.x, F@self.P@F.T + G@G.T*self.config.acceleration_noise**2) if self.x is not None else (None,None)

    def estimate(self,obs,offline=False):
        if not obs['current_support']:
            return None,None,[], 'no_current_support'
        # Object-detector head-box centroids are not calibrated as the BODY_34
        # head joint. Reusing the body joint's learned pelvis offset would turn
        # an unverified landmark correspondence into a 3D walking position.
        # Preserve the head observation for 2D association/review only.
        if obs['kind']=='head':
            return None,None,[26], 'two_d_only'
        if obs['root_valid']:
            xyz = np.asarray(obs['joints'][0])
            return xyz,noise(xyz),[0], 'sdk_estimate'
        if not self.config.partial_enabled:
            return None,None,[], 'two_d_only'
        estimates, parts, scatter = [], [], []
        for k in PARTS:
            if not joint_ok(obs,k):
                continue
            history = [v for t,v in self.offsets[k] if abs(t-obs['t']) <= self.config.offset_max_age_s
                       and (offline or t <= obs['t'])]
            if len(history)<3:
                continue
            values = np.asarray(history)
            offset = np.median(values,axis=0)
            spread = float(np.median(np.linalg.norm(values-offset,axis=1)))
            if spread>.25:
                continue
            estimates.append(np.asarray(obs['joints'][k])+offset)
            parts.append(k); scatter.append(spread)
        if not estimates:
            return None,None,[], 'two_d_only'
        xyz = np.median(estimates,axis=0)
        disagreement = float(np.max(np.linalg.norm(np.asarray(estimates)-xyz,axis=1)))
        sigma = noise(xyz)+max(scatter)+(.20 if len(parts)>1 else .35)
        if disagreement > .45 or sigma > self.config.partial_max_sigma_m:
            return None,None,parts,'inconsistent_partial_geometry'
        predicted,P = self.forecast(obs['t'])
        if not offline and predicted is not None and np.linalg.norm(predicted[:2]-xyz[:2]) > 1.0+sigma*2:
            return None,None,parts,'partial_motion_disagreement'
        return xyz,sigma,parts,'partial_observation_estimate'

    def update(self,obs,xyz,sigma,clean_appearance=True):
        if xyz is not None:
            if self.x is None:
                self.x = np.array([xyz[0],xyz[1],0.,0.])
            else:
                x,P = self.forecast(obs['t'])
                H = np.array([[1,0,0,0],[0,1,0,0]])
                R = np.eye(2)*sigma**2
                K = np.linalg.solve(H@P@H.T+R,(P@H.T).T).T
                self.x = x+K@(xyz[:2]-H@x)
                I = np.eye(4)-K@H
                self.P = I@P@I.T+K@R@K.T
                speed = np.linalg.norm(self.x[2:])
                if speed>self.config.max_speed_m_s:
                    self.x[2:] *= self.config.max_speed_m_s/speed
            self.state_t = obs['t']
        if obs['root_valid'] and xyz is not None:
            root = np.asarray(obs['joints'][0])
            for k in PARTS:
                if joint_ok(obs,k):
                    delta = root-np.asarray(obs['joints'][k])
                    if np.linalg.norm(delta) < 1.3:
                        self.offsets[k].append((obs['t'],delta))
        if clean_appearance and obs.get('appearance') is not None:
            a = np.asarray(obs['appearance'])
            self.appearance = a if self.appearance is None else .85*self.appearance+.15*a
            self.appearance_count += 1
        self.last,self.last_t = obs,obs['t']
        self.observations.append(obs)
        if joint_ok(obs,0,need3d=False):
            scale=np.linalg.norm(np.asarray(obs['pixels'][0])-obs['pixels'][26]) if joint_ok(obs,26,need3d=False) else 25.
            self.pixel_history.append((obs['t'],np.asarray(obs['pixels'][0]),scale))


def cost(track, obs, config):
    dt = obs['t']-track.last_t
    xyz,sigma,_,_ = track.estimate(obs)
    pred,P = track.forecast(obs['t'])
    pixel = pixel_distance(track.last,obs)
    app = appearance_distance(track.appearance,obs.get('appearance'))
    reasons = dict(gap_s=dt,pixel_distance=pixel,appearance_distance=app)
    pixel_innovation=track.pixel_forecast_error(obs)
    reasons['pixel_prediction_error']=pixel_innovation
    same_sdk = obs['kind']==track.last['kind'] and obs['sdk_id']==track.last['sdk_id'] and obs['sdk_id']>=0
    score = 0.
    if app is not None and track.appearance_count >= 3 and app > config.appearance_veto:
        return 1e6,dict(reasons,rejection='appearance_change')
    if xyz is not None and pred is not None:
        delta = xyz[:2]-pred[:2]
        S = P[:2,:2]+np.eye(2)*sigma**2
        maha = float(delta@np.linalg.solve(S,delta))
        dist = float(np.linalg.norm(delta))
        reasons.update(mahalanobis_sq=maha,distance_m=dist)
        # 2D identity updates do not advance the 3D state clock. Gating by last_t
        # here permanently rejects legitimate recovery after a depth outage.
        position_age=max(0.,obs['t']-track.state_t)
        reasons['position_age_s']=position_age
        reachable_distance=float(np.linalg.norm(xyz[:2]-track.x[:2]))
        reasons['distance_from_last_state_m']=reachable_distance
        # Physical reachability is centred on the last state, not the already
        # extrapolated position. Otherwise an old velocity can lock out a turn.
        if maha > 25 or reachable_distance > .6+2*sigma+config.max_speed_m_s*position_age:
            if same_sdk and pixel is not None and pixel < .25 and dt < .5:
                # Stable image support can maintain identity while a stereo depth spike is rejected.
                reasons['position_rejected_motion_outlier'] = True
                score += .8
            else:
                return 1e6,dict(reasons,rejection='motion_gate')
        else:
            score += np.sqrt(maha)*.45
    elif pixel is None:
        return 1e6,dict(reasons,rejection='no_comparable_geometry')
    else:
        if pixel > .8+dt*4:
            return 1e6,dict(reasons,rejection='pixel_gate')
        score += pixel*.9 + .4
    if pixel is not None:
        if dt < .3 and pixel>2.0:
            return 1e6,dict(reasons,rejection='pixel_jump')
        score += min(pixel,3)*.25
    if app is not None:
        score += app*config.appearance_weight
    if pixel_innovation is not None:
        score += min(pixel_innovation,3)*config.pixel_prediction_weight
    if same_sdk:
        score -= .3
    score += dt*.08
    reasons['sdk_id_hint'] = same_sdk
    return max(0.,float(score)),reasons


def in_roi(obs,config):
    if config.roi_polygon is None:
        return True
    k = next((k for k in [0,2,26] if joint_ok(obs,k,need3d=False)),None)
    if k is None:
        return False
    return cv2.pointPolygonTest(np.asarray(config.roi_polygon,dtype=np.float32),tuple(obs['pixels'][k]),False)>=0


def point(obs,track_id,xyz,sigma,parts,source,status,reason):
    return dict(obs_id=obs['obs_id'],frame_index=obs['frame_index'],timestamp_ns=obs['timestamp_ns'],
                t=obs['t'],track_id=track_id,subject_id=None,sdk_id=obs['sdk_id'],kind=obs['kind'],
                xyz=None if xyz is None else np.asarray(xyz).tolist(), sigma_m=sigma,
                sigma_is_calibrated=False, parts=parts,position_source=source,
                id_status=status,association_reason=reason,
                support_is_direct_measurement=False,
                support_note='SDK keypoints may include fitted/predicted values; current support is a proxy')


def run_tracker(data, config: Config):
    tracks, result, audit = [], [], []
    groups = defaultdict(list)
    for obs in data['observations']:
        groups[obs['frame_index']].append(obs)
    for frame in data['frames']:
        observations = groups[frame['frame_index']]
        usable = []
        duplicates = {}
        recent_sdk = {(tr.last['kind'],tr.last['sdk_id']) for tr in tracks if frame['t']-tr.last_t<.5}
        ordered = sorted(observations,key=lambda o:(-(int((o['kind'],o['sdk_id']) in recent_sdk)),
                                                   -(o.get('confidence') or 0),o['obs_id']))
        retained = []
        for o in ordered:
            duplicate = None
            if o['kind']=='body' and o['root_valid']:
                for b in retained:
                    if b['kind']!='body' or not b['root_valid']:
                        continue
                    d = pixel_distance(o,b)
                    app = appearance_distance(o.get('appearance'),b.get('appearance'))
                    if (d is not None and d<.14 and app is not None and app<.2
                            and np.linalg.norm(np.asarray(o['joints'][0])-b['joints'][0])<.6):
                        duplicate = b['obs_id'];break
            if duplicate:
                duplicates[o['obs_id']] = duplicate
            else:
                retained.append(o)
        for o in observations:
            if o['obs_id'] in duplicates:
                result.append(point(o,None,None,None,[],'duplicate_observation','duplicate',
                                    {'duplicate_of':duplicates[o['obs_id']]}))
                continue
            if not o['current_support'] or not in_roi(o,config):
                result.append(point(o,None,None,None,[],'no_current_support','unassigned',{'reason':'state_stale_or_roi'}))
                continue
            # Proximity alone is not enough to suppress two independent head
            # boxes near the same body, or one head near multiple bodies.
            if o['kind']=='head' and joint_ok(o,26,need3d=False):
                bodies=[b for b in retained if b['kind']=='body' and b['current_support']
                        and in_roi(b,config) and joint_ok(b,26,need3d=False)]
                heads=[h for h in retained if h['kind']=='head' and h['current_support']
                       and in_roi(h,config) and joint_ok(h,26,need3d=False)]
                near=[b for b in bodies if np.linalg.norm(np.asarray(b['pixels'][26])-o['pixels'][26])<15]
                competitors=[h for h in heads if any(np.linalg.norm(np.asarray(b['pixels'][26])-h['pixels'][26])<15 for b in near)]
                if len(near)>1 or (len(near)==1 and len(competitors)>1):
                    reason=dict(reason='ambiguous_head_body_proximity',
                        candidate_body_obs_ids=[b['obs_id'] for b in near],
                        competing_head_obs_ids=[h['obs_id'] for h in competitors])
                    audit.append(dict(obs_id=o['obs_id'],**reason))
                    result.append(point(o,None,None,None,[26],'two_d_only','ambiguous',reason))
                    continue
                if len(near)==1:
                    audit.append(dict(obs_id=o['obs_id'],reason='head_supplements_body',body_obs_id=near[0]['obs_id']))
                    result.append(point(o,None,None,None,[26],'supplemental_head','supplemental',{'body_obs_id':near[0]['obs_id']}))
                    continue
            if not any(joint_ok(o,k,need3d=False) for k in [0,2,5,12,18,22,26]):
                result.append(point(o,None,None,None,[],'two_d_only','unassigned',{'reason':'no_visible_anchor'}))
                continue
            usable.append(o)
        active = [tr for tr in tracks if frame['t']-tr.last_t <= config.retain_s]
        matrix = np.full((len(active),len(usable)),1e6)
        reasons = {}
        for i,tr in enumerate(active):
            for j,obs in enumerate(usable):
                matrix[i,j],reasons[i,j] = cost(tr,obs,config)
        assigned,ambiguous = {},{}
        if active and usable:
            augmented = np.concatenate([matrix,np.full((len(active),len(active)),config.match_cost)],axis=1)
            rr,cc = linear_sum_assignment(augmented)
            for i,j in zip(rr,cc):
                if j>=len(usable) or matrix[i,j]>=config.match_cost:
                    continue
                row_alt = np.delete(matrix[i],j)
                col_alt = np.delete(matrix[:,j],i)
                alternative = min(np.min(row_alt,initial=np.inf),np.min(col_alt,initial=np.inf),config.match_cost)
                if alternative-matrix[i,j] < config.ambiguity_margin:
                    ambiguous[j] = [active[k].id for k in range(len(active)) if matrix[k,j]<config.match_cost]
                else:
                    assigned[j] = (active[i],reasons[i,j],float(matrix[i,j]))
        for j,obs in enumerate(usable):
            if j in ambiguous:
                evidence=[dict(track_id=active[i].id,cost=float(matrix[i,j]),**reasons[i,j])
                          for i in range(len(active)) if matrix[i,j]<config.match_cost]
                result.append(point(obs,None,None,None,[],'two_d_only','ambiguous',
                                    {'candidate_tracks':ambiguous[j],'candidate_evidence':evidence}))
                continue
            if j in assigned:
                tr,reason,score = assigned[j]
                status = 'associated'
                reason = dict(reason,cost=score)
            else:
                recent_same_sdk = [tr for tr in active if obs['sdk_id'] >= 0
                    and tr.last['kind'] == obs['kind'] and tr.last['sdk_id'] == obs['sdk_id']
                    and 0 < obs['t'] - tr.last_t <= config.unmatched_sdk_hold_s]
                if recent_same_sdk:
                    result.append(point(obs,None,None,None,[],'unresolved_identity','ambiguous',
                        {'reason':'unmatched_recent_sdk_id_hold',
                         'candidate_tracks':[tr.id for tr in recent_same_sdk]}))
                    continue
                if obs['root_valid'] and obs['joints'][0][0] < config.birth_min_x_m:
                    result.append(point(obs,None,None,None,[],'two_d_only','unassigned',{'reason':'near_camera_birth_excluded'}))
                    continue
                # Unmatched partial observations may become a 2D track, but not an invented pelvis.
                tr = Track(len(tracks)+1,obs,config)
                tracks.append(tr)
                evidence=[dict(track_id=active[i].id,cost=float(matrix[i,j]),**reasons[i,j])
                          for i in sorted(range(len(active)),key=lambda i:matrix[i,j])[:3]]
                status,reason = 'initialized',{'reason':'new_track','prior_candidates':evidence}
            xyz,sigma,parts,source = tr.estimate(obs)
            if reason.get('position_rejected_motion_outlier'):
                xyz,sigma,parts,source = None,None,[],'rejected_position'
            clean = True
            for other in usable:
                if other is not obs:
                    d = pixel_distance(obs,other)
                    if d is not None and d < .6:
                        clean = False
            tr.update(obs,xyz,sigma,clean)
            result.append(point(obs,tr.id,xyz,sigma,parts,source,status,reason))
    # Review the preceding instant when one SDK identity branches into two people.
    # A large image innovation immediately before that branch is unresolved, even
    # if online association had already attached it to the old track.
    reviewed=review_sdk_branches(result,config)
    for identity,t in reviewed:
        tr=tracks[identity-1]
        for k in tr.offsets:
            tr.offsets[k]=[(stamp,v) for stamp,v in tr.offsets[k] if stamp!=t]
    # Offline partial recovery uses actual visible joints and same-track anatomical offsets.
    # It does not back-extrapolate an unobserved person before the first observation.
    by_obs = {o['obs_id']:o for o in data['observations']}
    for r in result:
        if r['track_id'] is None or r['xyz'] is not None or r['position_source']=='rejected_position':
            continue
        tr = tracks[r['track_id']-1]
        xyz,sigma,parts,source = tr.estimate(by_obs[r['obs_id']],offline=True)
        if xyz is not None:
            neighbours = [p for p in result if p['track_id']==r['track_id'] and p['xyz'] is not None
                          and abs(p['t']-r['t']) <= config.offset_max_age_s]
            if neighbours:
                nearest = min(neighbours,key=lambda p:abs(p['t']-r['t']))
                if np.linalg.norm(xyz[:2]-np.asarray(nearest['xyz'])[:2]) > .5+config.max_speed_m_s*abs(nearest['t']-r['t']):
                    continue
                r.update(xyz=xyz.tolist(),sigma_m=sigma,parts=parts,position_source=source)
                r['association_reason']['offline_anatomical_offset'] = True
    return dict(schema_version=2,config=asdict(config),observations=result,audit=audit,
                derived=derive_points(result,data['frames'],config),
                tracks=[dict(track_id=t.id,subject_id=None,sdk_ids=sorted(set(o['sdk_id'] for o in t.observations)),
                             start_s=t.observations[0]['t'],end_s=t.last_t) for t in tracks])


def review_sdk_branches(points,config):
    groups=defaultdict(list)
    for p in points:
        groups[p['frame_index']].append(p)
    previous={};reviewed=[]
    for frame in groups.values():
        assigned={p['track_id'] for p in frame if p['track_id'] is not None}
        for p in frame:
            if p['track_id'] is None or p['sdk_id']<0:
                continue
            key=p['kind'],p['sdk_id'];q=previous.get(key)
            if (q and q['track_id'] is not None and q['track_id']!=p['track_id']
                    and q['track_id'] in assigned and 0<p['t']-q['t']<=config.branch_review_s):
                reason=q['association_reason']
                jump=max(reason.get('pixel_prediction_error') or 0,reason.get('pixel_distance') or 0)
                if jump>config.branch_pixel_jump:
                    old_id=q['track_id']
                    reviewed.append((old_id,q['t']))
                    q.update(proposed_track_id=old_id,track_id=None,id_status='ambiguous',
                             rejected_xyz=q['xyz'],xyz=None,sigma_m=None,position_source='unresolved_identity')
                    reason.update(posthoc_sdk_branch=True,candidate_tracks=[old_id,p['track_id']],
                                  branch_observation=p['obs_id'])
            previous[key]=p
    return reviewed


def derive_points(points, frames, config):
    output = []
    by_track = defaultdict(list)
    for p in points:
        if p['track_id'] is not None and p['xyz'] is not None:
            by_track[p['track_id']].append(p)
    for identity,items in by_track.items():
        items.sort(key=lambda p:p['t'])
        existing = {p['frame_index'] for p in items}
        for a,b in zip(items,items[1:]):
            gap = b['t']-a['t']
            if gap<=0 or gap>config.interpolate_s:
                continue
            if np.linalg.norm(np.asarray(b['xyz'])[:2]-np.asarray(a['xyz'])[:2])/gap > config.max_speed_m_s:
                continue
            for f in frames:
                if a['t']<f['t']<b['t'] and f['frame_index'] not in existing:
                    alpha = (f['t']-a['t'])/gap
                    xyz = (1-alpha)*np.asarray(a['xyz'])+alpha*np.asarray(b['xyz'])
                    output.append(dict(track_id=identity,subject_id=None,obs_id=None,frame_index=f['frame_index'],
                                       timestamp_ns=f['timestamp_ns'],t=f['t'],xyz=xyz.tolist(),
                                       position_source='interpolated',id_status='derived',parts=[],
                                       endpoints=[a['obs_id'],b['obs_id']],sigma_m=max(a['sigma_m'],b['sigma_m'])+gap*.5))
        if len(items)>=2 and config.predict_s>0:
            a,b = items[-2:]
            dt = b['t']-a['t']
            if 0<dt<=.5:
                velocity = (np.asarray(b['xyz'])-a['xyz'])/dt
                if np.linalg.norm(velocity[:2])<=config.max_speed_m_s:
                    for f in frames:
                        age = f['t']-b['t']
                        if 0<age<=config.predict_s:
                            output.append(dict(track_id=identity,subject_id=None,obs_id=None,frame_index=f['frame_index'],
                                               timestamp_ns=f['timestamp_ns'],t=f['t'],xyz=(np.asarray(b['xyz'])+age*velocity).tolist(),
                                               position_source='predicted',id_status='derived',parts=[],
                                               endpoints=[a['obs_id'],b['obs_id']],sigma_m=b['sigma_m']+age*config.max_speed_m_s))
        if config.smoothing_s>0:
            for p in items:
                nearby = [q for q in items if abs(q['t']-p['t']) <= config.smoothing_s/2]
                weights = [1/max(.01,q['sigma_m'])**2 for q in nearby]
                output.append(dict(track_id=identity,subject_id=None,obs_id=None,frame_index=p['frame_index'],
                                   timestamp_ns=p['timestamp_ns'],t=p['t'],xyz=np.average([q['xyz'] for q in nearby],axis=0,weights=weights).tolist(),
                                   position_source='smoothed',id_status='derived',parts=[],endpoints=[q['obs_id'] for q in nearby],
                                   sigma_m=None))
    return output


def apply_anchors(result,anchors):
    """Merge/split explicitly reviewed track intervals, without changing positions.

    An anchor names an obs_id and a recording-local person_key. The default scope
    is that automatic track; start_s/end_s restrict it to a reviewed interval.
    scope=observation can assign one ambiguous observation without inventing XYZ.
    """
    output = copy.deepcopy(result)
    mapping = {}
    by_obs = {p['obs_id']:p for p in output['observations']}
    for a in anchors:
        obs = by_obs[a['obs_id']]
        if obs['track_id'] is None and a.get('scope')!='observation':
            raise ValueError('Anchor must refer to an assigned observation; review ambiguity first')
        if not isinstance(a['person_key'],str) or not a['person_key']:
            raise ValueError('Recording-local person_key must be a nonempty string')
        value = (a['person_key'],a.get('subject_id'))
        start,end=a.get('start_s',-np.inf),a.get('end_s',np.inf)
        if start>end:
            raise ValueError('Anchor interval is reversed')
        selected=[obs] if a.get('scope')=='observation' else [p for p in output['observations']
                  if p['track_id']==obs['track_id'] and start<=p['t']<=end]
        if not selected or obs not in selected:
            raise ValueError('Anchor observation must be within its reviewed interval')
        for p in selected:
            key=p['obs_id']
            if key in mapping and mapping[key]!=value:
                raise ValueError('Conflicting anchors inside one track interval')
            mapping[key]=value
    seen = set()
    for p in output['observations']:
        if p['obs_id'] in mapping:
            person,subject = mapping[p['obs_id']]
            slot = (p['frame_index'],person)
            if slot in seen:
                raise ValueError('Anchors would merge simultaneous observations')
            seen.add(slot)
            p.update(automatic_track_id=p['track_id'],track_id='manual:'+person,
                     manual_person_key=person,subject_id=subject,anchor_applied=True,id_status='manual_anchor')
    derived=[]
    for p in output['derived']:
        endpoints=[by_obs[k] for k in p['endpoints']]
        ids={q['track_id'] for q in endpoints}
        if len(ids)==1:
            p.update(automatic_track_id=p['track_id'],track_id=endpoints[0]['track_id'],
                     subject_id=endpoints[0].get('subject_id'))
            derived.append(p)
    output['derived']=derived
    output['automatic_tracks']=output['tracks']
    groups=defaultdict(list)
    for p in output['observations']:
        if p['track_id'] is not None:
            groups[p['track_id']].append(p)
    output['tracks']=[dict(track_id=k,subject_id=items[0].get('subject_id'),
                           sdk_ids=sorted(set(p['sdk_id'] for p in items)),
                           start_s=min(p['t'] for p in items),end_s=max(p['t'] for p in items))
                      for k,items in groups.items()]
    output['manual_anchors'] = anchors
    return output
