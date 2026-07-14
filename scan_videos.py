#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描 /Volumes/12T/NBA/比赛录像 下所有视频，提取:
  - 文件名自身的日期 (英文月/中文月/数字 YYYY_MM_DD 等)
  - 阶段 (从父目录名: 常规赛经典/季后赛/总决赛/全明星/夏联/季前赛)
  - 最佳球队 (vs / @ 两侧)
  - 相对路径
无"月+日"的文件 -> undated，列出供人工确认 (不放到日历)。
输出:
  - video_index.json
  - calendar.html (自包含, 内嵌数据)
"""
import os, re, json, sys
from datetime import datetime, date

ROOT = "/Volumes/12T/NBA/比赛录像"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm"}

MONTHS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"sept":9,"oct":10,"nov":11,"dec":12,
}
MONTHS_CN = ["一","二","三","四","五","六","七","八","九","十","十一","十二"]

STAGE_MAP = {
    "常规赛经典":"常规赛","常规赛":"常规赛","季后赛":"季后赛","总决赛":"总决赛",
    "全明星":"全明星","夏联":"夏联","季前赛":"季前赛",
}
STAGE_KEY = {"常规赛":"rs","季后赛":"po","总决赛":"fin","全明星":"as","夏联":"sl","季前赛":"pre"}

# ---------- 日期解析 ----------
def parse_date(name):
    """返回 (y,m,d) 或 None。要求至少有 月+日。"""
    s = name
    # 1) 数字 YYYY[_.\-]MM[_.\-]DD
    m = re.search(r'(19|20)\d{2}[._\-](\d{1,2})[._\-](\d{1,2})', s)
    if m:
        y=int(m.group(0)[:4]); mo=int(m.group(2)); d=int(m.group(3))
        if 1<=mo<=12 and 1<=d<=31: return (y,mo,d)
    # 2) 数字 MM[_.\-]DD[_.\-]YYYY
    m = re.search(r'(\d{1,2})[._\-](\d{1,2})[._\-](19|20)\d{2}', s)
    if m:
        mo=int(m.group(1)); d=int(m.group(2)); y=int(m.group(3))
        if 1<=mo<=12 and 1<=d<=31: return (y,mo,d)
    # 3) 英文月 名 + 日 [, ] 年
    m = re.search(r'([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(19|20)\d{2}', s, re.IGNORECASE)
    if m:
        mn = m.group(1).lower()
        if mn in MONTHS_EN:
            mo=MONTHS_EN[mn]; d=int(m.group(2)); y=int(m.group(3))
            if 1<=d<=31: return (y,mo,d)
    # 4) 中文 年?月日
    m = re.search(r'((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?', s)
    if m:
        y=int(m.group(1)); mo=int(m.group(2)); d=int(m.group(3))
        if 1<=mo<=12 and 1<=d<=31: return (y,mo,d)
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', s)
    if m:
        mo=int(m.group(1)); d=int(m.group(2))
        # 年需另寻
        ym = re.search(r'((?:19|20)\d{2})', s)
        if ym and 1<=mo<=12 and 1<=d<=31:
            return (int(ym.group(1)),mo,d)
    return None

def hint_year(name):
    m = re.search(r'((?:19|20)\d{2})', name)
    if m and parse_date(name) is None:
        return int(m.group(1))
    return None

# ---------- 球队最佳提取 ----------
def parse_teams(title):
    # 去掉常见前缀词
    t = re.sub(r'^Full Game[_：:]?\s*', '', title, flags=re.IGNORECASE)
    m = re.search(r'([A-Za-z][\w &\.\'\-]{1,32}?)\s+(?:vs\.?|@)\s+([A-Za-z][\w &\.\'\-]{1,32}?)', t)
    if m:
        a = m.group(1).strip().strip('_').strip()
        b = m.group(2).strip().strip('_').strip()
        # 截断到 vs/@ 之前的短语, 去掉尾部多余标点
        a = a.split('(')[0].strip()
        b = b.split('(')[0].strip()
        if a and b and len(a)<30 and len(b)<30:
            return [a, b]
    return None

def stage_of(dirname):
    for k,v in STAGE_MAP.items():
        if k in dirname:
            return v
    return dirname

# ---------- 扫描 ----------
def scan():
    videos=[]; undated=[]
    for cur,_,files in os.walk(ROOT):
        # 阶段取 比赛录像/{年}/{阶段}/ 这一层
        rel = os.path.relpath(cur, ROOT)
        parts = rel.split(os.sep)
        stage = stage_of(parts[1]) if len(parts)>1 else ""
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in VIDEO_EXT: continue
            title = os.path.splitext(f)[0]
            d = parse_date(title)
            path = ("比赛录像/" + rel + "/" + f) if rel!="." else ("比赛录像/" + f)
            teams = parse_teams(title)
            if d:
                y,mo,day = d
                videos.append({
                    "title":title,
                    "date":"%04d-%02d-%02d"%(y,mo,day),
                    "year":y,"month":mo,"day":day,
                    "stage":stage,"stageKey":STAGE_KEY.get(stage,"other"),
                    "teams":teams,
                    "path":path,
                })
            else:
                undated.append({
                    "title":title,
                    "path":path,
                    "stage":stage,
                    "hintYear":hint_year(title),
                })
    videos.sort(key=lambda x:(x["date"], x["path"]))
    undated.sort(key=lambda x:(x["hintYear"] or 0, x["path"]))
    return videos, undated

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA 录像库日历</title>
<style>
:root{
  --bg:#0e1116; --panel:#161b22; --panel2:#1c232c; --line:#2a323c;
  --txt:#e6edf3; --muted:#8b949e; --accent:#58a6ff;
  --rs:#3fb950; --po:#d29922; --fin:#f85149; --as:#bc8cff; --sl:#39c5cf; --pre:#8b949e; --other:#6e7681;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;}
a{color:var(--accent);text-decoration:none}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:12px;align-items:center;position:sticky;top:0;background:var(--bg);z-index:10}
h1{font-size:16px;margin:0;font-weight:600}
.nav button{background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:6px;padding:5px 11px;cursor:pointer;font-size:13px}
.nav button:hover{border-color:var(--accent)}
#monthLabel{font-size:15px;font-weight:600;min-width:140px;text-align:center}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:3px 11px;cursor:pointer;font-size:12px;color:var(--muted)}
.chip.on{color:#fff;border-color:transparent}
.chip[data-k="rs"].on{background:var(--rs)} .chip[data-k="po"].on{background:var(--po)}
.chip[data-k="fin"].on{background:var(--fin)} .chip[data-k="as"].on{background:var(--as)}
.chip[data-k="sl"].on{background:var(--sl)} .chip[data-k="pre"].on{background:var(--pre)}
.chip[data-k="all"].on{background:var(--accent)}
#search{background:var(--panel);border:1px solid var(--line);border-radius:6px;color:var(--txt);padding:6px 10px;font-size:13px;min-width:180px}
#search:focus{outline:none;border-color:var(--accent)}
main{display:flex;gap:0;align-items:flex-start}
#calWrap{flex:1;padding:14px 18px;min-width:0}
#cal{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.dow{text-align:center;color:var(--muted);font-size:12px;padding:4px 0;border-bottom:1px solid var(--line)}
.cell{min-height:78px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 6px;cursor:pointer;overflow:hidden;transition:.12s}
.cell:hover{border-color:var(--accent)}
.cell.empty{background:transparent;border:none;cursor:default}
.cell.today{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.dnum{font-size:12px;color:var(--muted)}
.cell.today .dnum{color:var(--accent);font-weight:700}
.dots{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.dot{width:7px;height:7px;border-radius:50%}
.dot.rs{background:var(--rs)} .dot.po{background:var(--po)} .dot.fin{background:var(--fin)}
.dot.as{background:var(--as)} .dot.sl{background:var(--sl)} .dot.pre{background:var(--pre)} .dot.other{background:var(--other)}
.cnt{font-size:11px;color:var(--muted);margin-top:2px}
#side{width:340px;flex:none;border-left:1px solid var(--line);min-height:calc(100vh - 57px);padding:14px 16px;position:sticky;top:57px}
#side h2{font-size:14px;margin:0 0 10px}
.vitem{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin-bottom:8px}
.vitem .vt{font-size:13px;font-weight:600;line-height:1.35}
.vitem .vm{font-size:11px;color:var(--muted);margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.badge{font-size:10px;padding:1px 7px;border-radius:10px;color:#0e1116;font-weight:700}
.badge.rs{background:var(--rs)} .badge.po{background:var(--po)} .badge.fin{background:var(--fin)}
.badge.as{background:var(--as)} .badge.sl{background:var(--sl)} .badge.pre{background:var(--pre)} .badge.other{background:var(--other)}
.vitem a.open{font-size:11px}
#undated{margin-top:18px}
#undated summary{cursor:pointer;color:var(--muted);font-size:12px}
#undated .vitem{opacity:.85}
.empty-note{color:var(--muted);font-size:12px;padding:20px;text-align:center}
.kbd{font:11px monospace;background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;color:var(--muted)}
footer{color:var(--muted);font-size:11px;padding:8px 18px;border-top:1px solid var(--line)}
</style>
</head>
<body>
<header>
  <h1>🏀 NBA 录像库日历</h1>
  <div class="nav">
    <button id="prevY">« 年</button>
    <button id="prevM">‹ 月</button>
    <span id="monthLabel"></span>
    <button id="nextM">月 ›</button>
    <button id="nextY">年 »</button>
    <button id="todayBtn">今天</button>
  </div>
  <div class="chips" id="chips">
    <span class="chip on" data-k="all">全部</span>
    <span class="chip" data-k="rs">常规赛</span>
    <span class="chip" data-k="po">季后赛</span>
    <span class="chip" data-k="fin">总决赛</span>
    <span class="chip" data-k="as">全明星</span>
    <span class="chip" data-k="sl">夏联</span>
    <span class="chip" data-k="pre">季前赛</span>
  </div>
  <input id="search" placeholder="搜索球队/关键词  ( / 聚焦 )">
</header>
<main>
  <div id="calWrap"><div id="cal"></div>
    <div id="undated">
      <details>
        <summary id="undSummary"></summary>
        <div id="undList"></div>
      </details>
    </div>
  </div>
  <aside id="side"><h2 id="sideTitle">点击日期查看录像</h2><video id="player" controls preload="none" style="display:none;width:100%;border-radius:8px;background:#000;margin-bottom:10px;"></video><div id="sideBody"><div class="empty-note">← 选择一个有录像的日期</div></div></aside>
</main>
<footer>
  数据来自 /Volumes/12T/NBA/比赛录像 · 日期以文件名解析为准 · 无月/日文件已单列待人工确认 ·
  快捷键: <span class="kbd">← →</span> 切换月 · <span class="kbd">↑ ↓</span> 切换年 · <span class="kbd">/</span> 搜索 · <span class="kbd">Esc</span> 返回
</footer>
<script>
const DATA = __DATA__;
const STAGE_NAME = {rs:"常规赛",po:"季后赛",fin:"总决赛",as:"全明星",sl:"夏联",pre:"季前赛",other:"其他"};
const MONTHS = ["一月","二月","三月","四月","五月","六月","七月","八月","九月","十月","十一月","十二月"];
const DOW = ["一","二","三","四","五","六","日"];
let viewY, viewM; // M: 1-12
let activeFilter = "all";
let searchQ = "";

// 建索引: date -> [videos]
const byDate = {};
for (const v of DATA.videos){ (byDate[v.date] = byDate[v.date]||[]).push(v); }

function passFilter(v){
  if (activeFilter!=="all" && v.stageKey!==activeFilter) return false;
  if (searchQ){
    const q = searchQ.toLowerCase();
    const hay = ((v.teams||[]).join(" ")+" "+v.title+" "+(v.stage||"")).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}
function countFor(dateStr){
  const arr = byDate[dateStr]||[];
  return arr.filter(passFilter).length;
}
function dotsFor(dateStr){
  const arr = (byDate[dateStr]||[]).filter(passFilter);
  const seen={}; const out=[];
  for (const v of arr){ if(!seen[v.stageKey]){seen[v.stageKey]=1; out.push(v.stageKey);} }
  return out;
}
function renderCal(){
  const cal = document.getElementById("cal");
  cal.innerHTML="";
  for (const d of DOW){ const e=document.createElement("div"); e.className="dow"; e.textContent=d; cal.appendChild(e); }
  const first = new Date(viewY, viewM-1, 1);
  let lead = (first.getDay()+6)%7; // 周一为0
  for (let i=0;i<lead;i++){ const c=document.createElement("div"); c.className="cell empty"; cal.appendChild(c); }
  const days = new Date(viewY, viewM, 0).getDate();
  const today = new Date();
  const tStr = today.getFullYear()+"-"+String(today.getMonth()+1).padStart(2,"0")+"-"+String(today.getDate()).padStart(2,"0");
  for (let d=1; d<=days; d++){
    const ds = viewY+"-"+String(viewM).padStart(2,"0")+"-"+String(d).padStart(2,"0");
    const c = document.createElement("div");
    c.className="cell"+(ds===tStr?" today":"");
    const n = countFor(ds);
    let html = '<div class="dnum">'+d+'</div>';
    if (n>0){
      const dots = dotsFor(ds).map(k=>'<span class="dot '+k+'"></span>').join("");
      html += '<div class="dots">'+dots+'</div><div class="cnt">'+n+' 场</div>';
      c.onclick = ()=>showDay(ds);
    }
    c.innerHTML = html;
    cal.appendChild(c);
  }
  document.getElementById("monthLabel").textContent = viewY+" 年 "+MONTHS[viewM-1];
}
function showDay(ds){
  const arr = (byDate[ds]||[]).filter(passFilter).sort((a,b)=>a.title.localeCompare(b.title));
  document.getElementById("sideTitle").textContent = ds+" · "+arr.length+" 场";
  const body = document.getElementById("sideBody");
  if (!arr.length){ body.innerHTML='<div class="empty-note">无匹配录像</div>'; return; }
  let h="";
  for (const v of arr){
    const sk = v.stageKey||"other";
    const teams = (v.teams&&v.teams.length===2)? (v.teams[0]+" vs "+v.teams[1]) : "";
    h += '<div class="vitem"><div class="vt">'+esc(v.title)+'</div>'+
         '<div class="vm"><span class="badge '+sk+'">'+(STAGE_NAME[sk]||"其他")+'</span>'+
         (teams?'<span>'+esc(teams)+'</span>':'')+
         '<a class="open" href="#" data-path="'+esc(v.path)+'" onclick="playV(this);return false;">▶ 播放</a>'+
         '<a class="open" href="#" data-path="'+esc(v.path)+'" onclick="reveal(this.dataset.path);return false;">路径</a></div></div>';
  }
  body.innerHTML = h;
}
function videoURL(p){
  if (location.protocol === "file:") return "file:///Volumes/12T/NBA/" + p;
  return "/video/" + p;
}
function playV(el){
  const p = el.dataset.path;
  const pl = document.getElementById("player");
  pl.src = videoURL(p);
  pl.style.display = "block";
  pl.scrollIntoView({behavior:"smooth", block:"nearest"});
  pl.play().catch(()=>{ alert("浏览器阻止自动播放或无法加载。\n文件路径：/Volumes/12T/NBA/" + p); });
}
function reveal(p){
  alert("录像路径:\n/Volumes/12T/NBA/"+p);
}
function esc(s){ return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function renderUndated(){
  const sum = document.getElementById("undSummary");
  const list = document.getElementById("undList");
  sum.textContent = "⚠ 需人工确认 ("+DATA.undated.length+" 个无月/日文件) — 点击展开";
  let h="";
  for (const u of DATA.undated){
    const hy = u.hintYear? (" · 推测年份 "+u.hintYear):"";
    h += '<div class="vitem"><div class="vt">'+esc(u.title)+'</div>'+
         '<div class="vm"><span class="badge other">'+(u.stage||"未分类")+'</span>'+
         '<a class="open" href="#" data-path="'+esc(u.path)+'" onclick="playV(this);return false;">▶ 播放</a>'+
         '<span>'+esc(u.path)+hy+'</span></div></div>';
  }
  list.innerHTML = h || '<div class="empty-note">无</div>';
}
document.getElementById("prevM").onclick=()=>{viewM--; if(viewM<1){viewM=12;viewY--;} renderCal();};
document.getElementById("nextM").onclick=()=>{viewM++; if(viewM>12){viewM=1;viewY++;} renderCal();};
document.getElementById("prevY").onclick=()=>{viewY--; renderCal();};
document.getElementById("nextY").onclick=()=>{viewY++; renderCal();};
document.getElementById("todayBtn").onclick=()=>{const t=new Date();viewY=t.getFullYear();viewM=t.getMonth()+1;renderCal();};
document.querySelectorAll(".chip").forEach(ch=>{
  ch.onclick=()=>{
    document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on"));
    ch.classList.add("on"); activeFilter=ch.dataset.k; renderCal();
    const sd=document.getElementById("sideTitle").textContent; if(sd&&sd.length===10) showDay(sd);
  };
});
const sb=document.getElementById("search");
sb.addEventListener("input",()=>{searchQ=sb.value.trim(); renderCal(); const sd=document.getElementById("sideTitle").textContent; if(/^\d{4}-\d{2}-\d{2}$/.test(sd)) showDay(sd);});
document.addEventListener("keydown",e=>{
  if (e.key==="/"){ e.preventDefault(); sb.focus(); }
  else if (e.key==="Escape"){ sb.value=""; searchQ=""; renderCal(); document.activeElement.blur(); }
  else if (e.target===sb) return;
  else if (e.key==="ArrowLeft"){document.getElementById("prevM").click();}
  else if (e.key==="ArrowRight"){document.getElementById("nextM").click();}
  else if (e.key==="ArrowUp"){document.getElementById("prevY").click();}
  else if (e.key==="ArrowDown"){document.getElementById("nextY").click();}
});
// 初始: 跳到数据中最晚的年份/月
(function init(){
  let maxD="";
  for (const v of DATA.videos){ if(v.date>maxD) maxD=v.date; }
  if (maxD){ viewY=parseInt(maxD.slice(0,4)); viewM=parseInt(maxD.slice(5,7)); }
  else { const t=new Date(); viewY=t.getFullYear(); viewM=t.getMonth()+1; }
  renderCal(); renderUndated();
})();
</script>
</body>
</html>
"""

