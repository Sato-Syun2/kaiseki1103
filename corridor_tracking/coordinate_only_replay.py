"""Build an overhead replay from shared person coordinates; no images or depth files."""
import argparse
import csv
import html
import json
import math
from pathlib import Path

from depth_person_prototype import digest


def make_page(data, title):
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return r'''<!doctype html><html lang="ja"><meta charset="utf-8"><title>廊下座標の人物再生</title>
<style>body{font:16px system-ui,sans-serif;margin:24px;color:#203040}canvas{width:min(100%,1100px);height:auto;border:1px solid #bac8cf}input[type=range]{width:min(900px,90%)}button,label{margin:5px}pre{white-space:pre-wrap}</style>
<h1>__TITLE__：廊下座標の上面再生</h1><p>深度から求めた可視表面の代表点を表示します。身体中心や足の位置ではなく、ID・校正は暫定です。SDK骨格は使用していません。0.1秒を超える時刻の空きや欠測は線で結びません。</p>__NOTICE__
<label>時刻 <input type="range" id="slider" min="0" value="0" step="1"><span id="clock"></span></label><br>
<button id="play">再生</button><button id="stop">停止</button><button id="reset">最初へ</button><label>速度 <select id="speed"><option value="0.5">0.5倍</option><option value="1" selected>1倍</option><option value="2">2倍</option></select></label><br>
<canvas id="map" width="1100" height="500"></canvas><p>横軸は廊下方向X、縦軸は横方向Y（m）。原点はカメラの床面投影。実線は深度から推定した壁、破線は推定した反対側の壁です。点と線の色は録画内の暫定IDを示します。</p><p id="status"></p><pre id="details"></pre><p><a href="positions.json">時刻付き座標</a> / <a href="manifest.json">照合記録</a></p>
<script type="application/json" id="data">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent),f=D.frames,s=document.getElementById('slider'),c=document.getElementById('map'),m=c.getContext('2d');s.max=f.length-1;let timer=null;
const pts=f.flatMap(x=>x.observations).filter(o=>o.track_id!==null&&o.surface_corridor_m).map(o=>o.surface_corridor_m),w=D.walls.visible,z=D.walls.opposite;
const xs=pts.map(p=>p[0]).concat([0]),ys=pts.map(p=>p[1]).concat([0,...[w,z].filter(Number.isFinite)]),xmin=Math.floor(Math.min(...xs)-.5),xmax=Math.ceil(Math.max(...xs)+.5),ymin=Math.floor(Math.min(...ys)-.5),ymax=Math.ceil(Math.max(...ys)+.5);
const scale=Math.min(980/(xmax-xmin||1),390/(ymax-ymin||1)),px=x=>70+(x-xmin)*scale,py=y=>30+(ymax-y)*scale,color=id=>`hsl(${(id*137)%360},85%,42%)`;
function render(){const i=Number(s.value),cur=f[i];document.getElementById('clock').textContent=` ${cur.elapsed_s.toFixed(3)}秒 / frame ${cur.frame_index}`;document.getElementById('status').textContent=`検出 ${cur.observations.length} 件 / 深度候補 ${cur.observations.filter(o=>o.surface_corridor_m).length} 件`;document.getElementById('details').textContent=JSON.stringify(cur.observations,null,2);m.clearRect(0,0,c.width,c.height);m.fillStyle='white';m.fillRect(0,0,c.width,c.height);m.font='14px sans-serif';
for(let x=Math.ceil(xmin);x<=xmax;x++){m.strokeStyle='#e1e6e9';m.beginPath();m.moveTo(px(x),py(ymin));m.lineTo(px(x),py(ymax));m.stroke();m.fillStyle='#334';m.fillText(x,px(x)-4,py(ymin)+20)}for(let y=Math.ceil(ymin);y<=ymax;y++){m.strokeStyle='#e1e6e9';m.beginPath();m.moveTo(px(xmin),py(y));m.lineTo(px(xmax),py(y));m.stroke();m.fillStyle='#334';m.fillText(y,px(xmin)-25,py(y)+4)}
for(const [v,dashed] of [[w,false],[z,true]])if(Number.isFinite(v)){m.strokeStyle='#344f60';m.lineWidth=2;m.setLineDash(dashed?[8,5]:[]);m.beginPath();m.moveTo(px(xmin),py(v));m.lineTo(px(xmax),py(v));m.stroke()}m.setLineDash([]);m.fillStyle='#344f60';m.fillText('X →',px(xmax)-20,py(ymin)+38);m.fillText('Y ↑',5,40);m.fillText('camera',px(0)+5,py(0)-7);m.beginPath();m.arc(px(0),py(0),4,0,7);m.fill();
for(let j=0;j<=i;j++)for(const o of f[j].observations){const p=o.surface_corridor_m;if(o.track_id===null||!p)continue;m.fillStyle=color(o.track_id);if(j>0&&f[j].frame_index===f[j-1].frame_index+1&&f[j].elapsed_s-f[j-1].elapsed_s<=.1){const q=f[j-1].observations.find(a=>a.track_id===o.track_id&&a.surface_corridor_m);if(q){m.strokeStyle=color(o.track_id);m.lineWidth=2;m.setLineDash(o.identity_assignment==='proposed'||q.identity_assignment==='proposed'?[5,4]:[]);m.beginPath();m.moveTo(px(q.surface_corridor_m[0]),py(q.surface_corridor_m[1]));m.lineTo(px(p[0]),py(p[1]));m.stroke();m.setLineDash([])}}m.beginPath();m.arc(px(p[0]),py(p[1]),j===i?7:2,0,7);m.fill();if(o.identity_assignment==='proposed'){m.strokeStyle='#fff';m.lineWidth=1.5;m.stroke()}if(j===i){m.font='bold 16px sans-serif';m.fillText(`ID ${o.track_id}${o.identity_assignment==='proposed'?' (候補)':''}`,px(p[0])+8,py(p[1])-8)}}}
function step(){const i=Number(s.value);if(i>=f.length-1){timer=null;return}timer=setTimeout(()=>{s.value=i+1;render();step()},Math.max(1,1000*(f[i+1].elapsed_s-f[i].elapsed_s)/Number(document.getElementById('speed').value)))}function stop(){clearTimeout(timer);timer=null}s.oninput=()=>{stop();render()};document.getElementById('play').onclick=()=>{if(!timer)step()};document.getElementById('stop').onclick=stop;document.getElementById('reset').onclick=()=>{stop();s.value=0;render()};render();</script></html>'''.replace('__TITLE__', html.escape(title)).replace('__DATA__', payload).replace('__NOTICE__', '<p><strong>IDの再割当ては未確認の候補です。白縁の点・破線が再割当て候補です。</strong> <a href="review.html">同時刻の画像で確認</a> / <a href="report_ja.md">条件と制約</a></p>' if data.get('reassignment_candidate') else '')


