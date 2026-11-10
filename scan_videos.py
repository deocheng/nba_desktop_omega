#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描 <数据盘根>/比赛录像 下所有视频，提取:
  - 文件名自身的日期 (英文月/中文月/数字 YYYY_MM_DD 等)
  - 阶段 (从父目录名: 常规赛经典/季后赛/总决赛/全明星/夏联/季前赛)
  - 最佳球队 (vs / @ 两侧)
  - 相对路径
无"月+日"的文件 -> undated，列出供人工确认 (不放到日历)。
输出:
  - video_index.json
  - calendar.html (自包含, 内嵌数据)
"""
import json
import os
import re
import sys
from datetime import date, datetime

from common.nba_paths import DATA_ROOT

ROOT = str(DATA_ROOT) + '/比赛录像'
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

HTML_TEMPLATE = '<!DOCTYPE html>\n<html lang="zh">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>NBA 录像库日历</title>\n<style>\n:root{\n  --bg:#0e1116; --panel:#161b22; --panel2:#1c232c; --line:#2a323c;\n  --txt:#e6edf3; --muted:#8b949e; --accent:#58a6ff;\n  --rs:#3fb950; --po:#d29922; --fin:#f85149; --as:#bc8cff; --sl:#39c5cf; --pre:#8b949e; --other:#6e7681;\n}\n*{box-sizing:border-box}\nbody{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;}\na{color:var(--accent);text-decoration:none}\nheader{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:12px;align-items:center;position:sticky;top:0;background:var(--bg);z-index:10}\nh1{font-size:16px;margin:0;font-weight:600}\n.nav button{background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:6px;padding:5px 11px;cursor:pointer;font-size:13px}\n.nav button:hover{border-color:var(--accent)}\n#monthLabel{font-size:15px;font-weight:600;min-width:140px;text-align:center}\n.chips{display:flex;gap:6px;flex-wrap:wrap}\n.chip{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:3px 11px;cursor:pointer;font-size:12px;color:var(--muted)}\n.chip.on{color:#fff;border-color:transparent}\n.chip[data-k="rs"].on{background:var(--rs)} .chip[data-k="po"].on{background:var(--po)}\n.chip[data-k="fin"].on{background:var(--fin)} .chip[data-k="as"].on{background:var(--as)}\n.chip[data-k="sl"].on{background:var(--sl)} .chip[data-k="pre"].on{background:var(--pre)}\n.chip[data-k="all"].on{background:var(--accent)}\n#search{background:var(--panel);border:1px solid var(--line);border-radius:6px;color:var(--txt);padding:6px 10px;font-size:13px;min-width:180px}\n#search:focus{outline:none;border-color:var(--accent)}\nmain{display:flex;gap:0;align-items:flex-start}\n#calWrap{flex:1;padding:14px 18px;min-width:0}\n#cal{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}\n.dow{text-align:center;color:var(--muted);font-size:12px;padding:4px 0;border-bottom:1px solid var(--line)}\n.cell{min-height:78px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 6px;cursor:pointer;overflow:hidden;transition:.12s}\n.cell:hover{border-color:var(--accent)}\n.cell.empty{background:transparent;border:none;cursor:default}\n.cell.today{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}\n.dnum{font-size:12px;color:var(--muted)}\n.cell.today .dnum{color:var(--accent);font-weight:700}\n.dots{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}\n.dot{width:7px;height:7px;border-radius:50%}\n.dot.rs{background:var(--rs)} .dot.po{background:var(--po)} .dot.fin{background:var(--fin)}\n.dot.as{background:var(--as)} .dot.sl{background:var(--sl)} .dot.pre{background:var(--pre)} .dot.other{background:var(--other)}\n.cnt{font-size:11px;color:var(--muted);margin-top:2px}\n#side{width:340px;flex:none;border-left:1px solid var(--line);min-height:calc(100vh - 57px);padding:14px 16px;position:sticky;top:57px}\n#side h2{font-size:14px;margin:0 0 10px}\n.vitem{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin-bottom:8px}\n.vitem .vt{font-size:13px;font-weight:600;line-height:1.35}\n.vitem .vm{font-size:11px;color:var(--muted);margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}\n.badge{font-size:10px;padding:1px 7px;border-radius:10px;color:#0e1116;font-weight:700}\n.badge.rs{background:var(--rs)} .badge.po{background:var(--po)} .badge.fin{background:var(--fin)}\n.badge.as{background:var(--as)} .badge.sl{background:var(--sl)} .badge.pre{background:var(--pre)} .badge.other{background:var(--other)}\n.vitem a.open{font-size:11px}\n#undated{margin-top:18px}\n#undated summary{cursor:pointer;color:var(--muted);font-size:12px}\n#undated .vitem{opacity:.85}\n.empty-note{color:var(--muted);font-size:12px;padding:20px;text-align:center}\n.kbd{font:11px monospace;background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;color:var(--muted)}\nfooter{color:var(--muted);font-size:11px;padding:8px 18px;border-top:1px solid var(--line)}\n</style>\n</head>\n<body>\n<header>\n  <h1>🏀 NBA 录像库日历</h1>\n  <div class="nav">\n    <button id="prevY">« 年</button>\n    <button id="prevM">‹ 月</button>\n    <span id="monthLabel"></span>\n    <button id="nextM">月 ›</button>\n    <button id="nextY">年 »</button>\n    <button id="todayBtn">今天</button>\n  </div>\n  <div class="chips" id="chips">\n    <span class="chip on" data-k="all">全部</span>\n    <span class="chip" data-k="rs">常规赛</span>\n    <span class="chip" data-k="po">季后赛</span>\n    <span class="chip" data-k="fin">总决赛</span>\n    <span class="chip" data-k="as">全明星</span>\n    <span class="chip" data-k="sl">夏联</span>\n    <span class="chip" data-k="pre">季前赛</span>\n  </div>\n  <input id="search" placeholder="搜索球队/关键词  ( / 聚焦 )">\n</header>\n<main>\n  <div id="calWrap"><div id="cal"></div>\n    <div id="undated">\n      <details>\n        <summary id="undSummary"></summary>\n        <div id="undList"></div>\n      </details>\n    </div>\n  </div>\n  <aside id="side"><h2 id="sideTitle">点击日期查看录像</h2><video id="player" controls preload="none" style="display:none;width:100%;border-radius:8px;background:#000;margin-bottom:10px;"></video><div id="sideBody"><div class="empty-note">← 选择一个有录像的日期</div></div></aside>\n</main>\n<footer>\n  数据来自 ' + str(DATA_ROOT) + '/比赛录像 · 日期以文件名解析为准 · 无月/日文件已单列待人工确认 ·\n  快捷键: <span class="kbd">← →</span> 切换月 · <span class="kbd">↑ ↓</span> 切换年 · <span class="kbd">/</span> 搜索 · <span class="kbd">Esc</span> 返回\n</footer>\n<script>\nconst DATA = __DATA__;\nconst STAGE_NAME = {rs:"常规赛",po:"季后赛",fin:"总决赛",as:"全明星",sl:"夏联",pre:"季前赛",other:"其他"};\nconst MONTHS = ["一月","二月","三月","四月","五月","六月","七月","八月","九月","十月","十一月","十二月"];\nconst DOW = ["一","二","三","四","五","六","日"];\nlet viewY, viewM; // M: 1-12\nlet activeFilter = "all";\nlet searchQ = "";\n\n// 建索引: date -> [videos]\nconst byDate = {};\nfor (const v of DATA.videos){ (byDate[v.date] = byDate[v.date]||[]).push(v); }\n\nfunction passFilter(v){\n  if (activeFilter!=="all" && v.stageKey!==activeFilter) return false;\n  if (searchQ){\n    const q = searchQ.toLowerCase();\n    const hay = ((v.teams||[]).join(" ")+" "+v.title+" "+(v.stage||"")).toLowerCase();\n    if (!hay.includes(q)) return false;\n  }\n  return true;\n}\nfunction countFor(dateStr){\n  const arr = byDate[dateStr]||[];\n  return arr.filter(passFilter).length;\n}\nfunction dotsFor(dateStr){\n  const arr = (byDate[dateStr]||[]).filter(passFilter);\n  const seen={}; const out=[];\n  for (const v of arr){ if(!seen[v.stageKey]){seen[v.stageKey]=1; out.push(v.stageKey);} }\n  return out;\n}\nfunction renderCal(){\n  const cal = document.getElementById("cal");\n  cal.innerHTML="";\n  for (const d of DOW){ const e=document.createElement("div"); e.className="dow"; e.textContent=d; cal.appendChild(e); }\n  const first = new Date(viewY, viewM-1, 1);\n  let lead = (first.getDay()+6)%7; // 周一为0\n  for (let i=0;i<lead;i++){ const c=document.createElement("div"); c.className="cell empty"; cal.appendChild(c); }\n  const days = new Date(viewY, viewM, 0).getDate();\n  const today = new Date();\n  const tStr = today.getFullYear()+"-"+String(today.getMonth()+1).padStart(2,"0")+"-"+String(today.getDate()).padStart(2,"0");\n  for (let d=1; d<=days; d++){\n    const ds = viewY+"-"+String(viewM).padStart(2,"0")+"-"+String(d).padStart(2,"0");\n    const c = document.createElement("div");\n    c.className="cell"+(ds===tStr?" today":"");\n    const n = countFor(ds);\n    let html = \'<div class="dnum">\'+d+\'</div>\';\n    if (n>0){\n      const dots = dotsFor(ds).map(k=>\'<span class="dot \'+k+\'"></span>\').join("");\n      html += \'<div class="dots">\'+dots+\'</div><div class="cnt">\'+n+\' 场</div>\';\n      c.onclick = ()=>showDay(ds);\n    }\n    c.innerHTML = html;\n    cal.appendChild(c);\n  }\n  document.getElementById("monthLabel").textContent = viewY+" 年 "+MONTHS[viewM-1];\n}\nfunction showDay(ds){\n  const arr = (byDate[ds]||[]).filter(passFilter).sort((a,b)=>a.title.localeCompare(b.title));\n  document.getElementById("sideTitle").textContent = ds+" · "+arr.length+" 场";\n  const body = document.getElementById("sideBody");\n  if (!arr.length){ body.innerHTML=\'<div class="empty-note">无匹配录像</div>\'; return; }\n  let h="";\n  for (const v of arr){\n    const sk = v.stageKey||"other";\n    const teams = (v.teams&&v.teams.length===2)? (v.teams[0]+" vs "+v.teams[1]) : "";\n    h += \'<div class="vitem"><div class="vt">\'+esc(v.title)+\'</div>\'+\n         \'<div class="vm"><span class="badge \'+sk+\'">\'+(STAGE_NAME[sk]||"其他")+\'</span>\'+\n         (teams?\'<span>\'+esc(teams)+\'</span>\':\'\')+\n         \'<a class="open" href="#" data-path="\'+esc(v.path)+\'" onclick="playV(this);return false;">▶ 播放</a>\'+\n         \'<a class="open" href="#" data-path="\'+esc(v.path)+\'" onclick="reveal(this.dataset.path);return false;">路径</a></div></div>\';\n  }\n  body.innerHTML = h;\n}\nfunction videoURL(p){\n  if (location.protocol === "file:") return "file://' + str(DATA_ROOT) + '/" + p;\n  return "/video/" + p;\n}\nfunction playV(el){\n  const p = el.dataset.path;\n  const pl = document.getElementById("player");\n  pl.src = videoURL(p);\n  pl.style.display = "block";\n  pl.scrollIntoView({behavior:"smooth", block:"nearest"});\n  pl.play().catch(()=>{ alert("浏览器阻止自动播放或无法加载。\\n文件路径：' + str(DATA_ROOT) + '/" + p); });\n}\nfunction reveal(p){\n  alert("录像路径:\\n' + str(DATA_ROOT) + '/"+p);\n}\nfunction esc(s){ return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c])); }\nfunction renderUndated(){\n  const sum = document.getElementById("undSummary");\n  const list = document.getElementById("undList");\n  sum.textContent = "⚠ 需人工确认 ("+DATA.undated.length+" 个无月/日文件) — 点击展开";\n  let h="";\n  for (const u of DATA.undated){\n    const hy = u.hintYear? (" · 推测年份 "+u.hintYear):"";\n    h += \'<div class="vitem"><div class="vt">\'+esc(u.title)+\'</div>\'+\n         \'<div class="vm"><span class="badge other">\'+(u.stage||"未分类")+\'</span>\'+\n         \'<a class="open" href="#" data-path="\'+esc(u.path)+\'" onclick="playV(this);return false;">▶ 播放</a>\'+\n         \'<span>\'+esc(u.path)+hy+\'</span></div></div>\';\n  }\n  list.innerHTML = h || \'<div class="empty-note">无</div>\';\n}\ndocument.getElementById("prevM").onclick=()=>{viewM--; if(viewM<1){viewM=12;viewY--;} renderCal();};\ndocument.getElementById("nextM").onclick=()=>{viewM++; if(viewM>12){viewM=1;viewY++;} renderCal();};\ndocument.getElementById("prevY").onclick=()=>{viewY--; renderCal();};\ndocument.getElementById("nextY").onclick=()=>{viewY++; renderCal();};\ndocument.getElementById("todayBtn").onclick=()=>{const t=new Date();viewY=t.getFullYear();viewM=t.getMonth()+1;renderCal();};\ndocument.querySelectorAll(".chip").forEach(ch=>{\n  ch.onclick=()=>{\n    document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on"));\n    ch.classList.add("on"); activeFilter=ch.dataset.k; renderCal();\n    const sd=document.getElementById("sideTitle").textContent; if(sd&&sd.length===10) showDay(sd);\n  };\n});\nconst sb=document.getElementById("search");\nsb.addEventListener("input",()=>{searchQ=sb.value.trim(); renderCal(); const sd=document.getElementById("sideTitle").textContent; if(/^\\d{4}-\\d{2}-\\d{2}$/.test(sd)) showDay(sd);});\ndocument.addEventListener("keydown",e=>{\n  if (e.key==="/"){ e.preventDefault(); sb.focus(); }\n  else if (e.key==="Escape"){ sb.value=""; searchQ=""; renderCal(); document.activeElement.blur(); }\n  else if (e.target===sb) return;\n  else if (e.key==="ArrowLeft"){document.getElementById("prevM").click();}\n  else if (e.key==="ArrowRight"){document.getElementById("nextM").click();}\n  else if (e.key==="ArrowUp"){document.getElementById("prevY").click();}\n  else if (e.key==="ArrowDown"){document.getElementById("nextY").click();}\n});\n// 初始: 跳到数据中最晚的年份/月\n(function init(){\n  let maxD="";\n  for (const v of DATA.videos){ if(v.date>maxD) maxD=v.date; }\n  if (maxD){ viewY=parseInt(maxD.slice(0,4)); viewM=parseInt(maxD.slice(5,7)); }\n  else { const t=new Date(); viewY=t.getFullYear(); viewM=t.getMonth()+1; }\n  renderCal(); renderUndated();\n})();\n</script>\n</body>\n</html>\n'

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
