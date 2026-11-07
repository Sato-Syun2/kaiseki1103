import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import zipfile
from depth_person_prototype import load_depth_export


@pytest.mark.parametrize('mode, compression', [('compressed', zipfile.ZIP_DEFLATED), ('stored', zipfile.ZIP_STORED)])
def test_worker_records_timing_without_changing_frame_contract(tmp_path, monkeypatch, mode, compression):
    source = Path(__file__).resolve().parents[1]/'zed_sdk_package/tracking_v2/export_zed_depth.py'
    spec = importlib.util.spec_from_file_location('depth_worker_under_test', source)
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    class Init:
        def set_from_svo_file(self, path): pass
    class Mat:
        def get_data(self): return self.data
    class Camera:
        def __init__(self): self.index = -1
        def open(self, init): return 0
        def get_camera_information(self):
            cfg = SimpleNamespace(resolution=SimpleNamespace(width=2, height=2), calibration_parameters=SimpleNamespace(left_cam=SimpleNamespace(fx=1, fy=1, cx=0, cy=0)), fps=30)
            return SimpleNamespace(camera_configuration=cfg, camera_model='mock', serial_number=123)
        def get_svo_number_of_frames(self): return 2
        def grab(self, runtime):
            self.index += 1
            return 0 if self.index < 2 else 1
        def get_svo_position(self): return self.index
        def get_timestamp(self, _): return SimpleNamespace(get_nanoseconds=lambda: 1000 + self.index * 100)
        def retrieve_measure(self, mat, *_): mat.data = np.ones((2,2), np.float32); return 0
        def retrieve_image(self, mat, *_): mat.data = np.zeros((2,2,4), np.uint8); return 0
        def close(self): pass
        @staticmethod
        def get_sdk_version(): return 'mock'
    sl = ModuleType('pyzed.sl')
    sl.InitParameters, sl.Camera, sl.Mat = Init, Camera, Mat
    sl.RuntimeParameters = lambda: SimpleNamespace(confidence_threshold=50)
    sl.ERROR_CODE = SimpleNamespace(SUCCESS=0, END_OF_SVOFILE_REACHED=1)
    sl.UNIT = SimpleNamespace(METER='m'); sl.COORDINATE_SYSTEM = SimpleNamespace(IMAGE='image')
    sl.DEPTH_MODE = SimpleNamespace(NEURAL='neural')
    sl.TIME_REFERENCE = SimpleNamespace(IMAGE='image'); sl.MEASURE = SimpleNamespace(DEPTH='depth')
    sl.MEM = SimpleNamespace(CPU='cpu'); sl.VIEW = SimpleNamespace(LEFT='left')
    sl.REFERENCE_FRAME = SimpleNamespace(CAMERA='camera')
    monkeypatch.setitem(sys.modules, 'pyzed', ModuleType('pyzed'))
    monkeypatch.setitem(sys.modules, 'pyzed.sl', sl)
    svo = tmp_path/'test.svo2'; svo.write_bytes(b'mock source')
    output = tmp_path/'out'
    monkeypatch.setattr(sys, 'argv', ['export_zed_depth.py', str(svo), '--output', str(output), '--setup-id', 'test', '--depth-mode', 'NEURAL', '--match-body-depth-settings', '--pixel-stride', '1', '--point-archive-mode', mode, '--frame-indices', '0', '1'])
    assert worker.main() == 0
    camera = json.loads((output/'camera.json').read_text())
    manifest = json.loads((output/'manifest.json').read_text())
    assert manifest['status'] == 'complete' and manifest['sample_count'] == 2
    assert camera['total_svo_frames_read'] == 2 and camera['requested_frame_indices'] == [0, 1]
    assert camera['point_archive_mode'] == mode
    with zipfile.ZipFile(output/'zed_depth_points.npz') as archive:
        assert all(item.compress_type == compression for item in archive.infolist())
    _, _, frames, points, ids, _ = load_depth_export(output)
    assert [int(frame['frame_index']) for frame in frames] == [0, 1]
    assert points.shape == (8, 3) and ids.tolist() == [0]*4 + [1]*4
    assert set(camera['processing_timing_seconds']) == {'source_hash', 'sdk_init', 'grab_and_save_images', 'point_archive'}
    assert all(value >= 0 for value in camera['processing_timing_seconds'].values())
