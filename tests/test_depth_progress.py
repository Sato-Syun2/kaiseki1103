from datetime import datetime

from corridor_tracking.depth_progress import DepthProgress, duration, estimate


def test_estimate_counts_down_from_completed_clip_and_handles_overrun():
    assert estimate(10, 0, 4, 3, 0) == (None, None)
    assert estimate(90, 1, 4, 3, 100, 60) == (150, 350)
    assert estimate(100, 1, 4, 3, 100, 60) == (140, 340)
    assert estimate(250, 1, 4, 3, 100, 60) == (None, None)
    assert estimate(30, 0, 4, 2, 90) == (60, 150)
    assert duration(3661) == '01:01:01'


def test_progress_reports_actual_completed_work_and_estimated_finish():
    clock = [0.]
    p = DepthProgress(2, 'recording_003', completed=2, total=109, pending_new=3, clock=lambda:clock[0])
    p.update(clips_total=4, stage='深度を解析中')
    assert '算定中' in p.line()
    clock[0] = 60
    p.update(clips_done=1)
    clock[0] = 90
    line = p.line(now=datetime(2026, 11, 5, 12, 0))
    assert '全体完了 2/109 録画' in line and 'この録画 1/4 区間' in line
    assert 'この録画の残り: 約 00:02:30' in line
    assert '全体の残り: 約 00:10:30' in line
    assert '完了予想 11/05 12:10' in line
    line.encode('cp932')


def test_progress_continues_during_a_silent_operation(capsys):
    p = DepthProgress(3, 'recording_001', interval=.02)
    p.start()
    try:
        p.stop_event.wait(.15)
    finally:
        p.stop()
    lines = [s for s in capsys.readouterr().out.splitlines() if '[進捗]' in s]
    assert len(lines) >= 2
