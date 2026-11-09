#!/usr/bin/env python3
"""Reproducible descriptive join of survey and existing provisional trajectories.

The trajectory-role to questionnaire-role match is an explicit hypothesis, not
an identity validation. No source data are modified.
"""
import collections
import csv
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path('/home/hp-ubuntu/kaiseki1103')
BOOK = ROOT / 'inputs/追い越し実験_アンケート入力・途中終了対応.xlsx'
FEATURES = Path('/home/hp-ubuntu/pedestrian_sim/overtaking/behavior_results/features_per_role.csv')
OUT = ROOT / 'results/subjective_trajectory_exploration_20261108_02'
NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workbook_rows():
    with zipfile.ZipFile(BOOK) as z:
        strings = [''.join(t.text or '' for t in el.iter('{%s}t' % NS['x']))
                   for el in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        root = ET.fromstring(z.read('xl/worksheets/sheet3.xml'))
        for row in root.findall('.//x:sheetData/x:row', NS):
            if int(row.attrib['r']) < 4:
                continue
            values = {}
            for c in row.findall('x:c', NS):
                column = re.match(r'[A-Z]+', c.attrib['r']).group()
                v = c.find('x:v', NS)
                if v is None or v.text is None:
                    continue
                values[column] = strings[int(v.text)] if c.get('t') == 's' else v.text
            yield values


def run():
    OUT.mkdir(parents=True, exist_ok=False)
    survey = list(workbook_rows())
    counts = collections.Counter()
    keyed = collections.defaultdict(list)
    invalid = []
    for row in survey:
        answers = [row.get(col) for col in 'IJKLMN']
        if any(a not in (None, '') for a in answers):
            counts[row.get('A', '?')] += 1
        for col, answer in zip('IJKLMN', answers):
            if answer not in (None, '') and answer not in tuple(map(str, range(1, 8))):
                invalid.append({'group': row.get('A'), 'trial': row.get('F'), 'column': col, 'value': answer})
        keyed[(row.get('A'), row.get('F'), row.get('H'))].append(row)

    feats = list(csv.DictReader(FEATURES.open(encoding='utf-8', newline='')))
    joined, failures = [], []
    rolemap = {'initially_trailing': '追い越す', 'initially_leading': '追い越される'}
    for f in feats:
        key = ('G%02d' % int(f['group']), f['trial_number'], rolemap[f['role']])
        candidates = keyed[key]
        if len(candidates) != 1:
            failures.append({'recording': f['recording'], 'role': f['role'], 'reason': 'nonunique_survey_key', 'count': len(candidates)})
            continue
        row = candidates[0]
        if row.get('G') != f['condition_id'] or row.get('Q') != '追い越し':
            failures.append({'recording': f['recording'], 'role': f['role'], 'reason': 'condition_mismatch'})
            continue
        if not all(row.get(c) in tuple(map(str, range(1, 8))) for c in 'IJKLMN'):
            failures.append({'recording': f['recording'], 'role': f['role'], 'reason': 'missing_or_invalid_answer'})
            continue
        other_role = '追い越される' if rolemap[f['role']] == '追い越す' else '追い越す'
        other = keyed[(key[0], key[1], other_role)]
        joined.append({**f, **{'Q%d' % (i + 1): int(row[c]) for i, c in enumerate('IJKLMN')},
                       'participant_label': row.get('D'), 'survey_role_assumption': rolemap[f['role']],
                       'Q5_opposite_role': int(other[0]['M']) if len(other) == 1 and other[0].get('M') in tuple(map(str, range(1, 8))) else ''})
    columns = list(joined[0]) if joined else []
    with (OUT / 'provisional_join.csv').open('w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=columns); writer.writeheader(); writer.writerows(joined)

    checks = [('min_observed_point_distance_m', 'Q5'),
              ('max_lateral_displacement_cross_window_m', 'Q2'),
              ('speed_drop_m_s', 'Q6')]
    correlations = []
    for x, y in checks:
        for role in rolemap:
            for group in ('all', '3'):
                rows = [r for r in joined if r['role'] == role and (group == 'all' or r['group'] == group)]
                rows = [r for r in rows if r[x] and math.isfinite(float(r[x]))]
                xx, yy = [float(r[x]) for r in rows], [int(r[y]) for r in rows]
                rho = float(spearmanr(xx, yy).statistic) if len(rows) >= 3 and len(set(xx)) > 1 and len(set(yy)) > 1 else None
                correlations.append({'feature': x, 'question': y, 'role': role, 'group': group, 'n_recordings': len(rows), 'spearman_rho': rho})
    sensitivity = []
    for role in rolemap:
        for group in ('all', '3'):
            for variant in ('exclude_high_jump', 'opposite_role', 'participant_1', 'participant_2'):
                rows = [r for r in joined if r['role'] == role and (group == 'all' or r['group'] == group)]
                if variant == 'exclude_high_jump': rows = [r for r in rows if r['high_jump_flag'] == 'False']
                if variant.startswith('participant_'): rows = [r for r in rows if r['participant_label'] == variant[-1]]
                q = 'Q5_opposite_role' if variant == 'opposite_role' else 'Q5'
                rows = [r for r in rows if r['min_observed_point_distance_m'] and r[q] != '']
                xx = [float(r['min_observed_point_distance_m']) for r in rows]; yy = [int(r[q]) for r in rows]
                rho = float(spearmanr(xx, yy).statistic) if len(rows) >= 3 and len(set(xx)) > 1 and len(set(yy)) > 1 else None
                sensitivity.append({'role': role, 'group': group, 'variant': variant, 'n_recordings': len(rows), 'rho': rho})
    summary = {'inputs_sha256': {str(BOOK): sha(BOOK), str(FEATURES): sha(FEATURES)},
               'survey_rows_with_any_answer_by_group': dict(sorted(counts.items())),
               'invalid_answer_cells': invalid, 'trajectory_role_rows': len(feats),
               'joined_role_rows': len(joined), 'joined_recordings': len(set(r['recording'] for r in joined)),
               'joined_by_group': dict(sorted(collections.Counter(r['group'] for r in joined).items())),
               'failures': failures, 'exploratory_correlations': correlations, 'distance_q5_sensitivity': sensitivity,
               'limitations': ['role mapping is unverified; no person ID ground truth',
                               'selection and point measurement are biased and provisional',
                               'all/group 3 correlations are descriptive, not independent participant inference']}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
