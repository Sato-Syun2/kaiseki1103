"""Generate SDK 2D body replay at saved image timestamps in camera coordinates."""
import argparse
import csv
import html
import json
import os
from pathlib import Path

from body.compare_sdk_stability import BONES, digest, load, point


def make_page(frames, title, source):
    data=json.dumps({'frames':frames},ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>SDK骨格再生</title>
<style>body{font:16px system-ui,sans-serif;margin:24px;color:#203040}canvas{display:block;max-width:100%;height:auto;border:1px solid #bbb}input[type=range]{width:min(100%,900px)}button,label{margin:6px}pre{white-space:pre-wrap}</style>
<h1>TITLE SDK骨格再生</h1><p>元SVO: SOURCE</p>
<p>元画像と同じ時刻に出たSDKの主要な骨格線。画像は約0.1秒間隔で、画像間のフレームは表示していません。IDや骨格はSDKの推定で、正確さを保証しません。以前の設置の廊下校正は使用していません。</p>
<label>画像の時刻 <input type="range" id="slider" min="0" value="0"><span id="clock"></span></label><br>
<button id="play">再生</button><button id="stop">停止</button><label><input id="bones" type="checkbox" checked>骨格を表示</label><label><input id="allStates" type="checkbox">OK以外も表示</label>
<canvas id="view"></canvas><p id="status"></p><pre id="detail"></pre>
<script type="application/json" id="data">PAYLOAD</script><script>
const D=JSON.parse(document.getElementById('data').textContent), F=D.frames;
const slider=document.getElementById('slider'),canvas=document.getElementById('view'),ctx=canvas.getContext('2d');slider.max=F.length-1;let timer=null;
const bones=BONES;const colour=id=>`hsl(${(id*137+30)%360},85%,50%)`;
function render(){const i=Number(slider.value),f=F[i],im=new Image();document.getElementById('clock').textContent=` ${f.elapsed_s.toFixed(3)} 秒 / frame ${f.frame_index}`;
document.getElementById('status').textContent=`SDK検出 ${f.bodies.length} 件（この画像時刻）`;document.getElementById('detail').textContent=JSON.stringify(f.bodies.map(x=>({sdk_id:x.id,state:x.state,confidence:x.confidence})),null,2);
im.onload=()=>{if(Number(slider.value)!==i)return;canvas.width=im.width;canvas.height=im.height;ctx.drawImage(im,0,0);if(!document.getElementById('bones').checked)return;
for(const b of f.bodies){if(!document.getElementById('allStates').checked&&b.state!=='OK')continue;ctx.strokeStyle=colour(b.id);ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=4;
for(const [a,c] of bones){const p=b.pixels[a],q=b.pixels[c],ca=b.conf[a],cc=b.conf[c];if(!Array.isArray(p)||!Array.isArray(q)||!p.every(Number.isFinite)||!q.every(Number.isFinite)||!Number.isFinite(ca)||!Number.isFinite(cc)||ca<20||cc<20)continue;ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();}
const p=b.pixels[0];if(Array.isArray(p)&&p.every(Number.isFinite)){ctx.font='bold 28px sans-serif';ctx.fillText(`SDK ${b.id} ${b.state}`,p[0]+8,p[1]-8)}}};im.src=f.image;}
function step(){const i=Number(slider.value);if(i>=F.length-1){timer=null;return}const delay=Math.max(1,1000*(F[i+1].elapsed_s-F[i].elapsed_s));timer=setTimeout(()=>{slider.value=i+1;render();step()},delay)}
slider.oninput=render;document.getElementById('bones').onchange=render;document.getElementById('allStates').onchange=render;document.getElementById('play').onclick=()=>{if(!timer)step()};document.getElementById('stop').onclick=()=>{clearTimeout(timer);timer=null};render();</script></html>'''.replace('TITLE',html.escape(title)).replace('SOURCE',html.escape(source)).replace('PAYLOAD',data).replace('BONES',json.dumps(BONES))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--setup-id',required=True)
    a=p.parse_args()
    if a.output.exists():p.error('output already exists')
    sources=sorted(a.input_root.glob('recording_*/body'))
    if not sources:p.error('no BODY exports found')
    inv={}; ip=a.input_root/'input_inventory.csv'
    if ip.is_file():
        with ip.open(newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['recording'] in inv:raise ValueError('duplicate inventory entry')
                inv[row['recording']]=row['source_relative_path']
    a.output.mkdir(parents=True,exist_ok=False);records=[];failures=[];seen=set()
    for body in sources:
        name=body.parent.name
        try:
            d=load(body);camera=d['camera'];source_hash=camera.get('source_svo_sha256')
            if camera.get('setup_id')!=a.setup_id or not source_hash or source_hash in seen:
                raise ValueError('setup mismatch, missing hash or duplicate SVO')
            seen.add(source_hash);dest=a.output/name;dest.mkdir();frames=[]
            for frame in d['frames']:
                if not frame.get('image_file'):continue
                index=int(frame['frame_index']);path=(body/frame['image_file']).resolve()
                if not path.is_file() or not path.is_relative_to(body.resolve()):raise ValueError('unsafe/missing image')
                image=os.path.relpath(path,dest.resolve()).replace(os.sep,'/')
                bodies=[]
                for r in d['bodies'].get(index,[]):
                    bodies.append({'id':r['id'],'state':r['tracking_state'],'confidence':float(r['confidence']),
                                   'pixels':r['pixels'],'conf':r['conf']})
                frames.append({'frame_index':index,'elapsed_s':float(frame['elapsed_s']),
                               'timestamp_ns':frame['image_timestamp_ns'],'image':image,'bodies':bodies})
            if not frames:raise ValueError('no saved images')
            source=inv.get(name,'入力一覧を確認してください')
            (dest/'index.html').write_text(make_page(frames,name,source),encoding='utf-8')
            records.append({'recording':name,'source_relative_path':source,'source_svo_sha256':source_hash,
                            'body_manifest_sha256':digest(body/'manifest.json'),'saved_images':len(frames),'page':f'{name}/index.html'})
            print(name,len(frames),'images',flush=True)
        except Exception as e:
            failures.append({'recording':name,'error':str(e)});print(name,'FAILED',e,flush=True)
    links=''.join('<li><a href="'+html.escape(r['page'])+'">'+html.escape(r['recording'])+'</a>　'+html.escape(r['source_relative_path'])+'（'+str(r['saved_images'])+'画像）</li>' for r in records)
    page='<!doctype html><html lang="ja"><meta charset="utf-8"><title>グループ4 SDK骨格再生</title><style>body{font:16px system-ui;margin:24px}li{margin:8px 0}</style><h1>SDK骨格再生一覧</h1><p>画像は約0.1秒ごと。SDK IDと骨格は推定であり、正確さを保証しません。カメラ座標での確認です。</p><ul>'+links+'</ul><p>失敗 '+str(len(failures))+' 件。<a href="manifest.json">記録・エラー</a></p></html>'
    (a.output/'index.html').write_text(page,encoding='utf-8')
    outputs={str(x.relative_to(a.output)):digest(x) for x in a.output.rglob('*') if x.is_file()}
    manifest={'status':'complete' if not failures else 'incomplete','setup_id':a.setup_id,
              'script_sha256':digest(Path(__file__)),'records':records,'failures':failures,'file_hashes':outputs,
              'image_policy':'relative links to validated source export; source images are not copied'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('replay index:',a.output/'index.html')
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
