#!/usr/bin/env python3
"""Build a local group/trial viewer from the already generated tracking results."""
from pathlib import Path
import json
import os
import re

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'results/tracking_replay_gallery_20261104'
SOURCES={'1':'goal_a_20261104_02','2':'group002_20261104_analysis_01','3':'group003_20261104_analysis_01'}
template=(ROOT/'body/corridor_tracking/replay_template.html').read_text(encoding='utf-8')
template=template.replace('<option value="candidate">改善候補</option><option value="baseline">旧処理</option>', '<option value="baseline" selected>SDK元ID（従来表示）</option><option value="candidate">追跡候補（未採用）</option>')
template=template.replace('<label><input type="checkbox" id="bones" checked>骨格</label>', '<label><input type="checkbox" id="bones" checked>骨格</label><label><input type="checkbox" id="showRejected">未採用の骨格も表示</label>')
template=template.replace('<input type="range" id="slider"', '<label><input type="checkbox" id="jumpGuard" checked>急激な飛びを保留（試験中）</label><span id="jumpInfo"></span><input type="range" id="slider"')
template=template.replace('const anchored=new Map(', 'const baselineMap=new Map(D.baseline.map(p=>[p.obs_id,p]));\nconst anchored=new Map(')
template=template.replace("function selected(){", '''const jumpFlag=new Set(),tracksBySdk=new Map();
for(const p of D.baseline){if(!p.xyz||p.track_id===null)continue;if(!tracksBySdk.has(p.sdk_id))tracksBySdk.set(p.sdk_id,[]);tracksBySdk.get(p.sdk_id).push(p)}
const dist3=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
for(const track of tracksBySdk.values()){track.sort((a,b)=>a.t-b.t);for(let i=1;i<track.length-1;i++){
 const [a,b,c]=track.slice(i-1,i+2),dt1=b.t-a.t,dt2=c.t-b.t;
 if(!(dt1>0&&dt1<=.15&&dt2>0&&dt2<=.15&&frameOrder.get(b.frame_index)-frameOrder.get(a.frame_index)===1&&frameOrder.get(c.frame_index)-frameOrder.get(b.frame_index)===1))continue;
 const d1=dist3(a.xyz,b.xyz),d2=dist3(b.xyz,c.xyz),back=dist3(a.xyz,c.xyz);
 if(d1>.75&&d2>.75&&d1/dt1>6&&d2/dt2>6&&back<.5+4*(dt1+dt2))jumpFlag.add(b.obs_id)
}}
$('jumpInfo').textContent=`保留候補 ${jumpFlag.size} 観測（自動判定・要確認）`;
function jumpSegment(a,b){const dt=b.t-a.t;return $('jumpGuard').checked&&dt>0&&dist3(a.xyz,b.xyz)>.75&&dist3(a.xyz,b.xyz)/dt>6}
function selected(){''')
template=template.replace("return p.filter(p=>p.xyz&&p.track_id!==null)", "return p.filter(p=>p.xyz&&p.track_id!==null&&(!$('jumpGuard').checked||!jumpFlag.has(p.obs_id)))")
template=template.replace("&&p.t>prev.t&&adjacent){", "&&p.t>prev.t&&adjacent&&!jumpSegment(prev,p)){")
template=template.replace('function drawImage(){', '''function selectedDecision(o){return ($('mode').value==='baseline'?baselineMap:$('mode').value==='anchored'?anchored:candidate).get(o.obs_id)}
function showSkeleton(o){const p=selectedDecision(o);if($('jumpGuard').checked&&jumpFlag.has(o.obs_id))return false;return $('showRejected').checked || (o.state==='OK' && p && p.track_id!==null && p.xyz && ['sdk_estimate','partial_observation_estimate'].includes(p.position_source))}
function drawImage(){''')
template=template.replace("for(const o of raw.get(images[imageIndex].frame_index)||[]){const p=", "for(const o of raw.get(images[imageIndex].frame_index)||[]){if(o.kind!=='body'||!showSkeleton(o))continue;const p=")
template=template.replace("for(const id of ['mode','derived','bones'])", "for(const id of ['mode','derived','bones','showRejected','jumpGuard'])")
scene_html='''<section><h2>3D空間の骨格と軌跡</h2><label>視点の回転 <input id="angle3d" type="range" min="-180" max="180" value="-30"></label><canvas id="scene3d" width="1100" height="570"></canvas><p>骨格はSDKの推定値です。初期状態では選択方式が位置を採用した観測のみ表示します。未採用の骨格は上のチェックで確認できます。位置と骨格は正解を保証せず、校正は暫定値です。</p></section>'''
scene_js=r'''
function drawScene3d(){
 const c=$('scene3d'),ctx=c.getContext('2d'),W=c.width,H=c.height,pts=selected();ctx.clearRect(0,0,W,H);
 const good=p=>Array.isArray(p)&&p.length===3&&p.every(Number.isFinite);
 const cur=D.frames[nearest(D.frames,time)];const bodies=(raw.get(cur.frame_index)||[]).filter(o=>o.kind==='body'&&showSkeleton(o));
 const positions=pts.map(p=>p.xyz).filter(good),xs=positions.map(p=>p[0]).sort((a,b)=>a-b),ys=positions.map(p=>p[1]).sort((a,b)=>a-b);
 const percentile=(v,q,fallback)=>v.length?v[Math.floor((v.length-1)*q)]:fallback;
 const xmin=Math.min(-.5,percentile(xs,.005,-.5)-.5),xmax=Math.max(16,percentile(xs,.995,16)+.5),ymin=Math.min(-.5,percentile(ys,.005,-.5)-.5),ymax=Math.max(2.5,percentile(ys,.995,2.5)+.5),zmin=-1,zmax=3;
 const a=Number($('angle3d').value)*Math.PI/180,cs=Math.cos(a),sn=Math.sin(a),cx=(xmin+xmax)/2,cy=(ymin+ymax)/2;
 const proj=p=>{let x=p[0]-cx,y=p[1]-cy;return [cs*x-sn*y, .35*(sn*x+cs*y)-p[2]]};
 const corners=[];for(const x of [xmin,xmax])for(const y of [ymin,ymax])for(const z of [zmin,zmax])corners.push(proj([x,y,z]));
 const left=Math.min(...corners.map(p=>p[0])),right=Math.max(...corners.map(p=>p[0])),top=Math.min(...corners.map(p=>p[1])),bottom=Math.max(...corners.map(p=>p[1]));
 const scale=Math.min((W-100)/Math.max(1,right-left),(H-100)/Math.max(1,bottom-top));
 const P=p=>{let q=proj(p);return [W/2+(q[0]-(left+right)/2)*scale,H/2+(q[1]-(top+bottom)/2)*scale]};
 const line=(p,q,col,width=1,dash=[])=>{ctx.strokeStyle=col;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.beginPath();ctx.moveTo(...P(p));ctx.lineTo(...P(q));ctx.stroke();ctx.setLineDash([])};
 const floor=[[xmin,ymin,0],[xmax,ymin,0],[xmax,ymax,0],[xmin,ymax,0]].map(P);ctx.fillStyle='#e5eef3';ctx.beginPath();ctx.moveTo(...floor[0]);floor.slice(1).forEach(p=>ctx.lineTo(...p));ctx.closePath();ctx.fill();
 const step=Math.max(1,Math.ceil((xmax-xmin)/16));for(let x=Math.ceil(xmin/step)*step;x<=xmax;x+=step)line([x,ymin,0],[x,ymax,0],'#b9cbd7');
 for(const y of [ymin,ymax])line([xmin,y,0],[xmax,y,0],'#8da6b6',2);
 const by=new Map();for(const p of pts){if(p.t>time||!good(p.xyz))continue;if(!by.has(p.track_id))by.set(p.track_id,[]);by.get(p.track_id).push(p)}
 for(const [id,arr] of by){arr.sort((a,b)=>a.t-b.t);let prev=null;for(const p of arr){if(prev&&p.t>prev.t&&p.t-prev.t<=.4&&frameOrder.get(p.frame_index)-frameOrder.get(prev.frame_index)===1&&!jumpSegment(prev,p)){const dash=[p.position_source,prev.position_source].some(s=>['interpolated','predicted'].includes(s))?[8,5]:[];line([prev.xyz[0],prev.xyz[1],0],[p.xyz[0],p.xyz[1],0],color(id),3,dash)}prev=p}}
 if($('bones').checked)for(const o of bodies){const match=($('mode').value==='anchored'?anchored:candidate).get(o.obs_id);const id=$('mode').value==='baseline'?'sdk:'+o.sdk_id:match?.track_id;const col=id==null?'#888':color(id);
 for(const [i,j] of bones)if(good(o.joints[i])&&good(o.joints[j])&&o.joint_confidence[i]>=20&&o.joint_confidence[j]>=20)line(o.joints[i],o.joints[j],col,4);
 const root=[0,2,26].map(k=>o.joints[k]).find(good);if(root){const q=P(root);ctx.fillStyle=col;ctx.font='bold 15px sans-serif';ctx.fillText(id==null?'未確定':`解析 ${id} / SDK ${o.sdk_id}`,q[0]+7,q[1]-7)}}
 ctx.fillStyle='#365464';ctx.font='14px sans-serif';ctx.fillText(`X: 廊下奥 [m]　 Y: 横 [m]　 Z: 高さ [m]　人物データ ${cur.t.toFixed(3)} 秒`,18,25);
}
$('angle3d').oninput=()=>drawScene3d();
'''
assert template.count('<section><h2>現在の推定と対応根拠</h2>')==1
assert template.count('function render(){')==1 and template.count('drawPlan()}')==1
template=template.replace('<section><h2>現在の推定と対応根拠</h2>',scene_html+'\n<section><h2>現在の推定と対応根拠</h2>')
template=template.replace('function render(){',scene_js+'\nfunction render(){').replace('drawPlan()}','drawPlan();drawScene3d()}')
OUT.mkdir(parents=True,exist_ok=True)
manifest={}
for group,source in SOURCES.items():
 manifest[group]=[]
 for original in sorted((ROOT/'results/tracking_v2'/source).glob('recording_*/index.html')):
  rec=original.parent.name
  raw=original.read_text(encoding='utf-8')
  match=re.search(r'<script id="data" type="application/json">(.*?)</script>',raw,re.S)
  if not match: raise ValueError(f'Missing data in {original}')
  data=json.loads(match.group(1));assert data['frames'] and any(f.get('image') for f in data['frames'])
  dest=OUT/f'group_{group}'/rec;dest.mkdir(parents=True,exist_ok=True)
  base=os.path.relpath(original.parent,dest).replace(os.sep,'/')+'/'
  page=template.replace('<title>','<base href="'+base+'"><title>',1).replace('__DATA__',match.group(1))
  (dest/'index.html').write_text(page,encoding='utf-8')
  manifest[group].append({'recording':rec,'page':f'group_{group}/{rec}/index.html'})
