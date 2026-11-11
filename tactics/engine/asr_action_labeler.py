#!/usr/bin/env python3
"""A-3：动作级标注工作台 —— 画面帧 + 人声原文，标签由老程人工给。

纪律：工具只做「定位 + 可视化」，**不输出任何战术判定**。
      段级真值 = 老程看着帧 + 读着解说原文裁定。

UI 铁律（沿用 build_human_labeler）：数字 26px 大字 + 「⤢全屏原图」。

用法：
    engine/asr_action_labeler.py            # 全 177 段
    engine/asr_action_labeler.py --limit 20 # 只出前 20 段
然后：
    cd action_work && python3 -m http.server 8791
    浏览器打开 http://127.0.0.1:8791/asr_action_labeler/index.html
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AW = ROOT / "action_work"
ANN = AW / "asr_segment_annotation.json"
SEGD = AW / "tactic_notes_batch_full" / "segments"
OUTD = AW / "asr_action_labeler"
LIB = AW / "tactic_library.json"


def sample_frames(seg_dir, k=5):
    """从既有 frames/ 里等距抽 k 帧（用现成产物，不重跑模型）。"""
    fd = seg_dir / "frames"
    if not fd.exists():
        return []
    fs = sorted(fd.glob("*.jpg")) + sorted(fd.glob("*.png"))
    if len(fs) <= k:
        return [str(p.relative_to(AW)) for p in fs]
    idx = [round(i * (len(fs) - 1) / (k - 1)) for i in range(k)]
    return [str(fs[i].relative_to(AW)) for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    ann = json.load(open(ANN, encoding="utf-8"))
    segs = ann["segments"]
    if a.limit:
        segs = segs[:a.limit]
    lib = json.load(open(LIB, encoding="utf-8"))
    tact_list = sorted(lib.get("tactics", {}).keys())

    OUTD.mkdir(parents=True, exist_ok=True)

    # 汇总控数据
    data = []
    for o in segs:
        sd = SEGD / o["seg"]
        fr = sample_frames(sd) if sd.exists() else []
        data.append({
            "seg": o["seg"], "video": o["video"], "t0": o["t0"], "t1": o["t1"],
            "narr": o["narration"], "cues": o["cues"],
            "eps": o["episode_tactics"], "frames": fr,
        })

    n_img = sum(1 for d in data if d["frames"])
    payload = json.dumps({"segs": data, "tactics": tact_list},
                         ensure_ascii=False)

    html = HTML.replace("__PAYLOAD__", payload)
    (OUTD / "index.html").write_text(html, encoding="utf-8")

    print(f"[A-3] 段 {len(data)} ｜ 有画面帧 {n_img} ｜ "
          f"战术候选 {len(tact_list)}")
    print(f"-> {OUTD/'index.html'}")
    print("    起服务： cd action_work && python3 -m http.server 8791")
    print("    打开： http://127.0.0.1:8791/asr_action_labeler/index.html")


HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>动作级战术标注（人声 x 画面）</title>
<style>
 body{background:#111;color:#eee;font:15px/1.6 -apple-system,"PingFang SC",sans-serif;margin:0}
 .bx{min-height:100vh;padding:24px 32px;border-bottom:1px solid #333}
 .hd{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
 .num{font-size:26px;font-weight:700;color:#ffd166}
 .tm{font-size:26px;color:#4cc9f0;font-weight:700}
 .vid{color:#999;font-size:13px;flex-basis:100%;margin-top:4px}
 .main{display:flex;gap:24px;margin-top:14px;flex-wrap:wrap}
 .lf{flex:1 1 620px;min-width:520px}
 .rt{flex:1 1 380px;min-width:340px}
 img{max-width:100%;border:1px solid #444;cursor:zoom-in;display:block}
 .ctr{display:flex;gap:10px;align-items:center;margin:10px 0;flex-wrap:wrap}
 button{background:#222;color:#eee;border:1px solid #555;border-radius:6px;
   padding:7px 13px;font-size:15px;cursor:pointer}
 button:hover{background:#333}
 select,input[type=text]{background:#1a1a1a;color:#eee;border:1px solid #555;
   border-radius:6px;padding:7px;font-size:15px}
 .narr{background:#181828;border-left:3px solid #4cc9f0;padding:12px 14px;
   font-size:19px;line-height:1.9;margin:10px 0}
 .cue{display:inline-block;background:#2a2a3d;border:1px solid #555;
   border-radius:5px;padding:3px 8px;margin:3px 4px 3px 0;font-size:14px}
 .cue b{color:#ffd166}
 .lb{margin-top:16px;padding-top:12px;border-top:1px dashed #444}
 .save{background:#0a5;border-color:#0a5;font-weight:700}
 .top{position:sticky;top:0;background:#111d;padding:10px 32px;
   border-bottom:1px solid #333;z-index:9;display:flex;gap:12px;align-items:center}
 progress{width:180px}
</style></head><body>
<div class="top">
 <b>动作级战术标注</b>
 <span id="prog" style="color:#ffd166;font-size:26px;font-weight:700">0/0</span>
 <progress id="bar" value="0" max="1"></progress>
 <button onclick="prev()">◀ 上一段</button>
 <button onclick="next()">下一段 ▶</button>
 <button class="save" onclick="exp()">导出标注 JSON</button>
 <span style="color:#888;font-size:13px">标签由人工裁定，工具不猜</span>
</div>
<div id="wrap"></div>
<script>
const D=__PAYLOAD__, L={}; let i=0;
function cur(){return D.segs[i]}
function render(){
 const s=cur();
 let opts='<option value="">—未定—</option>';
 D.tactics.forEach(t=>{opts+=`<option value="${t}">${t}</option>`});
 const cues=(s.cues||[]).map(c=>`<span class="cue"><b>${c.term}</b>
   ${c.mode}${c.score} @${c.t}s</span>`).join('');
 const frs=(s.frames||[]).map((f,n)=>`<img class="fm" data-n="${n}"
   src="../${f}" style="display:${n===0?'block':'none'}" onclick="zb(this)">`).join('');
 const nf=(s.frames||[]).length;
 document.getElementById('wrap').innerHTML=`<div class="bx">
  <div class="hd"><span class="num">${i+1}</span>
    <span class="tm">${s.t0}–${s.t1}s</span>
    <span style="color:#8f8">${s.seg}</span></div>
  <div class="vid">${s.video}${s.eps&&s.eps.length?
    ' ｜ 本期讲解：'+s.eps.join(','):''}</div>
  <div class="main"><div class="lf">${frs||'<i>（无画面帧）</i>'}
    <div class="ctr"><button onclick="fs(-1)">◀</button>
      <span id="fi" style="font-size:26px;color:#ffd166">1</span>
      <span style="color:#888">/${nf}</span>
      <button onclick="fs(1)">▶</button>
      <button onclick="zb(document.querySelector('.fm[style*=block]'))">⤢全屏原图</button></div>
    <div class="narr">${s.narr||'（窗口内无人声）'}</div>
    <div>${cues||'<span style="color:#777">无术语锚点</span>'}</div></div>
  <div class="rt"><div class="lb">
    <div style="color:#ffd166;font-weight:700;margin-bottom:8px">段级裁定</div>
    <div><b>是否确含战术？</b>
      <label><input type="radio" name="v${i}" value="是">是</label>
      <label><input type="radio" name="v${i}" value="否-简单配合">否·简单配合</label>
      <label><input type="radio" name="v${i}" value="否-无关">否·无关</label></div>
    <div style="margin-top:12px"><b>战术名：</b>
      <select id="sel${i}">${opts}</select></div>
    <div style="margin-top:12px"><b>自定义：</b>
      <input type="text" id="cus${i}" style="width:200px" placeholder="自由填写"></div>
    <div style="margin-top:12px"><b>备注：</b><br>
      <input type="text" id="rmk${i}" style="width:100%"></div>
  </div></div></div></div>`;
 const sv=L[s.seg]||{};
 if(sv.verdict)document.querySelector(`input[name=v${i}][value="${sv.verdict}"]`).checked=true;
 selv('sel'+i,sv.tactic); selv('cus'+i,sv.custom); selv('rmk'+i,sv.remark);
 document.getElementById('prog').textContent=(i+1)+'/'+D.segs.length;
 document.getElementById('bar').value=(i+1)/D.segs.length;
 window.scrollTo(0,0);
}
function selv(id,v){const e=document.getElementById(id);if(e&&v!==undefined)e.value=v}
function stash(){
 const s=cur(), v=document.querySelector(`input[name=v${i}]:checked`);
 L[s.seg]={seg:s.seg,video:s.video,t0:s.t0,t1:s.t1,narr:s.narr,
  verdict:v?v.value:'',tactic:(document.getElementById('sel'+i)||{}).value||'',
  custom:(document.getElementById('cus'+i)||{}).value||'',
  remark:(document.getElementById('rmk'+i)||{}).value||''};
 up();
}
function up(){const n=Object.keys(L).length;
 document.getElementById('prog').textContent=(i+1)+'/'+D.segs.length;
 document.getElementById('prog').style.color=n?'#0a5':'#ffd166'}
function prev(){stash();if(i>0)i--;render()}
function next(){stash();if(i<D.segs.length-1){i++}render()}
function fs(d){
 const im=[...document.querySelectorAll('.fm')];if(!im.length)return;
 let c=im.findIndex(x=>x.style.display==='block');if(c<0)c=0;
 c=Math.max(0,Math.min(im.length-1,c+d));
 im.forEach((x,n)=>x.style.display=(n===c?'block':'none'));
 document.getElementById('fi').textContent=c+1;
}
function zb(img){if(!img)return;
 const w=window.open('','_blank');
 w.document.write(`<title>原图</title><body style="margin:0;background:#000">
  <img src="${img.src}" style="width:100%"></body>`);}
function exp(){stash();
 const b=new Blob([JSON.stringify(Object.values(L),null,1)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(b);
 a.download='action_labels.json';a.click();}
document.addEventListener('keydown',e=>{
 if(e.key==='ArrowRight')next();if(e.key==='ArrowLeft')prev();});
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
