import pytest

from analyze_goal_b_pole_spacing import calculate_spacings


def test_spacing_does_not_depend_on_common_camera_origin():
    stations=[dict(distance_from_end_m=3,median_X_m=2.9),
              dict(distance_from_end_m=5,median_X_m=4.8),
              dict(distance_from_end_m=7,median_X_m=6.8)]
    original=calculate_spacings(stations)
    translated=calculate_spacings([{**s,'median_X_m':s['median_X_m']+7.3} for s in stations])
    assert [s['nominal_spacing_m'] for s in original]==[2,2]
    assert [s['observed_median_spacing_m'] for s in original]==pytest.approx([1.9,2.0])
    assert [s['observed_minus_nominal_m'] for s in original]==pytest.approx(
        [s['observed_minus_nominal_m'] for s in translated])
    with pytest.raises(ValueError,match='distinct'):
        calculate_spacings([stations[0],stations[0]])
