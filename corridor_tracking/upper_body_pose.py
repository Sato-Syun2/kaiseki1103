"""Estimate pose separately from existing depth positions using local ZED depth exports."""
from __future__ import annotations
import argparse
import csv
from functools import lru_cache
import importlib.metadata
import json
import math
import os
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from corridor_tracking.audit_depth_tracking import packet
from corridor_tracking.data import transform
from corridor_tracking.depth_person_comparison import load_run
from corridor_tracking.spatial_filter import filter_frames
from corridor_tracking.trajectory_quality import withhold_discontinuous_pairs, withhold_isolated_excursions
from depth_person_prototype import calibration_for_camera, digest, load_depth_export, safe_asset

JOINTS = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder', 'left_hip', 'right_hip')


def trusted_mapping(raw, trusted, bounds):
    filtered, selected, _ = filter_frames(raw['frames'], bounds)
    filtered, _ = withhold_isolated_excursions(filtered)
    filtered, _, _ = withhold_discontinuous_pairs(filtered)
    if filtered != trusted['frames'] or raw['metadata'] != trusted['metadata']:
        raise ValueError('trusted coordinates do not reproduce from source and recorded bounds')
    return [dict(zip(indices, frame['observations'])) for indices, frame in zip(selected, filtered)]


@lru_cache(maxsize=1)
def spatial_tree_type():
    try:
        from scipy.spatial import cKDTree
        return cKDTree
    except (ImportError, ValueError):
        return None


def prepare_depth(points, intr):
    """Project valid points once per frame; a spatial index only changes lookup speed."""
    p = points[np.isfinite(points).all(axis=1) & (points[:, 2] > 0)]
    projected = np.column_stack((intr['fx']*p[:,0]/p[:,2]+intr['cx'], intr['fy']*p[:,1]/p[:,2]+intr['cy']))
    tree_type = spatial_tree_type()
    tree = tree_type(projected) if len(projected) and tree_type is not None else None
    return p, projected, tree


def joint_depth(uv, score, points, intr, width, height, threshold=.3, radius=5., min_points=3, max_spread=.35, prepared=None, mask=None, membership=None):
    result = {'xy': None, 'score': None, 'camera_m': None, 'corridor_m': None, 'depth_points': 0, 'depth_spread_m': None, 'depth_points_before_mask': None, 'reason': None}
    if not np.isfinite(score) or not np.isfinite(uv).all():
        result['reason'] = 'nonfinite_keypoint'; return result
    result['xy'] = [float(x) for x in uv]; result['score'] = float(score)
    if score < threshold:
        result['reason'] = 'low_keypoint_score'; return result
    u, v = uv
    if not (0 <= u < width and 0 <= v < height):
        result['reason'] = 'outside_image'; return result
    p, projected, tree = prepare_depth(points, intr) if prepared is None else prepared
    if tree is not None:
        indices = np.asarray(tree.query_ball_point([u,v], radius), dtype=int)
    else:
        indices = np.flatnonzero((projected[:,0]-u)**2+(projected[:,1]-v)**2 <= radius**2)
    result['depth_points_before_mask'] = int(len(indices))
    if mask is not None and len(indices):
        uv_near = np.rint(projected[indices]).astype(int)
        valid = ((uv_near[:,0] >= 0) & (uv_near[:,0] < width) & (uv_near[:,1] >= 0) & (uv_near[:,1] < height))
        selected = np.zeros(len(indices), dtype=bool)
        xy = uv_near[valid]
        selected[valid] = (mask[xy[:,1],xy[:,0]] != 0) & (membership[xy[:,1],xy[:,0]] == 1)
        indices = indices[selected]
    p = p[indices]
    result['depth_points'] = len(p)
    if len(p) < min_points:
        result['reason'] = 'insufficient_person_depth' if mask is not None else 'insufficient_depth'; return result
    z = p[:, 2]; spread = float(np.percentile(z, 90)-np.percentile(z, 10)); result['depth_spread_m'] = spread
    if spread > max_spread:
        result['reason'] = 'ambiguous_depth'; return result
    z = float(np.median(z)); result['camera_m'] = [float((u-intr['cx'])*z/intr['fx']), float((v-intr['cy'])*z/intr['fy']), z]
    result['reason'] = 'ok'
    return result


