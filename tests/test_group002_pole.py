import numpy as np
import pytest
from inspect_group002_pole import select_sample_points


def test_depth_points_follow_saved_sample_not_svo_frame_number():
    xyz=np.array([[1,2,3],[4,5,6],[7,8,9]],dtype=float)
    indices=np.array([0,1,1]);frames=np.array([0,1]);timestamps=np.array([100,200])
    record=dict(sample_index='1',frame_index='15',image_timestamp_ns='200',valid_depth_points='2')
    assert select_sample_points(xyz,indices,frames,timestamps,record).tolist()==xyz[1:].tolist()
    with pytest.raises(ValueError,match='timestamp'):
        select_sample_points(xyz,indices,frames,timestamps,dict(record,image_timestamp_ns='201'))
