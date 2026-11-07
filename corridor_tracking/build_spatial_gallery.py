"""Build coordinate-only replays for spatially filtered results."""
import argparse
import html
import json
import os
from pathlib import Path

from corridor_tracking.coordinate_only_replay import make_page
from corridor_tracking.filter_shared_positions import read_packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--filtered-root', required=True, type=Path, action='append')
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('choose a new gallery destination')
    a.output.mkdir(parents=True, exist_ok=False)
    links = []
    for filtered_root in a.filtered_root:
        for kind, status in (('originals', 'complete'), ('candidates', 'proposed_not_verified')):
            folder = filtered_root/kind
            if not folder.is_dir():
                continue
            for source in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.')):
                data, manifest = read_packet(source, status)
                dest = a.output/kind/source.name
                dest.mkdir(parents=True)
                title = f"グループ{manifest['group']} {manifest['recording']}" + (' ID再割当て候補' if kind == 'candidates' else '')
                page = make_page(data, title)
                if kind == 'candidates':
                    page = page.replace(' <a href="review.html">同時刻の画像で確認</a> / <a href="report_ja.md">条件と制約</a>', '')
                for name in ('positions.json', 'manifest.json'):
                    rel = os.path.relpath(source/name, dest).replace(os.sep, '/')
                    page = page.replace(f'href="{name}"', f'href="{html.escape(rel, quote=True)}"')
                notice = '<p><strong>Xが15 mを超える観測と両側の壁の外の観測を除外しています。</strong>反対側の壁は廊下幅からの暫定推定です。位置不明の観測は保留しています。</p>'
                page = page.replace('<label>時刻', notice+'<label>時刻', 1)
                (dest/'index.html').write_text(page, encoding='utf-8')
                links.append((kind, title, (dest/'index.html').relative_to(a.output).as_posix()))
    sections = []
    for kind, label in (('originals', '範囲内の座標'), ('candidates', '範囲内のID再割当て候補')):
        items = ''.join(f'<li><a href="{html.escape(path, quote=True)}">{html.escape(title)}</a></li>'
                        for k,title,path in links if k == kind)
        sections.append(f'<h2>{label}</h2><ul>{items}</ul>')
    page = ('<!doctype html><meta charset="utf-8"><title>範囲内の深度座標</title>'
            '<style>body{font:16px sans-serif;margin:24px}li{margin:6px}</style><h1>範囲内の深度座標</h1>'
            '<p>Xが15 m超、または両側の壁の外にある座標を除外しています。壁・IDは暫定です。</p>' + ''.join(sections))
    (a.output/'index.html').write_text(page, encoding='utf-8')
    print(f'{len(links)} replays: {a.output / "index.html"}')


if __name__ == '__main__':
    main()
