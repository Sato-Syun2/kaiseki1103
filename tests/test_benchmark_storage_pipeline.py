import json
from pathlib import Path
import sys
from types import SimpleNamespace

from corridor_tracking import benchmark_storage_pipeline as benchmark


def positions():
    metadata = {k: 'same' for k in ('group', 'recording', 'source_svo_sha256', 'setup_id', 'calibration_sha256', 'body_manifest_sha256', 'model_sha256')}
    observation = {'track_id': 1, 'association_reason': 'matched', 'depth_status': 'surface_candidate', 'surface_corridor_m': [1., 2., 3.]}
    return {'metadata': metadata, 'frames': [{'frame_index': i, 'timestamp_ns': str(i), 'elapsed_s': i / 30, 'observations': [observation]} for i in range(12)]}


def test_storage_selection_requires_two_quality_and_speed_checks():
    baselines = [{'success': True, 'seconds': 100}, {'success': True, 'seconds': 95}]
    candidate = {'success': True, 'seconds': 85}
    valid = [{'passed': True}, {'passed': True}]
    assert benchmark.choose_storage(baselines, candidate, valid)[0] == 'stored'
    assert benchmark.choose_storage(baselines, {'success': True, 'seconds': 91}, valid)[0] == 'compressed'
    assert benchmark.choose_storage(baselines, candidate, [{'passed': False}, valid[1]])[0] == 'compressed'
    assert benchmark.choose_storage(baselines, {'success': False}, [])[0] == 'compressed'


def test_benchmark_uses_same_clip_size_and_isolated_storage_modes(tmp_path, monkeypatch):
    bundle = tmp_path/'bundle'; bundle.mkdir()
    sdk = tmp_path/'python'; sdk.touch()
    local = tmp_path/'ssd'; local.mkdir()
    clock = iter([0., 100., 101., 181., 182., 277.])
    monkeypatch.setattr(benchmark.time, 'perf_counter', lambda: next(clock))
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        root = Path(command[command.index('--local-root')+1])
        tag = 'g002_recording_001_benchmark'
        work = root/'analysis'/tag; work.mkdir(parents=True)
        (work/'timing.json').write_text(json.dumps({'status': 'complete'}))
        dest = root/'coordinates'/tag; dest.mkdir(parents=True)
        (dest/'positions.json').write_text(json.dumps(positions()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(benchmark.subprocess, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['benchmark', '--bundle', str(bundle), '--sdk-python', str(sdk), '--local-root', str(local), '--benchmark-id', 'test'])
    assert benchmark.main() == 0
    report = json.loads((local/'storage_benchmarks'/'test'/'benchmark_report.json').read_text())
    assert report['status'] == 'complete' and report['selected_point_archive_mode'] == 'stored'
    assert [c[c.index('--point-archive-mode')+1] for c in commands] == ['compressed', 'stored', 'compressed']
    assert all(c[c.index('--clip-frames')+1] == '69' for c in commands)
    assert all('storage_benchmarks/test/' in c[c.index('--shared-root')+1] for c in commands)
    assert not (local/'coordinates').exists()
