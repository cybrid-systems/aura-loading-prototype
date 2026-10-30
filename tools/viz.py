#!/usr/bin/env python3
"""Render a kernel result JSON as a self-contained three.js HTML page (rotate / zoom / step through the loading sequence).

  python3 tools/viz.py result.json out.html [--title "..."]
three.js is loaded from a CDN; the cargo data is embedded in the page.
"""
import json, sys

TPL = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>body{margin:0;font:13px sans-serif;background:#111;color:#ddd}#ui{position:absolute;top:8px;left:8px;background:#000a;padding:8px 10px;border-radius:6px;max-width:460px}
input[type=range]{width:300px}.k{display:inline-block;width:10px;height:10px;margin:0 3px 0 8px}</style>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script></head>
<body><div id="ui"><b>__TITLE__</b><div id="m"></div>
<div>装载步骤 <input id="s" type="range" min="0" value="0"> <span id="sv"></span></div>
<div>颜色=卸货站点 <span id="leg"></span> · 红框=易碎 · 黄框=危险品</div></div>
<script type="module">
import * as THREE from 'three'; import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
const R = __DATA__;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x111111);
const cam = new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 10, 200000);
const ren = new THREE.WebGLRenderer({antialias:true}); ren.setSize(innerWidth, innerHeight); document.body.appendChild(ren.domElement);
const ctl = new OrbitControls(cam, ren.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.6)); const dl = new THREE.DirectionalLight(0xffffff, 0.9); dl.position.set(1,2,3).multiplyScalar(10000); scene.add(dl);
const pal = [0x4e79a7,0xf28e2b,0x59a14f,0xb07aa1,0x76b7b2,0xedc948,0xff9da7,0x9c755f];
const meshes = []; let oy = 0, maxL = 0;
R.containers.forEach((c, ci) => {
  const g = new THREE.Group(); g.position.set(0, 0, oy); scene.add(g);
  const cb = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(c.L, c.H, c.W)), new THREE.LineBasicMaterial({color:0xaaaaaa}));
  cb.position.set(c.L/2, c.H/2, c.W/2); g.add(cb);
  c.boxes.forEach(b => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(b.dx-8, b.dz-8, b.dy-8), new THREE.MeshLambertMaterial({color: pal[(b.stop-1+pal.length)%pal.length]}));
    m.position.set(b.x+b.dx/2, b.z+b.dz/2, b.y+b.dy/2); g.add(m); meshes.push([b.seq, m]);
    if (b.fragile || b.hazmat) { const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({color: b.hazmat?0xffff00:0xff0000})); m.add(e); }
  });
  oy += c.W + 1500; maxL = Math.max(maxL, c.L);
});
const M = R.metrics; document.getElementById('m').innerHTML =
  `箱数 ${M.boxes} · 柜 ${M.containers} (${M.mix}) · 体积利用率 ${(M.vol_util*100).toFixed(1)}% · 重量利用率 ${(M.wt_util*100).toFixed(1)}% · 相对运费 ${M.cost.toFixed(2)} · 下界 ${M.lower_bound} 柜` +
  R.containers.map((c,i)=>`<br>#${i+1} ${c.type}: 体积 ${(c.vol_util*100).toFixed(1)}% 重量 ${(c.kg).toFixed(0)}kg 重心 x=${c.cog[0].toFixed(2)} y=${c.cog[1].toFixed(2)} ${c.cog_ok?'✓':'✗'}`).join('');
const stops = [...new Set(R.containers.flatMap(c=>c.boxes.map(b=>b.stop)))].sort((a,b)=>a-b);
document.getElementById('leg').innerHTML = stops.map(s=>`<span class="k" style="background:#${pal[(s-1)%pal.length].toString(16).padStart(6,'0')}"></span>站${s}`).join('');
const S = document.getElementById('s'); S.max = meshes.length; S.value = meshes.length;
const upd = () => { const v = +S.value; meshes.forEach(([q,m]) => m.visible = q < v); document.getElementById('sv').textContent = `${v}/${meshes.length}`; };
S.oninput = upd; upd();
cam.position.set(maxL*0.5, oy*1.2+6000, oy*1.6+8000); ctl.target.set(maxL/2, 1000, oy/2); ctl.update();
addEventListener('resize', () => { cam.aspect = innerWidth/innerHeight; cam.updateProjectionMatrix(); ren.setSize(innerWidth, innerHeight); });
(function loop(){ requestAnimationFrame(loop); ren.render(scene, cam); })();
</script></body></html>"""


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    title = sys.argv[sys.argv.index("--title") + 1] if "--title" in sys.argv else "Aura 配仓方案"
    r = json.load(open(sys.argv[1], encoding="utf-8"))
    html = TPL.replace("__TITLE__", title).replace("__DATA__", json.dumps(r, ensure_ascii=False, separators=(",", ":")))
    open(sys.argv[2], "w", encoding="utf-8").write(html)
    print(f"wrote {sys.argv[2]}")


if __name__ == "__main__":
    main()
