import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SDK = Path(__file__).resolve().parents[1]/'zed_sdk_package'/'tracking_v2'


def load_runner(monkeypatch):
    monkeypatch.syspath_prepend(str(SDK))
    return importlib.import_module('export_depth_clip')


def arguments(tmp_path, svo):
    return ['export_depth_clip.py','--svo',str(svo),'--setup-id','test-setup', '--tag','run1',
            '--local-root',str(tmp_path/'local'), '--shared-dir',str(tmp_path/'shared'),
            '--first-frame','3','--frame-count','3']


def test_wrong_svo_hash_fails_before_any_export(tmp_path, monkeypatch):
    runner=load_runner(monkeypatch); svo=tmp_path/'x.svo2';svo.write_bytes(b'example')
    monkeypatch.setattr(sys,'argv',arguments(tmp_path,svo)+['--expected-svo-sha256','0'*64])
    with pytest.raises(ValueError,match='differs'):
        runner.main()
    assert not (tmp_path/'local').exists() and not (tmp_path/'shared').exists()


def test_failed_export_preserves_log_without_shared_publish(tmp_path, monkeypatch):
    runner=load_runner(monkeypatch);svo=tmp_path/'x.svo2';svo.write_bytes(b'example')
    monkeypatch.setattr(sys,'argv',arguments(tmp_path,svo))
    calls=[]
    def failed(cmd,**kwargs):
        calls.append(cmd);return SimpleNamespace(returncode=7)
    monkeypatch.setattr(runner.subprocess,'run',failed)
    assert runner.main()==1
    local=tmp_path/'local'/'run1'; summary=json.loads((local/'batch_summary.json').read_text())
    assert summary['status']=='export_failed' and summary['export_exit_code']==7
    assert calls[0][-3:]==['3','4','5'] and '--match-body-depth-settings' in calls[0]
    assert (local/'export.log').is_file() and not (tmp_path/'shared').exists()


def test_validated_run_is_mirrored_after_validation(tmp_path,monkeypatch):
    runner=load_runner(monkeypatch);svo=tmp_path/'x.svo2';svo.write_bytes(b'example')
    monkeypatch.setattr(sys,'argv',arguments(tmp_path,svo));calls=[]
    def success(cmd,**kwargs):
        calls.append(cmd)
        if len(calls)==1:
            out=Path(cmd[cmd.index('--output')+1]);out.mkdir()
            (out/'camera.json').write_text(json.dumps({'source_svo_sha256':runner.sha256_file(svo),'requested_frame_indices':[3,4,5], 'point_archive_mode':'compressed'}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess,'run',success)
    assert runner.main()==0
    assert len(calls)==2
    summary=json.loads((tmp_path/'shared'/'batch_summary.json').read_text())
    assert summary['status']=='validated' and summary['frame_count']==3
    assert (tmp_path/'local'/'run1'/'depth'/'camera.json').read_bytes()==(tmp_path/'shared'/'depth'/'camera.json').read_bytes()


def test_validated_local_only_run_never_publishes_depth(tmp_path, monkeypatch):
    runner=load_runner(monkeypatch); svo=tmp_path/'x.svo2'; svo.write_bytes(b'example')
    args=arguments(tmp_path,svo); i=args.index('--shared-dir'); args[i:i+2]=['--local-only']
    monkeypatch.setattr(sys,'argv',args); calls=[]
    def success(cmd,**kwargs):
        calls.append(cmd)
        if len(calls)==1:
            out=Path(cmd[cmd.index('--output')+1]); out.mkdir()
            (out/'camera.json').write_text(json.dumps({'source_svo_sha256':runner.sha256_file(svo),'requested_frame_indices':[3,4,5], 'point_archive_mode':'compressed'}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess,'run',success)
    monkeypatch.setattr(runner,'copy_batch',lambda *a: pytest.fail('local-only must not copy'))
    assert runner.main()==0
    assert json.loads((tmp_path/'local'/'run1'/'batch_summary.json').read_text())['status']=='validated'
    assert not (tmp_path/'shared').exists()
