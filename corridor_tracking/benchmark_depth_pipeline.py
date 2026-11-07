"""Compare whole-recording clip sizes before a new batch, without publishing benchmark images."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def compare_positions(baseline, candidate, tolerance_m=0.01):
    """Conservatively require identical observations and identities, with <= 1 cm XYZ distance."""
    for key in ('group', 'recording', 'source_svo_sha256', 'setup_id', 'calibration_sha256',
                'body_manifest_sha256', 'model_sha256'):
        if baseline['metadata'].get(key) != candidate['metadata'].get(key):
            return {'passed': False, 'reason': f'metadata differs: {key}'}
    a_frames, b_frames = baseline['frames'], candidate['frames']
    if not a_frames or len(a_frames) != len(b_frames):
        return {'passed': False, 'reason': 'frame counts differ or are empty'}
    compared, largest = 0, 0.0
    for a, b in zip(a_frames, b_frames):
        if any(a[k] != b[k] for k in ('frame_index', 'timestamp_ns', 'elapsed_s')):
            return {'passed': False, 'reason': 'frame indices or timestamps differ'}
        if len(a['observations']) != len(b['observations']):
            return {'passed': False, 'reason': f'observation count differs at frame {a["frame_index"]}'}
        for x, y in zip(a['observations'], b['observations']):
            if any(x.get(k) != y.get(k) for k in ('track_id', 'association_reason', 'depth_status')):
                return {'passed': False, 'reason': f'ID or detection status differs at frame {a["frame_index"]}'}
            p, q = x.get('surface_corridor_m'), y.get('surface_corridor_m')
            if p is None or q is None:
                if p != q:
                    return {'passed': False, 'reason': f'position availability differs at frame {a["frame_index"]}'}
                continue
            if len(p) != 3 or len(q) != 3 or not all(math.isfinite(float(v)) for v in p + q):
                return {'passed': False, 'reason': 'invalid coordinate'}
            distance = math.dist(p, q)
            largest = max(largest, distance)
            compared += 1
            if distance > tolerance_m:
                return {'passed': False, 'reason': f'coordinate differs by more than {tolerance_m} m at frame {a["frame_index"]}',
                        'max_difference_m': largest, 'positions_compared': compared}
    if compared < 10:
        return {'passed': False, 'reason': 'fewer than 10 comparable person positions', 'positions_compared': compared}
    return {'passed': True, 'positions_compared': compared, 'max_difference_m': largest, 'tolerance_m': tolerance_m}


def choose(baselines, candidate, comparisons, minimum_gain=0.05):
    if len(baselines) != 2 or any(not x.get('success') for x in baselines):
        return 69, 'baseline measurement failed; batch must not start'
    if not candidate.get('success'):
        return 69, 'candidate run failed; using baseline'
    if len(comparisons) != 2 or not all(x.get('passed') for x in comparisons):
        return 69, 'candidate output did not pass both baseline comparisons'
    # Require improvement against both individual baseline runs, avoiding a cold-start-only advantage.
    if any(candidate['seconds'] > x['seconds'] * (1 - minimum_gain) for x in baselines):
        return 69, 'candidate did not improve on both baselines by at least 5%'
    return 90, 'candidate passed both output comparisons and was at least 5% faster than both baselines'


def stage_totals(timing):
    stages = timing.get('stages_seconds', {})
    totals = {'initial_source_hash': stages.get('initial_source_hash', 0.),
              'clip_source_hashes': 0., 'sdk_init': 0., 'sdk_grab_and_images': 0.,
              'point_archive': 0., 'export_validation': 0., 'depth_alignment': 0.,
              'person_analysis': 0.}
    for clip in timing.get('clips', []):
        sdk, worker = clip.get('sdk_detail_seconds', {}), clip.get('worker_detail_seconds', {})
        totals['clip_source_hashes'] += sdk.get('source_hash', 0.) + worker.get('source_hash', 0.)
        totals['sdk_init'] += worker.get('sdk_init', 0.)
        totals['sdk_grab_and_images'] += worker.get('grab_and_save_images', 0.)
        totals['point_archive'] += worker.get('point_archive', 0.)
        totals['export_validation'] += sdk.get('validation', 0.)
        totals['depth_alignment'] += clip.get('alignment_seconds', 0.)
        totals['person_analysis'] += clip.get('person_analysis_seconds', 0.)
    return totals


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sdk-python', type=Path, required=True)
    p.add_argument('--local-root', type=Path, required=True)
    p.add_argument('--benchmark-id', required=True)
    p.add_argument('--group', type=int, choices=(2, 3), default=2)
    p.add_argument('--recording', default='recording_001')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+', a.benchmark_id) or not re.fullmatch(r'recording_\d{3}', a.recording):
        p.error('invalid benchmark ID or recording')
    root = a.local_root.resolve() / 'benchmarks' / a.benchmark_id
    if os.name == 'nt' and str(root).startswith('\\\\'):
        p.error('benchmark root must be on a local drive, not a shared path')
    root.mkdir(parents=True, exist_ok=False)
    bundle = a.bundle.resolve()
    report = {'status': 'running', 'group': a.group, 'recording': a.recording,
              'benchmark_id': a.benchmark_id, 'runs': [], 'selected_clip_frames': 69,
              'limits': ['Single recording; timings can vary by workload and computer.',
                         'No benchmark images or depth are copied to the shared coordinate folder.']}
    report_path = root / 'benchmark_report.json'
    def save():
        temp = root / 'benchmark_report.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        temp.replace(report_path)
    def run(name, clip):
        output = root / name
        print(f'[Benchmark] {name}: group {a.group} {a.recording}, clip size {clip} frames', flush=True)
        cmd = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
               '--sdk-python', str(a.sdk_python.resolve()), '--local-root', str(output),
               '--shared-root', str(output/'coordinate_copy'), '--group', str(a.group), '--recording', a.recording,
               '--run-id', 'benchmark', '--clip-frames', str(clip)]
        start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, cwd=bundle, check=False)
            code = proc.returncode
        except OSError as exc:
            print(f'[Benchmark] Could not launch: {exc}', flush=True)
            code = -1
        seconds = time.perf_counter() - start
        tag = f'g{a.group:03d}_{a.recording}_benchmark'
        timing_file = output/'analysis'/tag/'timing.json'
        positions = output/'coordinates'/tag/'positions.json'
        run_result = {'name': name, 'clip_frames': clip, 'seconds': seconds, 'exit_code': code,
                      'success': code == 0 and timing_file.is_file() and positions.is_file()}
        if timing_file.is_file():
            run_result['timing'] = json.loads(timing_file.read_text(encoding='utf-8'))
            run_result['success'] = run_result['success'] and run_result['timing'].get('status') == 'complete'
            run_result['stage_totals_seconds'] = stage_totals(run_result['timing'])
        report['runs'].append(run_result)
        save()
        print(f'[Benchmark] {name}: {seconds:.1f} seconds, success={run_result["success"]}', flush=True)
        if run_result['success']:
            print('[Benchmark] Stage seconds: ' + ', '.join(f'{k}={v:.1f}' for k, v in run_result['stage_totals_seconds'].items()), flush=True)
        return run_result, positions
    save()
    baseline1, p1 = run('baseline_first', 69)
    if not baseline1['success']:
        report.update(status='failed', reason='first baseline failed; batch not started')
        save(); return 1
    candidate, pc = run('candidate_90', 90)
    if not candidate['success']:
        report.update(status='complete', reason='candidate failed; using baseline 69', selected_clip_frames=69)
        save(); print('[Benchmark] Candidate failed; baseline 69 selected.', flush=True); return 0
    baseline2, p2 = run('baseline_second', 69)
    if not baseline2['success']:
        report.update(status='failed', reason='second baseline failed; batch not started')
        save(); return 1
    def read(path):
        return json.loads(path.read_text(encoding='utf-8-sig'))
    comparisons = [compare_positions(read(p1), read(pc)), compare_positions(read(p2), read(pc))]
    selected, reason = choose([baseline1, baseline2], candidate, comparisons)
    report.update(status='complete', comparisons=comparisons, selected_clip_frames=selected, reason=reason)
    save()
    print(f'[Benchmark] Selected {selected} frames: {reason}', flush=True)
    print(f'[Benchmark] Detailed timing report: {report_path}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
