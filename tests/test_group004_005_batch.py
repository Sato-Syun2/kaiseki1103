import csv
import sys
from types import SimpleNamespace

from corridor_tracking import group004_005_batch as batch


def test_batch_skips_pilot_and_runs_both_groups(tmp_path, monkeypatch):
    root, shared, bundle = (tmp_path/x for x in ('root', 'shared', 'bundle'))
    for p in (root, shared, bundle): p.mkdir()
    sdk = tmp_path/'sdkpython'; sdk.touch()
    rows = [{'group':'4', 'recording':'recording_006'}, {'group':'4', 'recording':'recording_007'},
            {'group':'5', 'recording':'recording_001'}]
    with (bundle/'inventory.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    pilot='g004_recording_006_pilot_20261106_02'
    (shared/pilot).mkdir()
    receipt=root/'analysis'/pilot/'storage_retention.json';receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"complete"}')
    calls=[];checked=[]
    monkeypatch.setattr(batch,'validate_existing',lambda row,*args:checked.append(row['recording']))
    monkeypatch.setattr(batch.subprocess,'run',lambda cmd,**kw:(calls.append(cmd) or SimpleNamespace(returncode=0)))
    monkeypatch.setattr(sys,'argv',['batch','--bundle',str(bundle),'--sdk-python',str(sdk),
                                   '--local-root',str(root),'--shared-root',str(shared)])
    batch.main()
    assert checked==['recording_006'] and len(calls)==2
    assert [x[x.index('--group')+1] for x in calls]==['4','5']
    assert all('--compact-intermediates' in x for x in calls)
