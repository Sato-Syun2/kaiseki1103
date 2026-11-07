"""Conservatively exclude observations outside a documented corridor region."""
import copy
import math


def corridor_bounds(calibration, *, max_x_m=15.0, fallback_width_m=None):
    """Return the camera-origin corridor limits, never guessing a missing wall."""
    visible = float(calibration['visible_wall_Y_m'])
    if not math.isfinite(visible) or not math.isfinite(max_x_m) or max_x_m <= 0:
        raise ValueError('invalid visible wall or X limit')
    inference = calibration.get('other_wall_inference') or {}
    opposite = inference.get('opposite_wall_Y_m_assuming_same_boundaries')
    source = 'calibration_other_wall_inference'
    if opposite is None:
        if fallback_width_m is None or not math.isfinite(float(fallback_width_m)) or float(fallback_width_m) <= 0:
            raise ValueError('opposite wall is unknown; an explicit corridor width is required')
        opposite = visible - float(fallback_width_m)
        source = 'same_corridor_width_assumption'
    opposite = float(opposite)
    if not math.isfinite(opposite) or opposite == visible:
        raise ValueError('invalid opposite wall')
    return {'max_x_m': float(max_x_m), 'min_y_m': min(visible, opposite), 'max_y_m': max(visible, opposite),
            'visible_wall_y_m': visible, 'opposite_wall_y_m': opposite, 'opposite_wall_source': source,
            'fallback_width_m': float(fallback_width_m) if source == 'same_corridor_width_assumption' else None,
            'rule': 'exclude x > max_x or y outside [min_y, max_y]; keep points on boundary',
            'unknown_position': 'retain as unlocated; cannot determine whether inside'}


def in_region(point, bounds):
    if point is None:
        return True
    if len(point) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in point):
        raise ValueError('invalid or non-finite position')
    return point[0] <= bounds['max_x_m'] and bounds['min_y_m'] <= point[1] <= bounds['max_y_m']


def filter_frames(frames, bounds):
    result, selected = [], []
    stats = {'outside_any': 0, 'outside_x': 0, 'outside_wall': 0, 'inside_positioned': 0, 'unlocated_retained': 0}
    for frame in frames:
        keep = []
        for i, obs in enumerate(frame['observations']):
            point = obs.get('surface_corridor_m')
            if in_region(point, bounds):
                keep.append(i)
                stats['unlocated_retained' if point is None else 'inside_positioned'] += 1
            else:
                stats['outside_any'] += 1
                if point[0] > bounds['max_x_m']:
                    stats['outside_x'] += 1
                if not bounds['min_y_m'] <= point[1] <= bounds['max_y_m']:
                    stats['outside_wall'] += 1
        out = copy.deepcopy(frame)
        out['observations'] = [copy.deepcopy(frame['observations'][i]) for i in keep]
        selected.append(keep)
        result.append(out)
    return result, selected, stats
