"""Validate available coordinate-only results and build a recording gallery."""
import argparse
import csv
import html
import json
from pathlib import Path
import re
import subprocess
import sys


def available_source(shared_root, group, recording, run_id):
    prefix = f'g{group:03d}_{recording}_'
    preferred = [shared_root/(prefix+run_id), shared_root/(prefix+run_id+'_retry01')]
    for path in preferred:
        if path.is_dir():
            return path
    compact = sorted(p for p in shared_root.glob(prefix+'compact_*') if p.is_dir()
                     and re.fullmatch(re.escape(prefix) + r'compact_[A-Za-z0-9_]+', p.name))
    if len(compact) > 1:
        raise ValueError(f'multiple compact results for {prefix}')
    return compact[0] if compact else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--shared-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run-id', default='20261105_01')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+', a.run_id):
        p.error('invalid run ID')
    if a.output.exists():
        raise FileExistsError('output already exists')
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    a.output.mkdir(parents=True, exist_ok=False)
    records, failures = [], []
    for row in rows:
        group, rec = int(row['group']), row['recording']
        try:
            source = available_source(a.shared_root, group, rec, a.run_id)
        except ValueError as exc:
            failures.append({'group': group, 'recording': rec, 'error': str(exc)})
            records.append({'group': group, 'recording': rec, 'status': 'invalid'})
            continue
        if source is None and row['existing_depth'] == 'yes':
            records.append({'group': group, 'recording': rec, 'status': 'previously_processed'})
        elif source is None:
            records.append({'group': group, 'recording': rec, 'status': 'not_received'})
        else:
            dest = a.output/f'g{group:03d}_{rec}'
            cmd = [sys.executable, '-m', 'corridor_tracking.coordinate_only_replay', '--input', str(source),
                   '--inventory', str(a.inventory), '--group', str(group), '--recording', rec, '--output', str(dest)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode:
                failures.append({'group': group, 'recording': rec, 'error': result.stderr[-2000:]})
                records.append({'group': group, 'recording': rec, 'status': 'invalid'})
            else:
                records.append({'group': group, 'recording': rec, 'status': 'ready', 'page': f'g{group:03d}_{rec}/index.html'})
    sections = []
    for group in (2, 3):
        lines = []
        for r in records:
            if r['group'] != group:
                continue
            label = html.escape(r['recording'])
            if r['status'] == 'ready':
                lines.append(f'<li><a href="{html.escape(r["page"])}">{label}</a></li>')
            else:
                state = {'not_received':'未受領', 'invalid':'要確認', 'previously_processed':'別途解析済み'}[r['status']]
                lines.append(f'<li>{label} — {state}</li>')
        sections.append(f'<h2>グループ{group}</h2><ul>'+''.join(lines)+'</ul>')
    ready = sum(r['status'] == 'ready' for r in records)
    page = '<!doctype html><meta charset="utf-8"><title>廊下座標の再生一覧</title><style>body{font:16px system-ui;margin:24px}li{margin:5px}</style><h1>深度による廊下座標の再生一覧</h1><p>共有された人物座標だけで表示します。位置は可視表面の代表点候補、IDと校正は暫定です。</p>' + f'<p>受領・検証済み {ready} 録画 / 要確認 {len(failures)} 録画</p>' + ''.join(sections)
    (a.output/'index.html').write_text(page, encoding='utf-8')
    (a.output/'status.json').write_text(json.dumps({'records':records, 'failures':failures}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'{ready} ready, {len(failures)} invalid: {a.output / "index.html"}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
