"""Versioned adapters for legacy and full-frame ZED exports (no SDK dependency)."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def finite(v, size=3):
    if not isinstance(v, (list, tuple, np.ndarray)) or len(v) != size:
        return False
    return all(isinstance(x, (int, float, np.number)) and np.isfinite(x) for x in v)


def transform(point, calibration):
    if not finite(point):
        return None
    if 'transform_camera_to_corridor' in calibration:
        m = np.asarray(calibration['transform_camera_to_corridor'], dtype=float)
        return (m[:3, :3] @ np.asarray(point) + m[:3, 3]).tolist()
    floor, basis = calibration['floor_plane_camera_image'], calibration['corridor_basis_camera_image']
    down = np.asarray(floor['normal_down'], dtype=float)
    delta = np.asarray(point) + float(floor['offset_m']) * down
    axes = [basis['X_into_hallway'], basis.get('Y_positive_toward_ZED_visible_far_wall',
                                           basis.get('Y_positive_away_from_visible_wall')), basis['Z_up']]
    return (np.asarray(axes) @ delta).tolist()


def joint_ok(obs, k, confidence=20, need3d=True):
    if k >= len(obs['pixels']) or k >= len(obs['joint_confidence']):
        return False
    c, uv = obs['joint_confidence'][k], obs['pixels'][k]
    return (isinstance(c, (int, float)) and np.isfinite(c) and c >= confidence
            and finite(uv, 2) and 0 <= uv[0] < obs['width'] and 0 <= uv[1] < obs['height']
            and (not need3d or (k < len(obs['joints']) and finite(obs['joints'][k]))))


def appearance(image, obs):
    """Saturated hue histogram inside the observed torso; absent if support is small."""
    if image is None or not all(joint_ok(obs, k, need3d=False) for k in [5,12,22,18]):
        return None
    poly = np.rint([obs['pixels'][k] for k in [5,12,22,18]]).astype(np.int32)
    if abs(cv2.contourArea(poly)) < 45:
        return None
    x,y,w,h = cv2.boundingRect(poly)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > image.shape[1] or y+h > image.shape[0]:
        return None
    mask = np.zeros((h,w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, poly - [x,y], 255)
    hsv = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
    mask[(hsv[:,:,1] < 45) | (hsv[:,:,2] < 35)] = 0
    if np.count_nonzero(mask) < 20:
        return None
    hist = cv2.calcHist([hsv], [0], mask, [18], [0,180]).ravel()
    return (hist / hist.sum()).tolist()


def load_export(folder: Path, calibration: dict, with_appearance=True, heads_folder: Path | None=None):
    folder = Path(folder).resolve()
    camera = json.loads((folder/'camera.json').read_text(encoding='utf-8-sig'))
    if calibration.get('applies_to'):
        if camera.get('setup_id')!=calibration.get('setup_id'):
            raise ValueError('Calibration setup_id does not match this recording')
        for key,value in calibration['applies_to'].items():
            if value is not None and camera.get(key)!=value:
                raise ValueError(f'Calibration does not apply to camera {key}')
    if camera.get('body_format', 'BODY_34') != 'BODY_34':
        raise ValueError('Only BODY_34 is supported; joint indices must not silently change')
    if camera.get('coordinate_units', 'meter') not in ['meter','METER','m']:
        raise ValueError('Input camera coordinates must be in metres')
    if not str(camera.get('coordinate_system','IMAGE')).startswith('IMAGE'):
        raise ValueError('Input camera coordinates must use IMAGE axes')
    if camera.get('schema_version',1) >= 2:
        manifest = json.loads((folder/'manifest.json').read_text())
        if manifest.get('status') != 'complete':
            raise ValueError('Refusing an incomplete SDK export')
        from zed_sdk_package.tracking_v2.validate_export import validate_export
        validate_export(folder)
    frame_rows = read_csv(folder/'frames.csv')
    if not frame_rows:
        raise ValueError('Export contains no frames')
    origin = int(frame_rows[0]['image_timestamp_ns'])
    frames, by_frame, stamps = [], {}, set()
    for row in frame_rows:
        stamp, idx = int(row['image_timestamp_ns']), int(row['frame_index'])
        if stamp in stamps or (frames and (stamp <= int(frames[-1]['timestamp_ns']) or idx<=frames[-1]['frame_index'])) or idx in by_frame:
            raise ValueError('Frame indices and timestamps must be unique and increasing')
        stamps.add(stamp)
        image_file = row.get('image_file','').replace('\\','/')
        image_path = folder/image_file if image_file else None
        if image_path is not None and not image_path.is_file():
            raise FileNotFoundError(image_path)
        f = dict(frame_index=idx, sample_index=int(row.get('sample_index') or idx),
                 timestamp_ns=str(stamp), t=(stamp-origin)/1e9, image=image_file,
                 image_path=str(image_path) if image_path else None)
        frames.append(f)
        by_frame[idx] = f
    if not any(f['image'] for f in frames):
        raise ValueError('At least one saved image is required for replay')
    observations = []
    cached_frame, cached_image = None, None
    for rownum, row in enumerate(read_csv(folder/'bodies.csv')):
        idx = int(row['frame_index'])
        if idx not in by_frame:
            raise ValueError(f'Body references missing frame {idx}')
        f = by_frame[idx]
        if int(row['image_timestamp_ns']) != int(f['timestamp_ns']):
            raise ValueError(f'Body/image timestamp mismatch at frame {idx}')
        raw_joints = json.loads(row['keypoints_3d_camera_json'])
        conf = json.loads(row['keypoint_confidence_json'])
        obs = dict(obs_id=f'body:{idx}:{rownum}', frame_index=idx, sample_index=f['sample_index'],
                   timestamp_ns=f['timestamp_ns'], t=f['t'], sdk_id=int(row['body_id']), kind='body',
                   state=row['tracking_state'].upper(), pixels=json.loads(row['keypoints_2d_json']),
                   joints=[transform(p,calibration) for p in raw_joints], joint_confidence=conf,
                   confidence=float(row['confidence']) if row.get('confidence') else None,
                   is_new=None if row.get('is_new','') == '' else row['is_new'].lower() in ['true','1'],
                   detection_timestamp_ns=row.get('detection_timestamp_ns') or None,
                   width=int(camera['width']), height=int(camera['height']),
                   source=dict(file='bodies.csv',row=rownum+2), raw=row.copy())
        obs['legacy_valid'] = bool(obs['state']=='OK' and raw_joints and finite(raw_joints[0])
                                   and conf and isinstance(conf[0],(float,int)) and conf[0]>=20)
        obs['current_support'] = (obs['state']=='OK' and obs['is_new'] is not False)
        if obs['detection_timestamp_ns']:
            obs['current_support'] &= abs(int(obs['detection_timestamp_ns'])-int(f['timestamp_ns'])) <= 1000000
        obs['root_valid'] = obs['current_support'] and joint_ok(obs,0)
        if with_appearance:
            if cached_frame != idx:
                cached_frame = idx
                cached_image = cv2.imread(f['image_path']) if f['image_path'] else None
            obs['appearance'] = appearance(cached_image,obs)
        else:
            obs['appearance'] = None
        observations.append(obs)
    if heads_folder:
        heads_folder=Path(heads_folder).resolve()
        from zed_sdk_package.tracking_v2.validate_export import validate_export
        validate_export(heads_folder)
        head_camera = json.loads((heads_folder/'camera.json').read_text())
        # Cross-pass synchronization must prove recording identity, not just equal SDK IDs.
        if not camera.get('source_svo_sha256') or camera['source_svo_sha256'] != head_camera.get('source_svo_sha256'):
            raise ValueError('Head/body fusion requires matching source_svo_sha256')
        if json.loads((heads_folder/'manifest.json').read_text()).get('status') != 'complete':
            raise ValueError('Head export is incomplete')
        for key in ['width','height','serial_number','coordinate_system','coordinate_units','depth_mode','intrinsics_left','setup_id']:
            if camera.get(key)!=head_camera.get(key):
                raise ValueError(f'Head/body export metadata mismatch: {key}')
        if head_camera.get('detection_kind')!='heads':
            raise ValueError('Expected a separate head detection export')
        # Validate the complete timeline, including frames with no detections.
        # Matching only timestamps that appear in heads.csv can silently accept
        # an extra/missing zero-detection frame in an otherwise complete pass.
        head_frames=read_csv(heads_folder/'frames.csv')
        def timeline(rows):
            return [(int(r['frame_index']),int(r['svo_frame_index']),int(r['image_timestamp_ns'])) for r in rows]
        if timeline(frame_rows)!=timeline(head_frames):
            raise ValueError('Head/body full frame timeline mismatch')
        by_stamp = {f['timestamp_ns']: f for f in frames}
        for rownum,row in enumerate(read_csv(heads_folder/'heads.csv')):
            if row['image_timestamp_ns'] not in by_stamp:
                raise ValueError('Head timestamp absent from body frame timeline')
            f = by_stamp[row['image_timestamp_ns']]
            pixels, joints, conf = [None]*34, [None]*34, [None]*34
            box = json.loads(row['bounding_box_2d_json'])
            if len(box)!=4 or not all(finite(p,2) for p in box):
                continue
            pixels[26] = np.mean(box,axis=0).tolist()
            joints[26] = transform(json.loads(row['position_json']),calibration)
            conf[26] = float(row['confidence'])
            obs = dict(obs_id=f'head:{f["frame_index"]}:{rownum}',frame_index=f['frame_index'],
                       sample_index=f['sample_index'],timestamp_ns=f['timestamp_ns'],t=f['t'],
                       sdk_id=int(row['object_id']),kind='head',state=row['tracking_state'],
                       pixels=pixels,joints=joints,joint_confidence=conf,confidence=conf[26],
                       width=camera['width'],height=camera['height'],appearance=None,
                       is_new=row.get('is_new','').lower() in ['true','1'],legacy_valid=False,
                       current_support=row['tracking_state']=='OK' and row.get('is_new','').lower() in ['true','1'],
                       root_valid=False,raw=row,source=dict(file=str(heads_folder/'heads.csv'),row=rownum+2))
            obs['detection_timestamp_ns']=row.get('detection_timestamp_ns') or None
            if obs['detection_timestamp_ns']:
                obs['current_support'] &= abs(int(obs['detection_timestamp_ns'])-int(f['timestamp_ns']))<=1000000
            observations.append(obs)
    observations.sort(key=lambda o:(o['t'],o['kind']!='body',o['obs_id']))
    hashes={f:sha256(folder/f) for f in ['camera.json','frames.csv','bodies.csv']}
    for f in ['manifest.json','assets.csv']:
        if (folder/f).is_file():
            hashes[f]=sha256(folder/f)
    if heads_folder:
        hashes.update({'heads/'+f:sha256(heads_folder/f) for f in ['camera.json','frames.csv','heads.csv','manifest.json','assets.csv']})
    image_hashes={f['image']:sha256(Path(f['image_path'])) for f in frames if f['image_path']}
    return dict(schema_version=2,source=str(folder),camera=camera,frames=frames,observations=observations,
                timeline_origin_ns=str(origin),duration_s=frames[-1]['t'],
                input_hashes=hashes,image_hashes=image_hashes)
