import pytest
from corridor_tracking.coordinate_gallery import available_source


def test_gallery_finds_retry_and_compact_results_without_confusing_recordings(tmp_path):
    retry=tmp_path/'g002_recording_018_20261105_01_retry01';retry.mkdir()
    compact=tmp_path/'g002_recording_032_compact_20261105_01';compact.mkdir()
    assert available_source(tmp_path,2,'recording_018','20261105_01') == retry
    assert available_source(tmp_path,2,'recording_032','20261105_01') == compact
    assert available_source(tmp_path,2,'recording_033','20261105_01') is None
    original=tmp_path/'g002_recording_018_20261105_01';original.mkdir()
    assert available_source(tmp_path,2,'recording_018','20261105_01') == original
    (tmp_path/'g002_recording_032_compact_20261105_01_retry01').mkdir()
    with pytest.raises(ValueError,match='multiple compact results'):
        available_source(tmp_path,2,'recording_032','20261105_01')
