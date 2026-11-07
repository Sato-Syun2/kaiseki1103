"""Apply the corridor region to verified group 2/3 coordinates and ID candidates."""
import argparse
import copy
import csv
import json
from pathlib import Path

from corridor_tracking.coordinate_gallery import available_source
from corridor_tracking.coordinate_only_replay import validate_input
from corridor_tracking.filter_shared_positions import filter_candidate, save_packet
from corridor_tracking.spatial_filter import corridor_bounds, filter_frames
from depth_person_prototype import digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', required=True, type=Path)
    p.add_argument('--source-root', required=True, type=Path)
    p.add_argument('--candidate-root', required=True, type=Path)
    p.add_argument('--output-root', required=True, type=Path)
    a = p.parse_args()
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 109 or len({(r['group'],r['recording']) for r in rows}) != len(rows):
        raise ValueError('expected 109 unique group 2/3 recordings')
    sources, bounds_by_key = {}, {}
    for row in rows:
        group, rec = int(row['group']), row['recording']
        if group not in (2,3):
            raise ValueError('unexpected group')
        source = available_source(a.source_root, group, rec, '20261105_01')
        if source is None:
            raise ValueError(f'missing source: {group}/{rec}')
        data = validate_input(source, row)
        cal_path = Path(row['calibration'])
        if digest(cal_path) != row['calibration_sha256']:
            raise ValueError(f'calibration hash mismatch: {group}/{rec}')
        cal = json.loads(cal_path.read_text(encoding='utf-8-sig'))
        bounds = corridor_bounds(cal)
        frames, _, stats = filter_frames(data['frames'], bounds)
        result = copy.deepcopy(data)
        result['frames'] = frames
        result['walls'] = {'visible':bounds['visible_wall_y_m'], 'opposite':bounds['opposite_wall_y_m']}
        result['spatial_filter'] = {'bounds':bounds, 'source_positions_sha256':digest(source/'positions.json'),
            'source_manifest_sha256':digest(source/'manifest.json'), 'counts':stats,
            'position_semantics':'bounds apply to measured visible surface, not true person centre',
            'calibration':'provisional floor and inferred opposite wall'}
        record = {'status':'complete', 'source_positions_sha256':digest(source/'positions.json'),
                  'source_manifest_sha256':digest(source/'manifest.json'), 'bounds':bounds, 'counts':stats,
                  'group':group, 'recording':rec, 'frame_count':len(frames), 'allowed_files':['positions.json','manifest.json']}
        made = save_packet(a.output_root/'originals'/source.name, result, record)
        sources[(str(group),rec)] = source
        bounds_by_key[(str(group),rec)] = bounds
        if made:
            print(f'[範囲除外] {source.name}: 除外 {stats["outside_any"]} 観測', flush=True)
    for candidate in sorted(a.candidate_root.glob('g002_recording_*')):
        rec = candidate.name[5:18]
        key = ('2',rec)
        if key not in sources:
            raise ValueError(f'candidate has no source: {candidate}')
        source = sources[key]
        made, count = filter_candidate(source, candidate, a.output_root/'originals'/source.name,
                                       a.output_root/'candidates'/candidate.name, bounds_by_key[key])
        if made:
            print(f'[範囲除外] {candidate.name}: 仮割当て {count} 観測を保持', flush=True)
    print(f'[範囲除外] グループ2/3の {len(rows)} 録画を確認済み', flush=True)


if __name__ == '__main__':
    main()
