import csv
import json
import re
import sys

import pytest

from corridor_tracking import depth_batch_process
from corridor_tracking.depth_corridor_replay import make_page
from depth_person_prototype import digest


def test_replay_keeps_frame_and_escapes_embedded_data():
    frame = {'frame_index': 6, 'elapsed_s': 0.2, 'review_image': '<frame>.jpg', 'observations': []}
    data = {'frames': [frame], 'walls': {'visible': 2.1, 'opposite': -0.3}, 'csv': 'data.csv', 'tracking': 'data.json'}
    page = make_page(data, '録画 <001>')
    embedded = re.search(r'<script type="application/json" id="data">(.*?)</script>', page).group(1)
    assert json.loads(embedded) == data
    assert '<frame>' not in embedded
    assert '録画 &lt;001&gt;' in page
    assert 'surface_corridor_m' in page
    assert 'frame_index+1' in page


def test_batch_checks_all_clips_before_running_and_joins_complete_recording(tmp_path, monkeypatch):
    body = tmp_path/'body'; body.mkdir(); (body/'manifest.json').write_text('{}')
    cal = tmp_path/'cal.json'; cal.write_text('{}')
    sha = 'a' * 64
    row = {'group': '2', 'recording': 'recording_001', 'existing_depth': 'no', 'body_dir': str(body),
           'body_manifest_sha256': digest(body/'manifest.json'), 'calibration': str(cal),
           'calibration_sha256': digest(cal), 'frame_count': '140', 'source_svo_sha256': sha, 'setup_id': 'setup'}
    inventory = tmp_path/'inventory.csv'
    with inventory.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row); writer.writeheader(); writer.writerow(row)
    exchange = tmp_path/'exchange'; exchange.mkdir()
    for start, length in [(0, 69), (69, 69), (138, 2)]:
        folder = exchange/f'g002_recording_001_depth_{start:06d}_{start+length-1:06d}_20261105_01'
        folder.mkdir()
        (folder/'batch_summary.json').write_text(json.dumps({'status': 'validated', 'source_svo_sha256': sha,
            'setup_id': 'setup', 'first_frame': start, 'frame_count': length}))
    calls = []
    monkeypatch.setattr(depth_batch_process.subprocess, 'run', lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(sys, 'argv', ['depth_batch_process', '--inventory', str(inventory), '--group', '2',
        '--recording', 'recording_001', '--exchange-root', str(exchange), '--output-root', str(tmp_path/'out'),
        '--depth-python', sys.executable, '--model', str(tmp_path/'model')])
    depth_batch_process.main()
    assert len(calls) == 9
    merged = next(c for c in calls if 'corridor_tracking.merge_depth_person_runs' in c)
    assert merged.count('--part') == 3
    assert '--require-full-svo' in merged
    assert merged[merged.index('--frame-count')+1] == '140'

    # A missing final clip must be rejected before any expensive subprocess starts.
    (exchange/'g002_recording_001_depth_000138_000139_20261105_01'/'batch_summary.json').unlink()
    calls.clear()
    with pytest.raises(FileNotFoundError):
        depth_batch_process.main()
    assert not calls
