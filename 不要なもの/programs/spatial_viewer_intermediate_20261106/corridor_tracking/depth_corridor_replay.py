"""Create an overhead corridor-coordinate replay from a validated depth track."""
import argparse
import html
import json
import math
import os
from pathlib import Path

from depth_person_prototype import digest, safe_asset


def make_page(data, title):
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    page = r'''<!doctype html><html lang="ja"><meta charset="utf-8"><title>廊下座標での深度再生</title>
<style>body{font:16px system-ui,sans-serif;margin:22px;color:#24334b}canvas{max-width:100%;height:auto;border:1px solid #b7c4cb}input[type=range]{width:min(850px,90%)}button,label{margin:5px}pre{white-space:pre-wrap}.view{display:flex;flex-wrap:wrap;gap:12px;align-items:start}.view section{flex:1 1 600px}small{color:#555}</style>
<h1>__TITLE__：廊下座標の上面再生</h1>
<p>同じフレームの画像と、深度から求めた可視表面の代表点を表示します。点は身体中心・足の位置ではなく、IDと校正は暫定です。SDK骨格は位置推定に使用していません。0.1秒を超える時間の空きや欠測を線で結びません。</p>
<p>左の枠と右の点は同じ暫定IDの色です。人物上の点や輪郭の色は各フレームの検出順で変わります。点なしは深度が保留された状態であり、補間しません。</p>
__NOTICE__
<label>時刻 <input type="range" id="slider" min="0" value="0" step="1"><span id="clock"></span></label><br>
<button id="play">再生</button><button id="pause">停止</button><button id="reset">最初へ</button><label>速度 <select id="speed"><option value="0.5">0.5倍</option><option value="1" selected>1倍</option><option value="2">2倍</option></select></label>
<div class="view"><section><h2>画像・深度候補</h2><canvas id="image"></canvas></section><section><h2>廊下を上から見る</h2><canvas id="map" width="1100" height="500"></canvas><p>横軸：廊下に沿うX（m）。縦軸：横方向Y（m）。原点はカメラの床面投影。実線は深度から推定した壁、破線は別途推定した反対側の壁です。</p></section></div>
<p id="status"></p><pre id="details"></pre>__LINKS__
<script type="application/json" id="data">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent),frames=D.frames,s=document.getElementById('slider');s.max=frames.length-1;
const ic=document.getElementById('image'),ix=ic.getContext('2d'),mc=document.getElementById('map'),m=mc.getContext('2d'),clock=document.getElementById('clock');let timer=null;
const pts=frames.flatMap(f=>f.observations).filter(o=>o.track_id!==null&&o.surface_corridor_m).map(o=>o.surface_corridor_m);
const wall=D.walls.visible,far=D.walls.opposite, ys=pts.map(p=>p[1]).concat([0,...[wall,far].filter(Number.isFinite)]),xs=pts.map(p=>p[0]).concat([0]);
const xmin=Math.floor(Math.min(...xs)-0.5),xmax=Math.ceil(Math.max(...xs)+0.5),ymin=Math.floor(Math.min(...ys)-0.5),ymax=Math.ceil(Math.max(...ys)+0.5);
const scale=Math.min(980/(xmax-xmin||1),390/(ymax-ymin||1)),left=70,plotTop=30,px=x=>left+(x-xmin)*scale,py=y=>plotTop+(ymax-y)*scale,color=id=>`hsl(${(id*137)%360},85%,42%)`;
function plot(){m.clearRect(0,0,mc.width,mc.height);m.fillStyle='white';m.fillRect(0,0,mc.width,mc.height);m.font='14px sans-serif';m.lineWidth=1;
for(let x=Math.ceil(xmin);x<=xmax;x++){m.strokeStyle='#e1e6e9';m.beginPath();m.moveTo(px(x),py(ymin));m.lineTo(px(x),py(ymax));m.stroke();m.fillStyle='#334';m.fillText(x,px(x)-4,py(ymin)+20)}
for(let y=Math.ceil(ymin);y<=ymax;y++){m.strokeStyle='#e1e6e9';m.beginPath();m.moveTo(px(xmin),py(y));m.lineTo(px(xmax),py(y));m.stroke();m.fillStyle='#334';m.fillText(y,px(xmin)-25,py(y)+4)}
for(const [v,dashed] of [[wall,false],[far,true]])if(Number.isFinite(v)){m.strokeStyle='#344f60';m.lineWidth=2;m.setLineDash(dashed?[8,5]:[]);m.beginPath();m.moveTo(px(xmin),py(v));m.lineTo(px(xmax),py(v));m.stroke()}m.setLineDash([]);
m.fillStyle='#344f60';m.fillText('X →',px(xmax)-20,py(ymin)+38);m.fillText('Y ↑',5,plotTop+10);m.fillText('camera',px(0)+5,py(0)-7);m.beginPath();m.arc(px(0),py(0),4,0,7);m.fill();
const i=Number(s.value);for(let j=0;j<=i;j++)for(const o of frames[j].observations){const p=o.surface_corridor_m;if(o.track_id===null||!p)continue;m.fillStyle=color(o.track_id);if(j>0&&frames[j].frame_index===frames[j-1].frame_index+1&&frames[j].elapsed_s-frames[j-1].elapsed_s<=0.1){const q=frames[j-1].observations.find(x=>x.track_id===o.track_id&&x.surface_corridor_m);if(q){m.strokeStyle=color(o.track_id);m.lineWidth=2;m.setLineDash(o.identity_assignment==='proposed'||q.identity_assignment==='proposed'?[5,4]:[]);m.beginPath();m.moveTo(px(q.surface_corridor_m[0]),py(q.surface_corridor_m[1]));m.lineTo(px(p[0]),py(p[1]));m.stroke();m.setLineDash([])}}m.beginPath();m.arc(px(p[0]),py(p[1]),j===i?7:2,0,7);m.fill();if(o.identity_assignment==='proposed'){m.strokeStyle='#fff';m.lineWidth=1.5;m.stroke()}if(j===i){m.font='bold 16px sans-serif';m.fillText(`ID ${o.track_id}${o.identity_assignment==='proposed'?' (候補)':''}`,px(p[0])+8,py(p[1])-8)}}}
function render(){const i=Number(s.value),f=frames[i],im=new Image();
im.onload=()=>{if(Number(s.value)!==i)return;ic.width=im.width;ic.height=im.height;ix.drawImage(im,0,0);for(const o of f.observations){if(!o.region_bbox_xyxy)continue;const [x,y,x1,y1]=o.region_bbox_xyxy;ix.strokeStyle=o.track_id===null?'red':color(o.track_id);ix.fillStyle=ix.strokeStyle;ix.lineWidth=3;ix.strokeRect(x,y,x1-x,y1-y);ix.font='bold 24px sans-serif';ix.fillText(o.track_id===null?'ID ?':`ID ${o.track_id}${o.identity_assignment==='proposed'?' candidate':''}`,x,Math.max(24,y-5))}
clock.textContent=` ${f.elapsed_s.toFixed(3)}秒 / frame ${f.frame_index}`;document.getElementById('status').textContent=`検出 ${f.observations.length} 件 / 深度候補 ${f.observations.filter(o=>o.surface_corridor_m).length} 件`;document.getElementById('details').textContent=JSON.stringify(f.observations.map(o=>({ID:o.track_id,depth_status:o.depth_status,association:o.association_reason,corridor_XYZ_m:o.surface_corridor_m})),null,2);plot()};im.onerror=()=>{if(Number(s.value)===i)document.getElementById('status').textContent=`frame ${f.frame_index}: 画像を読み込めません`};im.src=f.review_image;}
function step(){const i=Number(s.value);if(i>=frames.length-1){timer=null;return}const speed=Number(document.getElementById('speed').value),delay=Math.max(1,1000*(frames[i+1].elapsed_s-frames[i].elapsed_s)/speed);timer=setTimeout(()=>{s.value=i+1;render();step()},delay)}
function stop(){clearTimeout(timer);timer=null}s.oninput=()=>{stop();render()};document.getElementById('play').onclick=()=>{if(!timer)step()};document.getElementById('pause').onclick=stop;document.getElementById('reset').onclick=()=>{stop();s.value=0;render()};render();</script></html>'''
    links = []
    for key, label in (('csv', '廊下座標を含むCSV'), ('tracking', '追跡結果JSON'), ('manifest', '出力の記録')):
        if data.get(key):
            links.append(f'<a href="{html.escape(data[key], quote=True)}">{label}</a>')
    notices = []
    if data.get('reassignment_candidate'):
        notices.append('<p><strong>再割当ては未確認の候補です。白縁の点・破線と candidate の表示が仮割当てを示します。</strong></p>')
    if data.get('spatial_filter'):
        notices.append('<p><strong>範囲外の座標・ID枠は除外しています。</strong>左の背景は解析時に保存した確認画像のため、除外前の輪郭や点が画像自体に残る場合があります。上面図と後から重ねたID枠が範囲適用後です。</p>')
    return (page.replace('__TITLE__', html.escape(title))
            .replace('__NOTICE__', ''.join(notices))
            .replace('__LINKS__', '<p>'+' / '.join(links)+'</p>' if links else '')
            .replace('__DATA__', payload))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tracking', type=Path, required=True)
    p.add_argument('--person-run', type=Path, required=True)
    p.add_argument('--calibration', type=Path, required=True)
    p.add_argument('--title', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('output already exists')
    root = a.tracking.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    person_manifest = a.person_run / 'manifest.json'
    if manifest.get('status') != 'complete' or manifest.get('source_manifest_sha256') != digest(person_manifest):
        raise ValueError('tracking source provenance mismatch')
    for name, expected in manifest['files_sha256'].items():
        if digest(safe_asset(root, name)) != expected:
            raise ValueError(f'tracking file hash mismatch: {name}')
    track = json.loads((root / 'tracking.json').read_text())
    person = json.loads((a.person_run / 'results.json').read_text())
    if digest(a.calibration) != person['metadata'].get('calibration_sha256'):
        raise ValueError('calibration differs from the one used for depth positions')
    if track['metadata'].get('source_svo_sha256') != person['metadata'].get('source_svo_sha256'):
        raise ValueError('SVO provenance mismatch')
    cal = json.loads(a.calibration.read_text())
    if cal.get('setup_id') != person['metadata'].get('setup_id'):
        raise ValueError('calibration setup mismatch')
    frames = track['frames']
    if not frames or any(not math.isfinite(float(f['elapsed_s'])) for f in frames):
        raise ValueError('missing frames or invalid times')
    if not any(o.get('surface_corridor_m') for f in frames for o in f['observations']):
        raise ValueError('no calibrated corridor positions')
    a.output.mkdir(parents=True, exist_ok=False)
    for f in frames:
        f['review_image'] = os.path.relpath(safe_asset(root, f['review_image']), a.output.resolve()).replace(os.sep, '/')
    rel = lambda name: os.path.relpath(root / name, a.output.resolve()).replace(os.sep, '/')
    data = {'frames': frames, 'walls': {'visible': cal.get('visible_wall_Y_m'),
            'opposite': cal.get('other_wall_inference', {}).get('opposite_wall_Y_m_assuming_same_boundaries')},
            'csv': rel('trajectories.csv'), 'tracking': rel('tracking.json'), 'manifest': 'manifest.json'}
    (a.output / 'index.html').write_text(make_page(data, a.title), encoding='utf-8')
    record = {'status': 'complete', 'source_tracking_manifest_sha256': digest(root/'manifest.json'),
              'source_person_manifest_sha256': digest(person_manifest), 'calibration_sha256': digest(a.calibration),
              'source_svo_sha256': track['metadata']['source_svo_sha256'], 'frame_count': len(frames),
              'script_sha256': digest(Path(__file__)), 'index_sha256': digest(a.output/'index.html'),
              'limits': ['visible surface, not body centre or foot position', 'provisional calibration and ID',
                         'linked source images are not copied']}
    (a.output/'manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(a.output/'index.html')


if __name__ == '__main__':
    main()