def main():
    videos, undated = scan()
    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "root": ROOT,
        "total": len(videos)+len(undated),
        "datable": len(videos),
        "undated_count": len(undated),
        "videos": videos,
        "undated": undated,
    }
    json_path = os.path.join(OUT_DIR, "video_index.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    html_path = os.path.join(OUT_DIR, "calendar.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE.replace("__DATA__", json.dumps(out, ensure_ascii=False)))
    # 报告
    print(f"扫描完成: 总 {out['total']} | 可定位日期 {out['datable']} | 待确认 {out['undated_count']}")
    # 年份分布(可定位)
    ydist={}
    for v in videos: ydist[v["year"]]=ydist.get(v["year"],0)+1
    print("年份分布(可定位, 前12):", dict(sorted(ydist.items(), reverse=True)[:12]))
    print("\n--- 需人工确认的文件 (无月/日, 共 %d) ---" % len(undated))
    for u in undated[:60]:
        hy = f" [推测{u['hintYear']}]" if u["hintYear"] else ""
        print(f"  {u['path']}{hy}")
    if len(undated)>60: print(f"  ... 还有 {len(undated)-60} 个，详见 video_index.json / calendar.html 的'需人工确认'区")
    print(f"\n输出: {json_path}\n      {html_path}")

if __name__ == "__main__":
    main()
