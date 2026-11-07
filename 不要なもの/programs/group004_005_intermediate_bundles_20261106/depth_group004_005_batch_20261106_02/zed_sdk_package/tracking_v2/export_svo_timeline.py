#!/usr/bin/env python3
"""Read a complete local SVO's timestamps and camera metadata, without BODY or images."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--svo', required=True, type=Path)
    parser.add_argument('--setup-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    a = parser.parse_args()
    if not a.svo.is_file() or a.svo.suffix.lower() not in ('.svo', '.svo2') or not a.setup_id.strip():
        parser.error('provide an existing SVO and a setup ID')
    if a.output.exists():
        raise FileExistsError('timeline output already exists')
    print(f'Hashing source SVO for timeline: {a.svo}', flush=True)
    source_hash = digest(a.svo)
    import pyzed.sl as sl
    init = sl.InitParameters()
    init.set_from_svo_file(str(a.svo.resolve()))
    init.svo_real_time_mode = False
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.IMAGE
    init.depth_mode = sl.DEPTH_MODE.NEURAL
    init.depth_minimum_distance, init.depth_maximum_distance = 0.25, 25.0
    camera = sl.Camera()
    status = camera.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f'could not open SVO: {status}')
    try:
        info = camera.get_camera_information()
        cfg = info.camera_configuration
        intr = cfg.calibration_parameters.left_cam
        width, height = int(cfg.resolution.width), int(cfg.resolution.height)
        camera_data = {'source_svo': str(a.svo.resolve()), 'source_svo_sha256': source_hash,
                       'sdk_version': str(sl.Camera.get_sdk_version()), 'setup_id': a.setup_id,
                       'serial_number': int(info.serial_number), 'width': width, 'height': height,
                       'depth_mode': 'NEURAL', 'coordinate_system': 'IMAGE', 'coordinate_units': 'meter',
                       'intrinsics_left': {key: float(getattr(intr, key)) for key in ('fx', 'fy', 'cx', 'cy')}}
        expected = int(camera.get_svo_number_of_frames())
        runtime = sl.RuntimeParameters()
        runtime.measure3D_reference_frame = sl.REFERENCE_FRAME.CAMERA
        frames = []
        last_stamp = None
        while True:
            status = camera.grab(runtime)
            if status == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                break
            if status != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f'SVO grab failed at frame {len(frames)}: {status}')
            index = len(frames)
            position = int(camera.get_svo_position())
            stamp = int(camera.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_nanoseconds())
            if position != index or stamp <= 0 or (last_stamp is not None and stamp <= last_stamp):
                raise ValueError(f'invalid SVO frame index or timestamp at {index}')
            frames.append({'frame_index': str(index), 'svo_frame_index': str(position), 'image_timestamp_ns': str(stamp)})
            last_stamp = stamp
        if len(frames) != expected or not frames:
            raise ValueError(f'incomplete SVO timeline: read {len(frames)} of {expected}')
    finally:
        camera.close()
    payload = {'kind': 'svo_sdk_timeline_no_body', 'camera': camera_data, 'frames': frames,
               'exporter_sha256': digest(Path(__file__)), 'status': 'complete'}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        stream.write('\n')
    print(f'Validated full SVO timeline: {len(frames)} frames; {a.output}', flush=True)


if __name__ == '__main__':
    main()
