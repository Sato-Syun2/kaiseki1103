"""Discover recordings and prepare separate depth calibration candidates for groups 5–9.

SVOs and all depth/image outputs remain local. A candidate is not a validated
calibration and this tool does not assign experimental conditions or person IDs.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


GROUP_NAME = re.compile(r'(?:^|_)group0*([5-9])$', re.I)


def svo_files(folder):
    return sorted((p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.svo', '.svo2')),
                  key=lambda p: str(p).casefold())


def discover(root, groups):
    if not root.is_dir():
        raise FileNotFoundError(f'recordings directory not found: {root}')
    candidates = {g: [] for g in groups}
    for p in [root, *root.iterdir()]:
        if p.is_dir() and (match := GROUP_NAME.search(p.name)) and int(match[1]) in candidates:
            candidates[int(match[1])].append(p.resolve())
    result = []
    for group, dirs in candidates.items():
        entry = {'group': group, 'group_directories': [str(p) for p in dirs],
                 'calibration_recording': 'calibration_002' if group == 6 else 'calibration_001',
                 'status': 'ambiguous_group_directory' if len(dirs) > 1 else 'group_directory_missing'}
        if len(dirs) == 1:
            directory = dirs[0]
            files = svo_files(directory)
            calibration_dir = directory / entry['calibration_recording']
            cals = svo_files(calibration_dir) if calibration_dir.is_dir() else []
            entry.update(status='ready' if len(cals) == 1 else 'calibration_missing_or_ambiguous',
                         svo_count=len(files), calibration_svos=[str(p) for p in cals],
                         recording_svos=[str(p) for p in files if not any(x.name.lower().startswith('calibration') for x in p.relative_to(directory).parents)])
            if group == 5:
                entry['status'] = 'uses_group4_calibration_operator_report'
                entry['calibration_note'] = 'Operator says groups 4 and 5 use the same calibration; compare and verify existing group 4 candidate separately.'
            if group == 6:
                take1 = directory / 'calibration_001'
                entry['operator_reported_trial_1_svos'] = [str(p) for p in svo_files(take1)] if take1.is_dir() else []
        result.append(entry)
    return result


def discover_group7_additional(root):
    # The separately recorded tests may live outside the group directory.
    tests = []
    for folder in root.rglob('*'):
        if not folder.is_dir() or folder.name.casefold() not in ('1106test', '20261106_test'):
            continue
        for trial, name in ((4, 'test1'), (5, 'test2')):
            test_number = trial - 3
            def matches_name(value):
                match = re.fullmatch(r'test[_-]?0*([12])', value, re.I)
                return match is not None and int(match[1]) == test_number
            matches = [p for p in svo_files(folder) if matches_name(p.stem) or
                       any(matches_name(part) for part in p.relative_to(folder).parts[:-1])]
            tests.append({'additional_trial': trial, 'reported_label': name,
                          'test_parent': str(folder.resolve()),
                          'svo_candidates': [str(p.resolve()) for p in matches],
                          'status': 'one_name_based_candidate_unverified' if len(matches) == 1 else 'missing_or_ambiguous'})
    return {'missing_original_svo_reported': [2, 3], 'test_directories': tests,
            'status': 'reported_trial_labels_require_timestamp_and_content_review'}


def prepare(entry, local_root, sdk_python, analysis_python, package, run_id):
    if entry['status'] != 'ready':
        raise ValueError(f"G{entry['group']:03d}: {entry['status']}; no calibration was guessed")
    group = entry['group']
    tag = f'g{group:03d}_calibration_depth_{run_id}'
    work = local_root / 'calibration_preparation'
    output, fit = work / tag, work / (tag + '_floor_wall_candidate')
    if output.exists() or fit.exists():
        raise FileExistsError(f'{tag} already exists; use a new run id, preserving existing data')
    setup = f'group{group:03d}_calibration_{run_id}'
    source = entry['calibration_svos'][0]
    print(f'\n[校正 G{group:03d}] {source}', flush=True)
    subprocess.run([str(sdk_python), str(package/'zed_sdk_package/tracking_v2/export_depth_clip.py'),
                    '--svo', source, '--setup-id', setup, '--tag', tag, '--local-root', str(work),
                    '--local-only', '--first-frame', '0', '--frame-count', '30', '--pixel-stride', '6'], check=True)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    subprocess.run([str(analysis_python), str(package/'analyze_zed_corridor.py'), str(output/'depth'),
                    '--output-dir', str(fit), '--label', f'Group {group} calibration candidate'], check=True, env=environment)
    candidate = fit / 'zed_corridor_candidate.json'
    data = json.loads(candidate.read_text(encoding='utf-8-sig'))
    if data.get('setup_id') != setup or data.get('provisional') is not True:
        raise ValueError('unexpected calibration candidate; inspect local files')
    print(f'[校正 G{group:03d}] 暫定候補: {candidate}', flush=True)
    return {'group': group, 'source_svo': source, 'export': str(output), 'candidate': str(candidate),
            'setup_id': setup, 'status': 'provisional_review_required'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recordings-root', type=Path, required=True)
    p.add_argument('--groups', type=int, nargs='+', choices=range(5, 10), default=list(range(5, 10)))
    p.add_argument('--local-root', type=Path, required=True)
    p.add_argument('--sdk-python', type=Path)
    p.add_argument('--analysis-python', type=Path)
    p.add_argument('--run-id', default='20261107_01')
    p.add_argument('--prepare', action='store_true')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+', a.run_id) or len(set(a.groups)) != len(a.groups):
        p.error('invalid run id or duplicate groups')
    if a.prepare and (not a.sdk_python or not a.analysis_python or not a.sdk_python.is_file() or not a.analysis_python.is_file()):
        p.error('SDK and analysis Python executables are required for calibration preparation')
    entries = discover(a.recordings_root, a.groups)
    print(json.dumps({'kind': 'read_only_svo_inventory', 'groups': entries,
                      'group_7_additional_trials': discover_group7_additional(a.recordings_root) if 7 in a.groups else None,
                      'conditions': 'not assigned by this inventory'}, ensure_ascii=False, indent=2), flush=True)
    if not a.prepare:
        return 0
    package = Path(__file__).resolve().parents[1]
    records, failed, skipped = [], [], []
    for entry in entries:
        if entry['status'] == 'uses_group4_calibration_operator_report':
            skipped.append({'group': 5, 'reason': entry['status']})
            print('[校正 G005] 実験者申告によりグループ４と共通。新規校正候補は作成しません。', flush=True)
            continue
        try:
            records.append(prepare(entry, a.local_root, a.sdk_python, a.analysis_python, package, a.run_id))
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            failed.append({'group': entry['group'], 'error': str(exc)})
            print(f'[校正エラー] G{entry["group"]:03d}: {exc}; 保存済みファイルは維持。', file=sys.stderr, flush=True)
    print(json.dumps({'prepared': records, 'failed': failed, 'skipped': skipped,
                      'notice': '候補は暫定。共有や本解析への適用前に確認する。'}, ensure_ascii=False, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
