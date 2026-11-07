import copy
import json
import sys
from types import SimpleNamespace

from corridor_tracking import benchmark_depth_pipeline as benchmark


def positions():
    metadata = {k: 'same' for k in ('group', 'recording', 'source_svo_sha256', 'setup_id', 'calibration_sha256', 'body_manifest_sha256', 'model_sha256')}
    observation = {'track_id': 1, 'association_reason': 'matched', 'depth_status': 'surface_candidate', 'surface_corridor_m': [1., 2., 3.]}
    return {'metadata': metadata, 'frames': [{'frame_index': i, 'timestamp_ns': str(i), 'elapsed_s': i / 30, 'observations': [copy.deepcopy(observation)]} for i in range(12)]}


def test_comparison_checks_identity_time_and_metric_position():
    reference = positions()
    candidate = copy.deepcopy(reference)
    candidate['frames'][1]['observations'][0]['surface_corridor_m'][0] += .005
    assert benchmark.compare_positions(reference, candidate)['passed']
    candidate['frames'][1]['observations'][0]['surface_corridor_m'][0] += .02
    assert not benchmark.compare_positions(reference, candidate)['passed']
    candidate = copy.deepcopy(reference)
    candidate['frames'][3]['observations'][0]['track_id'] = 2
    assert not benchmark.compare_positions(reference, candidate)['passed']
    candidate = copy.deepcopy(reference)
    candidate['frames'][3]['timestamp_ns'] = 'different'
    assert not benchmark.compare_positions(reference, candidate)['passed']
    candidate = copy.deepcopy(reference)
    candidate['frames'] = candidate['frames'][:2]
    assert not benchmark.compare_positions(candidate, candidate)['passed']


def test_selection_requires_speed_and_two_valid_comparisons():
    b = [{'success': True, 'seconds': 100}, {'success': True, 'seconds': 90}]
    c = {'success': True, 'seconds': 80}
    passed = [{'passed': True}, {'passed': True}]
    assert benchmark.choose(b, c, passed)[0] == 90
    assert benchmark.choose(b, {'success': True, 'seconds': 86}, passed)[0] == 69
    assert benchmark.choose(b, c, [passed[0], {'passed': False}])[0] == 69
    assert benchmark.choose(b, {'success': False}, [])[0] == 69
    assert benchmark.choose([b[0]], c, passed)[0] == 69


def test_full_benchmark_selects_only_after_three_isolated_successful_runs(tmp_path, monkeypatch):
    bundle = tmp_path/'bundle'; bundle.mkdir()
    sdk = tmp_path/'python'; sdk.touch()
    local = tmp_path/'ssd'; local.mkdir()
    monotonic = iter([0., 100., 101., 181., 182., 277.])
    monkeypatch.setattr(benchmark.time, 'perf_counter', lambda: next(monotonic))
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        root = __import__('pathlib').Path(command[command.index('--local-root')+1])
        tag = 'g002_recording_001_benchmark'
        work = root/'analysis'/tag; work.mkdir(parents=True)
        (work/'timing.json').write_text(json.dumps({'status': 'complete'}))
        dest = root/'coordinates'/tag; dest.mkdir(parents=True)
        (dest/'positions.json').write_text(json.dumps(positions()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(benchmark.subprocess, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['benchmark', '--bundle', str(bundle), '--sdk-python', str(sdk), '--local-root', str(local), '--benchmark-id', 'test'])
    assert benchmark.main() == 0
    report = json.loads((local/'benchmarks'/'test'/'benchmark_report.json').read_text())
    assert report['status'] == 'complete' and report['selected_clip_frames'] == 90
    assert [cmd[cmd.index('--clip-frames')+1] for cmd in commands] == ['69', '90', '69']
    assert all('benchmarks/test/' in cmd[cmd.index('--shared-root')+1] for cmd in commands)
    assert not (local/'coordinates').exists()


def test_failed_baseline_never_starts_batch(tmp_path, monkeypatch):
    bundle = tmp_path/'bundle'; bundle.mkdir()
    sdk = tmp_path/'python'; sdk.touch()
    monkeypatch.setattr(benchmark.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(sys, 'argv', ['benchmark', '--bundle', str(bundle), '--sdk-python', str(sdk), '--local-root', str(tmp_path), '--benchmark-id', 'bad'])
    assert benchmark.main() == 1
    report = json.loads((tmp_path/'benchmarks'/'bad'/'benchmark_report.json').read_text())
    assert report['status'] == 'failed' and report['selected_clip_frames'] == 69


def test_failed_candidate_preserves_default_and_does_not_reuse_baseline_output(tmp_path, monkeypatch):
    bundle = tmp_path/'bundle'; bundle.mkdir()
    sdk = tmp_path/'python'; sdk.touch()
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 2:
            return SimpleNamespace(returncode=1)
        root = __import__('pathlib').Path(command[command.index('--local-root')+1])
        tag = 'g002_recording_001_benchmark'
        work = root/'analysis'/tag; work.mkdir(parents=True)
        (work/'timing.json').write_text(json.dumps({'status': 'complete'}))
        dest = root/'coordinates'/tag; dest.mkdir(parents=True)
        (dest/'positions.json').write_text(json.dumps(positions()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(benchmark.subprocess, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['benchmark', '--bundle', str(bundle), '--sdk-python', str(sdk), '--local-root', str(tmp_path), '--benchmark-id', 'fallback'])
    assert benchmark.main() == 0
    report = json.loads((tmp_path/'benchmarks'/'fallback'/'benchmark_report.json').read_text())
    assert report['status'] == 'complete' and report['selected_clip_frames'] == 69
    assert len(calls) == 2 and len(report['runs']) == 2
