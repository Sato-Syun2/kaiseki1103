"""Benchmark lossless NPZ storage modes on one whole recording before a batch."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from corridor_tracking.benchmark_depth_pipeline import compare_positions, stage_totals


def choose_storage(baselines, candidate, comparisons, minimum_gain=0.05):
    if len(baselines) != 2 or any(not x.get('success') for x in baselines):
        return 'compressed', 'baseline measurement failed; batch must not start'
    if not candidate.get('success'):
        return 'compressed', 'stored candidate failed; retain compressed archives'
    if len(comparisons) != 2 or not all(x.get('passed') for x in comparisons):
        return 'compressed', 'stored candidate did not pass both position and identity comparisons'
    if any(candidate['seconds'] > x['seconds'] * (1 - minimum_gain) for x in baselines):
        return 'compressed', 'stored candidate was not at least 5% faster than both baselines'
    return 'stored', 'stored candidate passed both comparisons and was at least 5% faster than both baselines'


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
    root = a.local_root.resolve() / 'storage_benchmarks' / a.benchmark_id
    if os.name == 'nt' and str(root).startswith('\\\\'):
        p.error('benchmark root must be on a local drive')
    root.mkdir(parents=True, exist_ok=False)
    bundle = a.bundle.resolve()
    report = {'status': 'running', 'group': a.group, 'recording': a.recording,
              'benchmark_id': a.benchmark_id, 'runs': [], 'selected_point_archive_mode': 'compressed',
              'limits': ['One recording; different workloads and disk availability may change the result.',
                         'Benchmark data remain local.', 'Stored archives require more SSD space.']}
    report_path = root/'benchmark_report.json'
    def save():
        tmp = root/'benchmark_report.tmp'
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        tmp.replace(report_path)
    def run(name, mode):
        local = root/name
        print(f'[Storage benchmark] {name}: group {a.group} {a.recording}, mode={mode}', flush=True)
        cmd = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
               '--sdk-python', str(a.sdk_python.resolve()), '--local-root', str(local),
               '--shared-root', str(local/'coordinate_copy'), '--group', str(a.group), '--recording', a.recording,
               '--run-id', 'benchmark', '--clip-frames', '69', '--point-archive-mode', mode]
        start = time.perf_counter()
        try:
            code = subprocess.run(cmd, cwd=bundle, check=False).returncode
        except OSError as exc:
            print(f'[Storage benchmark] Could not launch: {exc}', flush=True); code = -1
        duration = time.perf_counter() - start
        tag = f'g{a.group:03d}_{a.recording}_benchmark'
        timing_path = local/'analysis'/tag/'timing.json'
        position_path = local/'coordinates'/tag/'positions.json'
        result = {'name': name, 'point_archive_mode': mode, 'seconds': duration, 'exit_code': code,
                  'success': code == 0 and timing_path.is_file() and position_path.is_file()}
        if timing_path.is_file():
            result['timing'] = json.loads(timing_path.read_text(encoding='utf-8'))
            result['success'] = result['success'] and result['timing'].get('status') == 'complete'
            result['stage_totals_seconds'] = stage_totals(result['timing'])
        result['archive_bytes'] = sum(path.stat().st_size for path in (local/'depth_clips').glob('*/depth/zed_depth_points.npz'))
        report['runs'].append(result); save()
        print(f'[Storage benchmark] {name}: {duration:.1f} s; archive bytes={result["archive_bytes"]}; success={result["success"]}', flush=True)
        return result, position_path
    save()
    b1, p1 = run('baseline_first', 'compressed')
    if not b1['success']:
        report.update(status='failed', reason='first baseline failed; batch not started'); save(); return 1
    c, pc = run('candidate_stored', 'stored')
    if not c['success']:
        report.update(status='complete', reason='candidate failed; retain compressed archives'); save(); return 0
    b2, p2 = run('baseline_second', 'compressed')
    if not b2['success']:
        report.update(status='failed', reason='second baseline failed; batch not started'); save(); return 1
    def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
    comparisons = [compare_positions(read(p1), read(pc)), compare_positions(read(p2), read(pc))]
    selected, reason = choose_storage([b1, b2], c, comparisons)
    report.update(status='complete', selected_point_archive_mode=selected, reason=reason, comparisons=comparisons)
    save()
    print(f'[Storage benchmark] Selected {selected}: {reason}', flush=True)
    print(f'[Storage benchmark] Report: {report_path}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
