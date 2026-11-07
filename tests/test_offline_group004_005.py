import json
import csv
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
from corridor_tracking import offline_group004_005 as offline
from zed_sdk_package.tracking_v2.exchange_copy import copy_batch


def setup_one(tmp_path):
    root, stage, remote = [tmp_path/x for x in ('ssd','queue','remote')]
    root.mkdir(); remote.mkdir()
    tag='g004_recording_032_compact_20261106_01_retry01'
    row={'group':'4','recording':'recording_032','source_svo_sha256':'source','frame_count':'2'}
    coord=root/'coordinates'/tag;coord.mkdir(parents=True)
    (coord/'positions.json').write_text('{"frames":[]}')
    pos=offline.sha(coord/'positions.json')
    manifest={'status':'complete','positions_sha256':pos,'source_svo_sha256':'source',
              'group':4,'recording':'recording_032','frame_count':2}
    (coord/'manifest.json').write_text(json.dumps(manifest))
    work=root/'analysis'/tag; replay=work/'merged'/'portable_replay.html';replay.parent.mkdir(parents=True)
    replay.write_text('replay')
    (work/'storage_retention.json').write_text(json.dumps({'status':'complete','positions_sha256':pos,
                                                            'replay_sha256':offline.sha(replay)}))
    rows={('4','recording_032'):row}
    return root,stage,remote,tag,rows,pos


def test_connection_loss_continues_and_reconnection_syncs_without_replacing(tmp_path):
    root,stage,remote,tag,rows,pos=setup_one(tmp_path)
    offline.bootstrap(root,stage,rows,{tag:pos},copy_batch)
    shutil.rmtree(remote)
    count,pending=offline.sync_once(root,stage,remote,rows,copy_batch)
    assert count==0 and len(pending)==1
    assert (root/'coordinates'/tag/'positions.json').exists()
    remote.mkdir()
    count,pending=offline.sync_once(root,stage,remote,rows,copy_batch)
    assert count==1 and not pending and offline.sha(remote/tag/'positions.json')==pos
    count,pending=offline.sync_once(root,stage,remote,rows,copy_batch)
    assert count==1 and not pending


def test_conflicting_remote_run_never_overwritten(tmp_path):
    root,stage,remote,tag,rows,pos=setup_one(tmp_path)
    offline.bootstrap(root,stage,rows,{tag:pos},copy_batch)
    conflict=remote/'g004_recording_032_compact_20261106_01'; conflict.mkdir()
    (conflict/'sentinel').write_text('keep')
    _,pending=offline.sync_once(root,stage,remote,rows,copy_batch)
    assert len(pending)==1 and 'other run' in pending[0][1]
    assert (conflict/'sentinel').read_text()=='keep' and not (remote/tag).exists()


def test_snapshot_requires_previously_shared_result_on_ssd(tmp_path):
    root,stage,remote,tag,rows,pos=setup_one(tmp_path)
    shutil.rmtree(root/'coordinates'/tag)
    with pytest.raises(ValueError,match='coordinate packet'):
        offline.bootstrap(root,stage,rows,{tag:pos},copy_batch)
    assert not (stage/tag).exists()


def test_incomplete_pipeline_result_not_synced(tmp_path):
    root,stage,remote,tag,rows,pos=setup_one(tmp_path)
    offline.bootstrap(root,stage,rows,{tag:pos},copy_batch)
    (root/'analysis'/tag/'storage_retention.json').unlink()
    count,pending=offline.sync_once(root,stage,remote,rows,copy_batch)
    assert count==0 and not pending and not (remote/tag).exists()


def test_batch_uses_local_queue_even_when_remote_is_offline(tmp_path, monkeypatch):
    root,stage,remote,tag,rows,pos=setup_one(tmp_path)
    bundle=tmp_path/'bundle';bundle.mkdir()
    with (bundle/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(next(iter(rows.values()))))
        writer.writeheader();writer.writerows(rows.values())
    snapshot=tmp_path/'snapshot.json';snapshot.write_text(json.dumps({'positions_sha256':{tag:pos}}))
    shutil.rmtree(remote)
    calls=[]
    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(offline.subprocess,'run',run)
    monkeypatch.setattr(sys,'argv',['offline','--bundle',str(bundle),'--sdk-python',str(tmp_path/'sdk'),
        '--local-root',str(root),'--shared-root',str(remote),'--snapshot',str(snapshot)])
    assert offline.main()==0
    assert calls[0][calls[0].index('--shared-root')+1] == str(root/'coordinate_queue_group004_005_20261106_01')
    assert (root/'coordinates'/tag/'positions.json').exists()