def validate_input(root, row):
    if {f.name for f in root.iterdir()} != {'positions.json', 'manifest.json'}:
        raise ValueError('coordinate share contains unexpected files')
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('status') != 'complete' or digest(root/'positions.json') != manifest.get('positions_sha256'):
        raise ValueError('coordinate output incomplete or hash mismatch')
    data = json.loads((root/'positions.json').read_text(encoding='utf-8-sig'))
    meta, frames = data['metadata'], data['frames']
    for key in ('source_svo_sha256', 'setup_id', 'calibration_sha256', 'body_manifest_sha256', 'recording'):
        if meta.get(key) != row[key]:
            raise ValueError(f'coordinate provenance mismatch: {key}')
    if str(meta.get('group')) != row['group'] or manifest.get('frame_count') != int(row['frame_count']):
        raise ValueError('recording group or frame count mismatch')
    if len(frames) != int(row['frame_count']) or [x['frame_index'] for x in frames] != list(range(len(frames))):
        raise ValueError('missing, duplicate or unordered frame')
    for previous, current in zip(frames, frames[1:]):
        if int(current['timestamp_ns']) <= int(previous['timestamp_ns']) or current['elapsed_s'] <= previous['elapsed_s']:
            raise ValueError('non-increasing time')
    for frame in frames:
        for o in frame['observations']:
            p = o['surface_corridor_m']
            if p is not None and (len(p) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)):
                raise ValueError('invalid corridor point')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--group', type=int, choices=[2, 3], required=True)
    p.add_argument('--recording', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('output already exists')
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['group'] == str(a.group) and r['recording'] == a.recording]
    if len(rows) != 1:
        raise ValueError('recording missing or duplicated in inventory')
    row = rows[0]
    data = validate_input(a.input, row)
    calpath = Path(row['calibration'])
    if digest(calpath) != row['calibration_sha256']:
        raise ValueError('local calibration changed')
    cal = json.loads(calpath.read_text())
    data['walls'] = {'visible': cal.get('visible_wall_Y_m'), 'opposite': cal.get('other_wall_inference', {}).get('opposite_wall_Y_m_assuming_same_boundaries')}
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output/'index.html').write_text(make_page(data, f'グループ{a.group} {a.recording}'), encoding='utf-8')
    (a.output/'positions.json').write_bytes((a.input/'positions.json').read_bytes())
    manifest = {'status': 'complete', 'source_manifest_sha256': digest(a.input/'manifest.json'),
                'positions_sha256': digest(a.output/'positions.json'), 'calibration_sha256': digest(calpath),
                'renderer_sha256': digest(Path(__file__)), 'index_sha256': digest(a.output/'index.html')}
    (a.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(a.output/'index.html')


if __name__ == '__main__':
    main()