def axis_yaw(left, right, min_width=.08):
    if left['corridor_m'] is None or right['corridor_m'] is None:
        return {'yaw_deg': None, 'confidence': None, 'reason': 'missing_joint_depth'}
    d = np.asarray(right['corridor_m'][:2])-np.asarray(left['corridor_m'][:2]); width = float(np.linalg.norm(d))
    if width < min_width:
        return {'yaw_deg': None, 'confidence': None, 'reason': 'horizontal_baseline_too_short', 'baseline_m': width}
    yaw = math.degrees(math.atan2(float(d[0]), float(-d[1])))
    return {'yaw_deg': yaw, 'confidence': min(left['score'], right['score']), 'reason': 'ok', 'baseline_m': width}


def combine_yaw(a, b):
    if a['yaw_deg'] is None or b['yaw_deg'] is None:
        return {'yaw_deg': None, 'confidence': None, 'reason': 'missing_shoulder_or_hip_yaw'}
    diff = abs((a['yaw_deg']-b['yaw_deg']+180)%360-180)
    if diff > 60:
        return {'yaw_deg': None, 'confidence': None, 'reason': 'shoulder_hip_disagreement', 'difference_deg': diff}
    x = sum(math.cos(math.radians(y['yaw_deg'])) for y in (a,b)); y = sum(math.sin(math.radians(y['yaw_deg'])) for y in (a,b))
    return {'yaw_deg': math.degrees(math.atan2(y,x)), 'confidence': min(a['confidence'],b['confidence']), 'reason':'ok', 'difference_deg':diff}


def velocity(frames, max_gap=.15):
    previous = {}
    for frame in frames:
        current = {}
        for o in frame['observations']:
            o['speed_m_s'] = None; o['speed_reason'] = 'unknown_id_or_position'
            ident, pos = o['track_id'], o['position_m']
            if ident is None or pos is None: continue
            if ident in current: raise ValueError('duplicate ID in frame')
            if ident in previous:
                old_index, t, p = previous[ident]; dt = frame['elapsed_s']-t
                if frame['frame_index'] == old_index+1 and 0 < dt <= max_gap:
                    o['speed_m_s'] = math.dist(pos[:2],p[:2])/dt; o['speed_reason'] = 'ok'
                else: o['speed_reason'] = 'frame_or_time_gap'
            else: o['speed_reason'] = 'no_previous_position'
            current[ident] = (frame['frame_index'], frame['elapsed_s'], pos)
        previous = current


def make_estimator(config, checkpoint, device, backend='mmpose', threads=2):
    if backend == 'rtmlib-onnx':
        try:
            from rtmlib import RTMPose
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError('rtmlib and onnxruntime are required for the ONNX backend') from exc
        if device != 'cpu': raise ValueError('rtmlib-onnx currently supports CPU only')
        settings = json.loads(Path(config).read_text(encoding='utf-8-sig'))
        names = settings['keypoint_names']
        if len(names) != 17 or len(set(names)) != len(names) or not set(JOINTS).issubset(names):
            raise ValueError('ONNX config must explicitly map 17 unique keypoint names')
        size = settings['model_input_size']
        if len(size) != 2 or any(not isinstance(v, int) or v <= 0 for v in size): raise ValueError('invalid ONNX input size')
        model = RTMPose(str(checkpoint), model_input_size=tuple(size), to_openpose=False, backend='onnxruntime', device='cpu')
        options = ort.SessionOptions(); options.intra_op_num_threads = threads; options.inter_op_num_threads = 1
        model.session = ort.InferenceSession(str(checkpoint), sess_options=options, providers=['CPUExecutionProvider'])
        lookup = {name: names.index(name) for name in JOINTS}
        def infer(image, bbox):
            xy, scores = model(image, bboxes=[list(bbox)])
            if xy.shape != (1,17,2) or scores.shape != (1,17): raise ValueError('unexpected ONNX keypoint output shape')
            return {name: (xy[0,idx],float(scores[0,idx])) for name,idx in lookup.items()}
        return infer
    try:
        from mmpose.apis import init_model, inference_topdown
    except ImportError as exc:
        raise RuntimeError('MMPose 1.x is required in the analysis environment; see docs/upper_body_pose.md') from exc
    model = init_model(str(config), str(checkpoint), device=device)
    names = model.dataset_meta.get('keypoint_id2name', {})
    lookup = {name: int(i) for i, name in names.items()}
    missing = set(JOINTS)-set(lookup)
    if missing: raise ValueError(f'model dataset metadata missing required COCO keypoints: {sorted(missing)}')
    def infer(image, bbox):
        result = inference_topdown(model, image, np.asarray([bbox], dtype=np.float32), bbox_format='xyxy')
        if len(result) != 1: raise ValueError('pose inference did not return exactly one result for the input box')
        inst = result[0].pred_instances
        xy = np.asarray(inst.keypoints)[0]; scores = np.asarray(inst.keypoint_scores)[0]
        return {name: (xy[lookup[name]], float(scores[lookup[name]])) for name in JOINTS}
    return infer


