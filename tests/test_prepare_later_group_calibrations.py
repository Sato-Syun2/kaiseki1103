from pathlib import Path
from unittest.mock import patch
import json

import pytest

from corridor_tracking.prepare_later_group_calibrations import discover, discover_group7_additional, prepare


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'svo')


def test_group6_uses_take2_and_keeps_take1_as_trial(tmp_path):
    root = tmp_path / '20261105_group006'
    touch(root / 'calibration_001' / 'a.svo2')
    touch(root / 'calibration_002' / 'b.svo2')
    touch(root / 'recording_001' / 'c.svo2')
    result = discover(tmp_path, [6])[0]
    assert result['status'] == 'ready'
    assert result['calibration_svos'] == [str((root / 'calibration_002' / 'b.svo2').resolve())]
    assert result['operator_reported_trial_1_svos'] == [str((root / 'calibration_001' / 'a.svo2').resolve())]
    assert len(result['recording_svos']) == 1


def test_ambiguous_folders_or_calibration_do_not_choose_one(tmp_path):
    touch(tmp_path / 'date_group005' / 'calibration_001' / 'a.svo2')
    touch(tmp_path / 'another_group005' / 'calibration_001' / 'b.svo2')
    entry = discover(tmp_path, [5])[0]
    assert entry['status'] == 'ambiguous_group_directory'
    with patch('subprocess.run') as run:
        with pytest.raises(ValueError):
            prepare(entry, tmp_path, Path('sdk'), Path('analysis'), tmp_path, 'run')
        run.assert_not_called()


def test_existing_calibration_is_never_overwritten(tmp_path):
    touch(tmp_path / 'date_group007' / 'calibration_001' / 'a.svo2')
    entry = discover(tmp_path, [7])[0]
    (tmp_path / 'calibration_preparation' / 'g007_calibration_depth_run').mkdir(parents=True)
    with patch('subprocess.run') as run:
        with pytest.raises(FileExistsError):
            prepare(entry, tmp_path, Path('sdk'), Path('analysis'), tmp_path, 'run')
        run.assert_not_called()


def test_additional_trials_keep_source_labels(tmp_path):
    touch(tmp_path / '1106test' / 'test1' / 'recording.svo2')
    touch(tmp_path / '1106test' / 'test2.svo2')
    result = discover_group7_additional(tmp_path)
    assert result['missing_original_svo_reported'] == [2, 3]
    assert [(e['additional_trial'], e['status']) for e in result['test_directories']] == [
        (4, 'one_name_based_candidate_unverified'), (5, 'one_name_based_candidate_unverified')]


def test_dated_test_folder_finds_underscored_labels_without_verifying_identity(tmp_path):
    touch(tmp_path / '20261106_test' / 'test_001' / 'test_001.svo2')
    touch(tmp_path / '20261106_test' / 'test_002' / 'test_002.svo2')
    result = discover_group7_additional(tmp_path)
    assert [(e['additional_trial'], e['status']) for e in result['test_directories']] == [
        (4, 'one_name_based_candidate_unverified'), (5, 'one_name_based_candidate_unverified')]
    assert 'test_001' in result['test_directories'][0]['svo_candidates'][0]


def test_prepare_uses_group6_take2_and_local_output(tmp_path):
    root = tmp_path / 'date_group006'
    touch(root / 'calibration_001' / 'trial1.svo2')
    touch(root / 'calibration_002' / 'cal.svo2')
    entry = discover(tmp_path, [6])[0]
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 2:
            fit = Path(command[command.index('--output-dir') + 1])
            fit.mkdir(parents=True)
            (fit / 'zed_corridor_candidate.json').write_text(json.dumps(
                {'setup_id': 'group006_calibration_run', 'provisional': True}), encoding='utf-8')

    with patch('subprocess.run', side_effect=fake_run):
        result = prepare(entry, tmp_path, Path('sdk'), Path('analysis'), tmp_path, 'run')
    assert calls[0][calls[0].index('--svo') + 1] == entry['calibration_svos'][0]
    assert '--local-only' in calls[0]
    assert result['status'] == 'provisional_review_required'