page='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>歩行解析 再生</title><style>body{margin:0;background:#edf3f7;color:#19364b;font:15px system-ui,sans-serif}header{padding:16px 24px;background:white;box-shadow:0 2px 8px #19364b22}h1{font-size:22px;margin:0 0 10px}label{margin-right:18px}select,a{font:inherit;padding:6px}p{margin:10px 0;line-height:1.6}iframe{display:block;border:0;width:100%;height:2050px;background:#edf3f7}</style><header><h1>歩行解析の再生</h1><label>グループ <select id="group"></select></label><label>試行番号 <select id="trial"></select></label><a id="direct" target="_blank" rel="noopener">別タブで開く</a><p>グループ1: 48試行、グループ2: 55試行、グループ3: 54試行。SDK元IDを初期表示します。追跡候補はID分断が多く未採用です。SDKも人物の正解ではなく、位置と骨格の校正は検証中です。</p></header><iframe id="viewer" title="選択した試行の再生"></iframe><script>const data=__MANIFEST__,g=document.getElementById('group'),t=document.getElementById('trial'),v=document.getElementById('viewer'),d=document.getElementById('direct');for(const k of Object.keys(data)){let o=new Option('グループ '+k,k);g.add(o)}function openTrial(){const item=data[g.value].find(x=>x.recording===t.value);if(item){v.src=item.page;d.href=item.page}}function groupChanged(){const previous=t.value;t.replaceChildren();for(const x of data[g.value])t.add(new Option('試行 '+x.recording.split('_')[1],x.recording));if(data[g.value].some(x=>x.recording===previous))t.value=previous;openTrial()}g.onchange=groupChanged;t.onchange=openTrial;groupChanged();</script></html>'''
(OUT/'index.html').write_text(page.replace('__MANIFEST__',json.dumps(manifest,ensure_ascii=False)),encoding='utf-8')
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('出力:',OUT/'index.html','件数:',{k:len(v) for k,v in manifest.items()})
