import csv
import sys
from types import SimpleNamespace

import pytest

from corridor_tracking import compact_batch as batch


def row(recording='recording_018', group='2'):
    return {'group':group,'recording':recording,'frame_count':'1','source_svo_sha256':'abc'}


def test_reuses_original_or_previous_retry_and_avoids_partial_runs(tmp_path):
    root, shared = tmp_path/'ssd', tmp_path/'share'; shared.mkdir(); root.mkdir()
    r=row(); prefix='compact_20261105_01'
    assert batch.existing_run(r, shared, prefix) is None
    (root/'analysis'/batch.tag_for(r, '20261105_01')).mkdir(parents=True)
    assert batch.fresh_run(r, root, shared, prefix) == prefix
    (root/'analysis'/batch.tag_for(r, prefix)).mkdir(parents=True)
    assert batch.fresh_run(r, root, shared, prefix) == prefix+'_retry01'
    (shared/batch.tag_for(r, '20261105_01_retry01')).mkdir()
    assert batch.existing_run(r, shared, prefix) == '20261105_01_retry01'
    (shared/batch.tag_for(r, '20261105_01')).mkdir()
    assert batch.existing_run(r, shared, prefix) == '20261105_01'


def test_multiple_compact_results_are_not_silently_selected(tmp_path):
    r=row(); prefix='compact_20261105_01'
    (tmp_path/batch.tag_for(r,prefix)).mkdir()
    assert batch.existing_run(r,tmp_path,prefix) == prefix
    (tmp_path/batch.tag_for(r,prefix+'_retry01')).mkdir()
    with pytest.raises(ValueError, match='multiple completed'):
        batch.existing_run(r,tmp_path,prefix)


def test_batch_validates_existing_and_starts_new_runs_with_compact_retention(tmp_path, monkeypatch):
    bundle=tmp_path/'bundle';bundle.mkdir()
    root=tmp_path/'ssd';root.mkdir()
    shared=tmp_path/'shared';shared.mkdir()
    sdk=tmp_path/'sdkpython';sdk.touch()
    rows=[row(f'recording_{i:03d}', '2') for i in range(1,56)] + [row(f'recording_{i:03d}', '3') for i in range(1,55)]
    with (bundle/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    for r in rows[:-1]: (shared/batch.tag_for(r,'20261105_01')).mkdir()
    checked=[];commands=[]
    monkeypatch.setattr(batch,'validate_existing',lambda r,*a:checked.append(r))
    monkeypatch.setattr(batch.subprocess,'run',lambda cmd,**k:(commands.append(cmd) or SimpleNamespace(returncode=0)))
    monkeypatch.setattr(sys,'argv',['compact_batch','--bundle',str(bundle),'--sdk-python',str(sdk), '--local-root',str(root),'--shared-root',str(shared)])
    assert batch.main() == 0
    assert len(checked) == 108 and len(commands) == 1
    command=commands[0]
    assert '--compact-intermediates' in command
    assert command[command.index('--run-id')+1] == 'compact_20261105_01'
    assert command[command.index('--point-archive-mode')+1] == 'compressed'
