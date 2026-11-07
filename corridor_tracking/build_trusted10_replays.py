"""Create separate Windows SSD video/replays using verified shared 10 m positions."""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def load_helper(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def prepare_one(root,bundle,source,out,spatial,quality,expected_filter_hash):
    from corridor_tracking.depth_person_comparison import load_run
    from corridor_tracking.portable_depth_replay import joined_frames
    from corridor_tracking.depth_corridor_replay import make_page
    from depth_person_prototype import safe_asset
    tag=source.name
    if not re.fullmatch(r'g00[2345]_recording_\d{3}_[A-Za-z0-9_]+',tag):raise ValueError('unexpected tag')
    manifest=read(source/'manifest.json');processed=read(source/'positions.json')
    if (manifest.get('status')!='complete' or manifest.get('positions_sha256')!=digest(source/'positions.json')
            or manifest.get('algorithm_sha256')!=expected_filter_hash
            or manifest.get('trajectory_quality_sha256')!=digest(Path(__file__).with_name('trajectory_quality.py'))):
        raise ValueError('10m packet hash or algorithm does not match')
    local=root/'coordinates'/tag; raw_manifest=read(local/'manifest.json');raw=read(local/'positions.json')
    if (raw_manifest.get('status')!='complete' or raw_manifest.get('positions_sha256')!=digest(local/'positions.json')
            or manifest.get('source_positions_sha256')!=digest(local/'positions.json') or raw['metadata']!=processed['metadata']):
        raise ValueError('SSD original coordinates differ from 10m source')
    bounds=manifest['bounds']
    if bounds.get('max_x_m')!=10.0:raise ValueError('unexpected corridor X limit')
    in_bounds,chosen,_=spatial.filter_frames(raw['frames'],bounds)
    first,_=quality.withhold_isolated_excursions(in_bounds)
    recomputed,_,_=quality.withhold_discontinuous_pairs(first)
    if recomputed!=processed['frames']:raise ValueError('10m trajectory quality output does not match source')
    merged=root/'analysis'/tag/'merged'; person=load_run(merged)
    if digest(merged/'manifest.json')!=raw['metadata']['person_run_manifest_sha256']:
        raise ValueError('merged person run differs from SSD coordinates')
    frames=joined_frames(person['frames'],raw['frames'])
    if len(frames)!=len(recomputed):raise ValueError('frame count differs')
    for i,(frame,selection,clean) in enumerate(zip(frames,chosen,recomputed)):
        frame['review_image']=os.path.relpath(safe_asset(merged,frame['review_image']),out).replace(os.sep,'/')
        selected=[frame['observations'][j] for j in selection]
        for target,position in zip(selected,clean['observations']):
            target['surface_corridor_m']=position['surface_corridor_m']
            if position.get('position_quality'):target['position_quality']=position['position_quality']
        frame['observations']=selected
    data={'frames':frames,'walls':processed['walls'],'spatial_filter':bounds}
    page=make_page(data,f'{tag}：10m以内・不連続位置保留')
    page=page.replace("depth_status:o.depth_status,association:o.association_reason", "depth_status:o.depth_status,position_quality:o.position_quality||null,association:o.association_reason")
    notice=('<p><strong>10m以内の座標です。</strong>不連続の疑いがある位置は欠測にしており、補間していません。'
            '元画像に描き込まれた点・輪郭は処理前のままの場合があります。新しく表示したID枠と上面図を確認してください。</p>')
    page=page.replace('<label>時刻',notice+'<label>時刻',1)
    result={'status':'complete','tag':tag,'source_positions_sha256':digest(local/'positions.json'),
            'trusted_positions_sha256':digest(source/'positions.json'),
            'person_manifest_sha256':digest(merged/'manifest.json'),
            'renderer_script_sha256':digest(Path(__file__)),
            'limits':['ID and calibration provisional','images are existing SSD assets; no image copies',
                      'no interpolation; invalid edge positions withheld, not corrected']}
    if out.exists():
        old=read(out/'manifest.json')
        if any(old.get(k)!=v for k,v in result.items()) or old.get('index_sha256')!=digest(out/'index.html'):
            raise ValueError('existing replay differs; will not overwrite')
        return False
    out.mkdir(parents=True,exist_ok=False)
    (out/'index.html').write_text(page,encoding='utf-8')
    result['index_sha256']=digest(out/'index.html')
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--local-root',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--shared-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.local_root.resolve();bundle=a.bundle.resolve();shared=a.shared_root
    sys.path.insert(0,str(bundle))
    spatial=load_helper(Path(__file__).with_name('spatial_filter.py'),'trusted_spatial')
    quality=load_helper(Path(__file__).with_name('trajectory_quality.py'),'trusted_quality')
    expected=digest(Path(__file__).with_name('trusted_depth_10m.py'))
    if not shared.is_dir():raise FileNotFoundError('10m shared coordinates unavailable; reconnect and rerun')
    a.output.mkdir(parents=True,exist_ok=True)
    entries=[];errors=[]
    for i,source in enumerate(sorted((shared/'originals').glob('g00[2345]_recording_*')),1):
        if not source.is_dir():continue
        try:
            created=prepare_one(root,bundle,source,a.output/source.name,spatial,quality,expected)
            entries.append(source.name)
            if created:print(f'[Replay] Created: {source.name}',flush=True)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append({'tag':source.name,'error':str(exc)})
            print(f'[Replay] Skipped {source.name}: {exc}',flush=True)
    marker='<meta name="trusted10-generated" content="1">';index=a.output/'index.html'
    if index.exists() and marker not in index.read_text(encoding='utf-8'):
        raise FileExistsError('existing replay index is not generated by this program')
    import html
    links=''.join(f'<li><a href="{html.escape(tag,quote=True)}/index.html">{html.escape(tag)}</a></li>' for tag in entries)
    warnings=''.join(f'<li>{html.escape(x["tag"])}: {html.escape(x["error"])}</li>' for x in errors)
    page=('<!doctype html><html lang="ja"><meta charset="utf-8">'+marker+'<title>10m以内の画像と位置</title>'
          '<style>body{font:16px system-ui;margin:25px}li{margin:6px}</style><h1>10m以内の画像と位置</h1>'
          '<p>元画像をSSDから参照し、範囲外・急変で保留した位置を上面図に描画しません。IDと校正は暫定です。</p>'
          f'<p>作成済み・照合済み {len(entries)} 件 / 未作成 {len(errors)} 件</p><ul>'+links+'</ul><h2>未作成</h2><ul>'+warnings+'</ul></html>')
    temp=a.output/'index.html.tmp';temp.write_text(page,encoding='utf-8');temp.replace(index)
    print(f'[Replay] Index: {index}; ready {len(entries)}, skipped {len(errors)}',flush=True)
    return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
