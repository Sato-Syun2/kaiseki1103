import pytest
import json
import sys
from types import SimpleNamespace

from zed_sdk_package.tracking_v2 import export_body_local_batch as batch
from zed_sdk_package.tracking_v2.export_body_local_batch import discover


def test_discover_preserves_gaps_and_uses_explicit_extra_alias(tmp_path):
    for n in (1,3):
        folder=tmp_path/f'recording_{n:03d}';folder.mkdir();(folder/f'recording_{n:03d}.svo2').touch()
    (tmp_path/'recording_002').mkdir()
    cal=tmp_path/'calibration_001';cal.mkdir();(cal/'calibration_001.svo2').touch()
    extra=tmp_path/'test_001.svo2';extra.touch()
    jobs,missing=discover([('7',str(tmp_path),'setup')],[('7','recording_901',str(extra),'setup')])
    assert [j['recording'] for j in jobs]==['recording_001','recording_003','recording_901']
    assert missing==[str(tmp_path/'recording_002')]


def test_ambiguous_or_duplicate_recordings_are_rejected(tmp_path):
    folder=tmp_path/'recording_001';folder.mkdir();(folder/'a.svo').touch();(folder/'b.svo2').touch()
    with pytest.raises(ValueError,match='multiple SVO'):
        discover([('8',str(tmp_path),'setup')],[])
    (folder/'b.svo2').unlink()
    with pytest.raises(ValueError,match='duplicate'):
        discover([('8',str(tmp_path),'setup')],[('8','recording_001',str(folder/'a.svo'),'setup')])


def test_restart_reuses_validated_and_preserves_failed_attempt(tmp_path, monkeypatch):
    root=tmp_path/'sources';root.mkdir();out=tmp_path/'output'
    for n in (1,3):
        folder=root/f'recording_{n:03d}';folder.mkdir();(folder/f'recording_{n:03d}.svo2').touch()
    known=tmp_path/'known.json';known.write_text(json.dumps({'records':[]}))
    monkeypatch.setattr(sys,'argv',['batch','--source','8',str(root),'setup','--local-root',str(out),'--known-sources',str(known)])
    monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    failures={'remaining':1}
    def fake_run(command,log,progress):
        if '--output' in command:
            if 'recording_003' in progress and failures['remaining']:
                failures['remaining']-=1
                return 1
            body=Path(command[command.index('--output')+1]);body.mkdir()
            (body/'camera.json').write_text(json.dumps({'source_svo_sha256':'a'*64}))
            (body/'manifest.json').write_text('{}')
        return 0
    from pathlib import Path
    monkeypatch.setattr(batch,'command_logged',fake_run)
    assert batch.main()==1
    assert len(list((out/'g008'/'recording_001').glob('attempt_*/complete.json')))==1
    assert len(list((out/'g008'/'recording_003').glob('attempt_*')))==1
    assert batch.main()==0
    assert len(list((out/'g008'/'recording_001').glob('attempt_*')))==1
    assert len(list((out/'g008'/'recording_003').glob('attempt_*')))==2
    assert len(list((out/'g008'/'recording_003').glob('attempt_*/complete.json')))==1
