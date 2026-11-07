import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from corridor_tracking.prepare_group004_005_bundle import validate_timeline


def load_exporter():
    path = Path(__file__).resolve().parents[1]/'zed_sdk_package/tracking_v2/export_svo_timeline.py'
    spec = importlib.util.spec_from_file_location('test_svo_timeline_exporter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_fake_sdk(monkeypatch, timestamps):
    sl = ModuleType('pyzed.sl')
    sl.ERROR_CODE = SimpleNamespace(SUCCESS=0, END_OF_SVOFILE_REACHED=1)
    sl.UNIT = SimpleNamespace(METER=0)
    sl.COORDINATE_SYSTEM = SimpleNamespace(IMAGE=0)
    sl.DEPTH_MODE = SimpleNamespace(NEURAL=0)
    sl.REFERENCE_FRAME = SimpleNamespace(CAMERA=0)
    sl.TIME_REFERENCE = SimpleNamespace(IMAGE=0)
    class Init:
        def set_from_svo_file(self, svo): self.svo = svo
    sl.InitParameters = Init
    sl.RuntimeParameters = type('RuntimeParameters', (), {})
    class Camera:
        def __init__(self): self.i = -1
        def open(self, init): return 0
        def close(self): self.closed = True
        def get_camera_information(self):
            intr = SimpleNamespace(fx=1000, fy=1000, cx=500, cy=300)
            cfg = SimpleNamespace(resolution=SimpleNamespace(width=1920, height=1080),
                                  calibration_parameters=SimpleNamespace(left_cam=intr))
            return SimpleNamespace(camera_configuration=cfg, serial_number=123)
        def get_svo_number_of_frames(self): return len(timestamps)
        def grab(self, runtime):
            self.i += 1
            return 0 if self.i < len(timestamps) else 1
        def get_svo_position(self): return self.i
        def get_timestamp(self, ref): return SimpleNamespace(get_nanoseconds=lambda: timestamps[self.i])
        @staticmethod
        def get_sdk_version(): return 'fake'
    sl.Camera = Camera
    pkg = ModuleType('pyzed'); pkg.sl = sl
    monkeypatch.setitem(sys.modules, 'pyzed', pkg)
    monkeypatch.setitem(sys.modules, 'pyzed.sl', sl)


def test_sdk_timeline_contains_no_body_or_images_and_checks_frames(tmp_path, monkeypatch):
    mod = load_exporter()
    install_fake_sdk(monkeypatch, [100, 200, 300])
    svo = tmp_path/'test.svo2'; svo.write_bytes(b'source')
    output = tmp_path/'timeline.json'
    monkeypatch.setattr(sys, 'argv', ['export', '--svo', str(svo), '--setup-id', 'setup', '--output', str(output)])
    mod.main()
    data = json.loads(output.read_text())
    assert data['kind'] == 'svo_sdk_timeline_no_body' and len(data['frames']) == 3
    assert set(data['frames'][0]) == {'frame_index', 'svo_frame_index', 'image_timestamp_ns'}
    validate_timeline(data, svo, 'setup')
    with pytest.raises(FileExistsError):
        mod.main()


def test_sdk_timeline_rejects_bad_timestamps_without_output(tmp_path, monkeypatch):
    mod = load_exporter()
    install_fake_sdk(monkeypatch, [100, 100])
    svo = tmp_path/'test.svo2'; svo.write_bytes(b'source')
    output = tmp_path/'timeline.json'
    monkeypatch.setattr(sys, 'argv', ['export', '--svo', str(svo), '--setup-id', 'setup', '--output', str(output)])
    with pytest.raises(ValueError, match='timestamp'):
        mod.main()
    assert not output.exists()
