import json

import pytest

from corridor_tracking.analysis_exclusions import excluded, load_exclusions


def test_operator_exclusions_do_not_remove_the_replacement_takes():
    rules=load_exclusions()
    assert excluded({'group':2,'recording':'recording_017'},rules)['replacement_recording']=='recording_018'
    assert excluded({'group':4,'recording':'recording_022'},rules)['replacement_recording']=='recording_023'
    assert excluded({'group':7,'recording':'recording_007'},rules)['replacement_recording'] is None
    for group,recording in ((2,'recording_018'),(4,'recording_023'),(8,'recording_007')):
        assert excluded({'group':group,'recording':recording},rules) is None


def test_invalid_registry_fails_closed(tmp_path):
    p=tmp_path/'exclusions.json';p.write_text(json.dumps({'schema_version':1,'exclusions':[{'group':2,'recording':'recording_017','source_svo_sha256':'not-a-hash','reason':'exclude'}]}))
    with pytest.raises(ValueError,match='invalid exclusion'):
        load_exclusions(p)
