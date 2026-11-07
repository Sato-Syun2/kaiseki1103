#!/usr/bin/env python3
"""Compare the conservative hold experiment on previously reviewed data.

All input observations and annotations are immutable. The six legacy reviews
have already been inspected during Goal A, and are not an independent test.
"""
import argparse
import csv
import json
from pathlib import Path

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import diagnostics, evaluate_checkpoints, evaluate_intervals
from corridor_tracking.tracker import Config, run_tracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    annotation_path = Path('results/tracking_v2/visual_review_20261104/annotations_final.json')
    annotation = json.loads(annotation_path.read_text())
    config_paths = [Path('configs/tracking_candidate_final_20261104.json'),
                    Path('configs/tracking_goal_b_hold_candidate_20261104.json')]
    configs = [json.loads(p.read_text()) for p in config_paths]
    specs = [('goal_a_20261104_02', n) for n in ['001','003','025','002','044','048']]
    specs += [('group002_20261104_analysis_01', n) for n in ['001','012']]
    specs += [('group003_20261104_analysis_01', n) for n in ['001','017']]
    rows, details, inputs = [], [], {}
    for run, number in specs:
        path = Path('results/tracking_v2') / run / ('recording_' + number) / 'observations.json'
        data = json.loads(path.read_text())
        inputs[str(path)] = sha256(path)
        for mode, cfg in zip(['candidate_original','candidate_hold'], configs):
            result = run_tracker(data, Config.from_dict(cfg))
            metrics = diagnostics(data, result)
            checkpoints = evaluate_checkpoints(data, result, annotation, 'recording_'+number) if run.startswith('goal_a_') else None
            intervals = evaluate_intervals(data, result, annotation, 'recording_'+number) if checkpoints else []
            row = {'run':run, 'recording':number, 'mode':mode,
                   **{k:metrics[k] for k in ['baseline_points','candidate_points','baseline_tracks','candidate_tracks']},
                   'ambiguous':metrics['id_status'].get('ambiguous',0),
                   'unresolved_identity':metrics['sources'].get('unresolved_identity',0)}
            if checkpoints:
                row.update({k:checkpoints['scores']['candidate'][k] for k in
                    ['person_checkpoints','matched_positions','identity_changes_lower_bound',
                     'fragmented_identities_lower_bound','cross_person_id_reuse_lower_bound']})
            rows.append(row)
            details.append(dict(run=run, recording=number, mode=mode, metrics=metrics,
                                checkpoints=checkpoints, intervals=intervals))
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (args.output/'comparison.csv').open('w', newline='', encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    (args.output/'details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    metadata = {'scope':'previously viewed reviews, not independent evaluation; 30fps examples are diagnostics only',
                'input_sha256':inputs, 'annotations_sha256':sha256(annotation_path),
                'config_sha256':{str(p):sha256(p) for p in config_paths},
                'tracker_sha256':sha256(Path('corridor_tracking/tracker.py')),
                'script_sha256':sha256(Path(__file__))}
    (args.output/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(args.output/'comparison.csv')


if __name__ == '__main__':
    main()
