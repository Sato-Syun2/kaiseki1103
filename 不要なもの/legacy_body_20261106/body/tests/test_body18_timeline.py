import pytest
from body.compare_body18_34 import validate_image_timeline


def test_image_timeline_accepts_csv_frame_numbers_and_rejects_mismatch():
    frames={3:{'image_timestamp_ns':'1000'},4:{'image_timestamp_ns':'2000'}}
    validate_image_timeline([{'frame_index':'3','image_timestamp_ns':'1000'}],frames)
    with pytest.raises(ValueError,match='Image timestamp mismatch'):
        validate_image_timeline([{'frame_index':'3','image_timestamp_ns':'1001'}],frames)
    with pytest.raises(ValueError,match='Image timestamp mismatch'):
        validate_image_timeline([{'frame_index':'5','image_timestamp_ns':'1000'}],frames)