def run(args):
    if args.output.exists(): raise FileExistsError('output already exists; choose a new directory')
    output = args.output.resolve()
    input_roots = [args.positions.resolve(), args.trusted.resolve(), args.person_run.resolve(), *(p.resolve() for p in args.depth)]
    if any(output == root or output.is_relative_to(root) for root in input_roots): raise ValueError('output must not be inside an input directory')
    if str(output).startswith('\\\\') or output.is_relative_to(Path('/data/experiment_data/kaiseki1103')): raise ValueError('pose and image replay output must be on local storage, not the shared root')
    if not (0 <= args.keypoint_threshold <= 1 and args.radius > 0 and args.min_points >= 1 and args.max_spread > 0 and args.threads >= 1): raise ValueError('invalid depth or score thresholds')
    raw, rm = packet(args.positions); trusted, tm = packet(args.trusted)
    if tm.get('source_positions_sha256') != digest(args.positions/'positions.json') or tm.get('source_manifest_sha256') != digest(args.positions/'manifest.json'):
        raise ValueError('trusted packet source hashes differ')
    bounds = tm['bounds']
    if bounds.get('max_x_m') != 10.0 or not all(math.isfinite(float(bounds[k])) for k in ('min_y_m','max_y_m')) or bounds['min_y_m'] > bounds['max_y_m']:
        raise ValueError('trusted coordinates must use X <= 10 m and finite wall bounds')
    mapping = trusted_mapping(raw, trusted, bounds)
    person = load_run(args.person_run); meta = raw['metadata']
    if digest(args.person_run/'manifest.json') != meta.get('person_run_manifest_sha256'):
        raise ValueError('person run does not match coordinates')
    if digest(args.calibration) != meta.get('calibration_sha256'):
        raise ValueError('calibration hash differs from coordinates')
    if person['metadata'].get('source_svo_sha256') != meta.get('source_svo_sha256') or person['metadata'].get('calibration_sha256') != meta.get('calibration_sha256'):
        raise ValueError('person run source or calibration differs')
    if len(person['frames']) != len(raw['frames']): raise ValueError('person frame count differs')
    infer = make_estimator(args.model_config, args.model_checkpoint, args.device, args.backend, args.threads)
    frames = []; depth_hashes = []
    for path in args.depth:
        root, camera, dfs, points, ids, dh = load_depth_export(path)
        if camera['source_svo_sha256'] != meta['source_svo_sha256'] or camera['setup_id'] != meta['setup_id']: raise ValueError('depth source or setup differs')
        cal = calibration_for_camera(args.calibration, camera)
        depth_hashes.append(dh)
        ordered_points = bool(np.all(ids[1:] >= ids[:-1]))
        print(f'Processing depth clip {path}, {len(dfs)} frames', flush=True)
        intr = camera['intrinsics_left']
        for df in dfs:
            idx = int(df['frame_index'])
            if idx != len(frames) or idx >= len(raw['frames']): raise ValueError('depth inputs must cover every frame exactly once, ordered')
            rf = raw['frames'][idx]; pf = person['frames'][idx]
            if int(df['image_timestamp_ns']) != int(rf['timestamp_ns']) or str(pf['timestamp_ns']) != str(rf['timestamp_ns']) or int(pf['frame_index']) != idx or df['image_sha256'] != pf['image_sha256']:
                raise ValueError(f'image, person and coordinate timeline differs at frame {idx}')
            if len(pf['people']) != len(rf['observations']): raise ValueError(f'observation count mismatch at frame {idx}')
            image_path = safe_asset(root, df['image_file']); image = cv2.imread(str(image_path))
            if image is None or image.shape[:2] != (int(camera['height']), int(camera['width'])): raise ValueError('cannot read RGB image')
            try: image_url = quote(os.path.relpath(image_path, args.output.resolve()).replace('\\','/'), safe='/')
            except ValueError as exc: raise ValueError('output and depth images must be on the same drive for local replay') from exc
            frame = {'frame_index':idx, 'timestamp_ns':str(rf['timestamp_ns']), 'elapsed_s':float(rf['elapsed_s']), 'image':image_url, 'observations':[]}
            sample = int(df['sample_index'])
            pts = points[np.searchsorted(ids,sample,'left'):np.searchsorted(ids,sample,'right')] if ordered_points else points[ids == sample]
            prepared = prepare_depth(pts, intr) if pf['people'] else None
            masks = []; membership = None
            if args.depth_region == 'exclusive-mask' and pf['people']:
                if person['metadata'].get('method') != 'mask': raise ValueError('exclusive-mask requires a verified segmentation-mask person run')
                membership = np.zeros((int(camera['height']),int(camera['width'])),dtype=np.uint16)
                for person_obs in pf['people']:
                    path = safe_asset(args.person_run, person_obs['region_mask'])
                    if digest(path) != person_obs['region_mask_sha256']: raise ValueError('person mask hash differs')
                    mask = cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
                    if mask is None or mask.shape != membership.shape: raise ValueError('invalid person mask')
                    mask = mask != 0; masks.append(mask); membership += mask.astype(np.uint16)
            for j, (p, original) in enumerate(zip(pf['people'], rf['observations'])):
                if p['status'] != original['depth_status'] or p.get('surface_corridor_m') != original.get('surface_corridor_m'): raise ValueError(f'person/position mismatch at {idx}:{j}')
                box = p.get('region_bbox_xyxy'); selected = mapping[idx].get(j)
                obs = {'observation_index':j, 'track_id':original.get('track_id'), 'bbox':box, 'position_m':selected.get('surface_corridor_m') if selected is not None else None,
                       'position_status':('outside_trusted_region' if selected is None else selected.get('position_quality', 'available' if selected.get('surface_corridor_m') is not None else 'missing_position')),
                       'joints':{}, 'angles':{}}
                if box is None:
                    obs['pose_reason'] = 'missing_person_box'
                    predictions = {}
                else:
                    predictions = infer(image, box); obs['pose_reason'] = 'ok'
                for name in JOINTS:
                    if name not in predictions:
                        joint = {'xy':None,'score':None,'camera_m':None,'corridor_m':None,'depth_points':0,'depth_spread_m':None,'reason':'missing_person_box'}
                    else:
                        xy, score = predictions[name]; joint = joint_depth(xy, score, pts, intr, camera['width'], camera['height'], args.keypoint_threshold, args.radius, args.min_points, args.max_spread, prepared=prepared, mask=masks[j] if membership is not None else None, membership=membership)
                        if joint['camera_m'] is not None: joint['corridor_m'] = transform(joint['camera_m'], cal)
                    obs['joints'][name] = joint
                js = obs['joints']; shoulder = axis_yaw(js['left_shoulder'],js['right_shoulder']); hip = axis_yaw(js['left_hip'],js['right_hip']); head = axis_yaw(js['left_ear'],js['right_ear'], .04)
                obs['angles'] = {'shoulder':shoulder, 'hip':hip, 'torso':combine_yaw(shoulder,hip), 'head':head}
                frame['observations'].append(obs)
            frames.append(frame)
            if len(frames) % 30 == 0: print(f'Processed {len(frames)} / {len(raw["frames"])} frames', flush=True)
    if len(frames) != len(raw['frames']): raise ValueError('depth inputs are incomplete; re-export missing clips locally')
    velocity(frames)
    metadata = {'group':meta.get('group'), 'recording':meta.get('recording'), 'source_svo_sha256':meta['source_svo_sha256'], 'setup_id':meta['setup_id'], 'calibration_sha256':digest(args.calibration), 'source_positions_sha256':digest(args.positions/'positions.json'), 'trusted_positions_sha256':digest(args.trusted/'positions.json'), 'person_manifest_sha256':digest(args.person_run/'manifest.json'), 'depth_manifests_sha256':depth_hashes, 'model_config_sha256':digest(args.model_config), 'model_checkpoint_sha256':digest(args.model_checkpoint), 'model_config':str(args.model_config), 'model_checkpoint':str(args.model_checkpoint), 'backend':args.backend, 'backend_versions':({name:importlib.metadata.version(name) for name in ('rtmlib','onnxruntime')} if args.backend == 'rtmlib-onnx' else {'mmpose':importlib.metadata.version('mmpose')}), 'threads':args.threads, 'depth_region':args.depth_region, 'device':args.device, 'keypoint_threshold':args.keypoint_threshold, 'radius_px':args.radius, 'min_depth_points':args.min_points, 'max_depth_spread_m':args.max_spread, 'trial_id':args.trial_id, 'code_sha256':digest(Path(__file__)), 'angle_convention':'degrees atan2(Y,X), forward=Z_up cross (right-left); head=ear baseline; unvalidated', 'position_policy':'trusted 10m only; source positions unchanged'}
    result = {'metadata':metadata, 'walls':trusted.get('walls',{}), 'frames':frames}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'pose.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    write_csv(args.output/'pose.csv',result)
    write_gaps(args.output/'gaps.csv', result)
    from corridor_tracking.upper_body_replay import make_page
    (args.output/'pose_replay.html').write_text(make_page(result),encoding='utf-8')
    files = {name:digest(args.output/name) for name in ('pose.json','pose.csv','gaps.csv','pose_replay.html')}
    (args.output/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':files},indent=2)+'\n',encoding='utf-8')
    print(f'Saved {len(frames)} frames to {args.output}')


def write_csv(path, data):
    columns = ['trial_id','group','recording','frame_index','timestamp_ns','elapsed_s','observation_index','track_id','position_x_m','position_y_m','position_z_m','position_status','speed_m_s','speed_reason','shoulder_yaw_deg','shoulder_confidence','shoulder_reason','hip_yaw_deg','hip_confidence','hip_reason','torso_yaw_deg','torso_confidence','torso_reason','head_yaw_deg','head_confidence','head_reason','pose_reason','joints_json']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns); w.writeheader()
        for frame in data['frames']:
            for o in frame['observations'] or [None]:
                row={k:data['metadata'].get(k) for k in ('trial_id','group','recording')}; row.update({k:frame[k] for k in ('frame_index','timestamp_ns','elapsed_s')})
                if o is None: row['pose_reason']='no_person_detection'
                else:
                    row.update({k:o.get(k) for k in ('observation_index','track_id','position_status','speed_m_s','speed_reason','pose_reason')})
                    if o['position_m'] is not None:
                        for key,v in zip(('position_x_m','position_y_m','position_z_m'),o['position_m']): row[key]=v
                    for part,a in o['angles'].items():
                        for dest,src in (('yaw_deg','yaw_deg'),('confidence','confidence'),('reason','reason')): row[part+'_'+dest]=a.get(src)
                    row['joints_json']=json.dumps(o['joints'],ensure_ascii=False,separators=(',',':'),allow_nan=False)
                w.writerow(row)


