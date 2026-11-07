from body.sdk_body_review import chosen_images, frame_counts


def test_flagged_events_are_mapped_to_available_image_frames():
    saved=[0,10,20,30,40,50,60,70,80,90]
    chosen=chosen_images(saved,[{'frame':24},{'frame':67}],12)
    assert set(chosen)<=set(saved)
    assert 20 in chosen and 70 in chosen
    assert len(chosen)==len(set(chosen))


def test_camera_space_counts_are_diagnostics_not_person_counts():
    bodies=[{'joints':[[0,0,-1]],'pixels':[[3,3]]},
            {'joints':[[0,0,2]],'pixels':[[11,3]]},
            {'joints':[[None,0,2]],'pixels':[[None,0]]}]
    result=frame_counts({'camera':{'width':10,'height':10},'bodies':{0:bodies}})
    assert result=={'sdk_body_observations':3,'pelvis_z_nonpositive':1,'pelvis_2d_outside_image':1}
