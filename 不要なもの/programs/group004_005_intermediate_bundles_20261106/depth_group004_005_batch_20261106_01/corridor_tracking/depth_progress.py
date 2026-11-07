"""Live, explicitly approximate progress for local depth-analysis batches."""
from datetime import datetime, timedelta
import math
import threading
import time


def duration(seconds):
    seconds = max(0, int(math.ceil(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def estimate(elapsed, completed_clips, total_clips, pending_new, previous_average, sample_elapsed=None):
    """Return (current-recording seconds, whole-batch seconds), or None when unknown.

    Only completed clip timings or completed recording timings provide an estimate.
    The current clip is not assumed complete just because its estimate was exceeded.
    """
    recording_total = None
    if total_clips and 0 < completed_clips < total_clips and sample_elapsed is not None:
        recording_total = sample_elapsed * total_clips / completed_clips
    elif previous_average > 0 and completed_clips == 0:
        recording_total = previous_average
    if recording_total is None or recording_total <= elapsed:
        return None, None
    current = recording_total - elapsed
    if pending_new is None or pending_new < 1:
        return current, None
    per_future = previous_average if previous_average > 0 else recording_total
    return current, current + (pending_new - 1) * per_future


class DepthProgress:
    def __init__(self, group, recording, *, completed=0, total=None,
                 pending_new=None, previous_average=0., interval=15., clock=time.monotonic):
        self.group, self.recording = group, recording
        self.completed, self.total, self.pending_new = completed, total, pending_new
        self.previous_average, self.interval, self.clock = previous_average, interval, clock
        self.started = clock()
        self.clips_done, self.clips_total, self.sample_elapsed = 0, None, None
        self.stage = '入力・設定を確認中'
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, name='depth-progress', daemon=True)

    def start(self):
        self.emit()
        self.thread.start()

    def _heartbeat(self):
        while not self.stop_event.wait(self.interval):
            self.emit()

    def update(self, *, stage=None, clips_done=None, clips_total=None):
        with self.lock:
            if stage is not None:
                self.stage = stage
            if clips_done is not None:
                self.clips_done = clips_done
                self.sample_elapsed = max(0., self.clock() - self.started)
            if clips_total is not None:
                self.clips_total = clips_total
        self.emit()

    def line(self, now=None):
        with self.lock:
            stage, done, total, sample = self.stage, self.clips_done, self.clips_total, self.sample_elapsed
        elapsed = max(0., self.clock() - self.started)
        current, batch = estimate(elapsed, done, total, self.pending_new, self.previous_average, sample)
        head = f'[進捗] G{self.group:03d} {self.recording}'
        if self.total is not None:
            head += f' | 全体完了 {self.completed}/{self.total} 録画'
        if total:
            head += f' | この録画 {done}/{total} 区間'
        head += f' | {stage} | 経過 {duration(elapsed)}'
        if current is None:
            head += ' | この録画の残り: 算定中'
        else:
            head += f' | この録画の残り: 約 {duration(current)}'
        if batch is not None:
            moment = now or datetime.now().astimezone()
            finish = moment + timedelta(seconds=batch)
            head += f' | 全体の残り: 約 {duration(batch)} / 完了予想 {finish:%m/%d %H:%M}'
        elif self.pending_new is not None:
            head += ' | 全体の残り: 算定中'
        return head + '（目安）'

    def emit(self):
        print(self.line(), flush=True)

    def stop(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2)