def write_gaps(path, data):
    """Save consecutive missing samples for known IDs within their observed span."""
    frames = data['frames']
    ids = sorted({o['track_id'] for f in frames for o in f['observations'] if o['track_id'] is not None})
    columns = ['trial_id','group','recording','track_id','measure','first_frame','last_frame','start_s','end_s','sample_count','reasons']
    rows = []
    for ident in ids:
        indices = [i for i,f in enumerate(frames) if any(o['track_id'] == ident for o in f['observations'])]
        for measure in ('shoulder','hip','torso','head','speed'):
            start = None; reasons = set()
            def finish(end):
                if start is not None:
                    rows.append(dict(trial_id=data['metadata']['trial_id'], group=data['metadata']['group'], recording=data['metadata']['recording'], track_id=ident, measure=measure, first_frame=frames[start]['frame_index'], last_frame=frames[end]['frame_index'], start_s=frames[start]['elapsed_s'], end_s=frames[end]['elapsed_s'], sample_count=end-start+1, reasons=';'.join(sorted(reasons))))
            for i in range(indices[0], indices[-1]+1):
                f=frames[i]; o=next((o for o in f['observations'] if o['track_id']==ident), None)
                if o is None: reason='id_not_observed'
                elif measure == 'speed': reason=None if o['speed_m_s'] is not None else o['speed_reason']
                else: reason=None if o['angles'][measure]['yaw_deg'] is not None else o['angles'][measure]['reason']
                if reason is not None:
                    if start is None: start=i; reasons=set()
                    reasons.add(reason)
                else:
                    finish(i-1); start=None; reasons=set()
            finish(indices[-1])
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns); writer.writeheader(); writer.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('positions','trusted','person-run','calibration','model-config','model-checkpoint','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--depth',type=Path,action='append',required=True,help='local depth export, repeated in frame order')
    p.add_argument('--trial-id',required=True,help='stable external trial join key; no conditions inferred')
    p.add_argument('--depth-region',choices=('all','exclusive-mask'),default='all',help='optionally restrict depth points to this person mask excluding overlaps')
    p.add_argument('--backend',choices=('mmpose','rtmlib-onnx'),default='mmpose'); p.add_argument('--threads',type=int,default=2)
    p.add_argument('--device',default='cuda:0'); p.add_argument('--keypoint-threshold',type=float,default=.3); p.add_argument('--radius',type=float,default=5.); p.add_argument('--min-points',type=int,default=3); p.add_argument('--max-spread',type=float,default=.35)
    a=p.parse_args()
    if not a.trial_id.strip(): p.error('trial-id must not be empty')
    run(a)

if __name__ == '__main__': main()
