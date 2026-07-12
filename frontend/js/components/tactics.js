/**
 * NBACore v8 — 球队战术板 + PBP 动态回放组件（纯渲染，Layer 4）
 * ================================================================
 * 半场 SVG 战术板：双色带号圆圈 + 篮球 + 路径箭头 + 事件标注气泡 + 回放控制条
 * + 战术模板选择面板 + AI 生成入口（灰显，P2）。
 *
 * 四层隔离红线：本组件**仅消费后端 Engine 生成的逐帧坐标序列 JSON**，
 * 用 requestAnimationFrame 推进帧并渲染 SVG。**不做任何坐标映射 / 插值 / 聚合
 * 计算**（计算全在 backend/services/tactics_engine）。
 *
 * 依赖全局（js/app.js 先加载）：api() / toast() / escapeHtml() / THEME。
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var SEASONS = [2026, 2025, 2024, 2023, 2022, 2021, 2020];

  // 播放状态（模块级，render 时重置）
  var state = { frames: [], meta: {}, events: [], cur: 0, playing: false, speed: 1, last: null, courtMode: 'full' };
  var playerEls = {};   // player_id -> {g, circle, text}
  var rafId = null;
  var tickCbs = [];     // onTick 回调列表（供外部驱动引擎消费，如融合回放页）

  function eh(v) {
    if (typeof escapeHtml === 'function') return escapeHtml(v == null ? '' : String(v));
    return String(v == null ? '' : v);
  }

  function el(id) { return document.getElementById(id); }

  function svgEl(name, attrs) {
    var e = document.createElementNS(SVG_NS, name);
    if (attrs) {
      for (var k in attrs) { if (attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]); }
    }
    return e;
  }

  // ───────────────────────── 渲染入口 ─────────────────────────
  // mode: 'full'（默认，战术板完整页）| 'clutch'（融合关键时刻回放：仅球场+控制条+侧栏插槽+高亮轨道插槽）
  // courtMode: 'full'（全场双筐广播视角，PBP 回放）| 'half'（半场，战术板模板）
  function render(containerId, mode, courtMode) {
    mode = mode || 'full';
    var container = el(containerId);
    if (!container) return;
    // 取消上一实例的 rAF，避免叠加
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    state = { frames: [], meta: {}, events: [], cur: 0, playing: false, speed: 1, last: null, courtMode: courtMode || 'full' };
    playerEls = {};
    tickCbs = [];

    container.innerHTML = buildLayout(mode, state.courtMode);
    buildCourt(state.courtMode);
    bindControls();
    // clutch 模式由融合回放页（clutch_replay.js）注入选择面板/侧栏，跳过模板与赛季预载
    if (mode !== 'clutch') {
      loadTemplates();
      initSeason();
    }
    // 每帧同步 PBP 文字解说（仅更新解说条文本，不重绘球场）
    onTick(updateCaption);

    rafId = requestAnimationFrame(tick);
  }

  function buildLayout(mode, courtMode) {
    if (mode === 'clutch') return buildClutchLayout(courtMode);
    var vb = (courtMode === 'full') ? '0 0 940 500' : '0 0 500 470';
    return (
      '<div class="page-header">' +
        '<h2>球队战术板 · Tactics Board <span style="font-size:13px;color:var(--text-dim);">v1</span></h2>' +
        '<button id="tacticsAiBtn" class="tactics-ai-badge" title="AI 战术生成（P2 预留）">🤖 AI 生成 · 即将上线</button>' +
      '</div>' +
      '<div class="tactics-layout">' +
        // 左：模板 / 比赛选择面板
        '<div class="tactics-panel card">' +
          '<div class="card-title">战术模板</div>' +
          '<select id="tacticsTemplateSel" class="select"></select>' +
          '<button id="tacticsLoadTpl" class="btn btn-primary btn-block">加载模板演示</button>' +
          '<hr class="tactics-hr"/>' +
          '<div class="card-title">PBP 动态回放</div>' +
          '<label class="label">赛季 Season</label>' +
          '<select id="tacticsSeasonSel" class="select"></select>' +
          '<label class="label">比赛 Game</label>' +
          '<select id="tacticsGameSel" class="select"></select>' +
          '<button id="tacticsLoadGame" class="btn btn-primary btn-block">加载回放</button>' +
          '<div id="tacticsMeta" class="tactics-meta"></div>' +
        '</div>' +
        // 中：半场 SVG 战术板
          '<div class="tactics-court-wrap card">' +
          '<svg id="tacticsCourt" viewBox="' + vb + '" preserveAspectRatio="xMidYMid meet"></svg>' +
        '</div>' +
        // 右：图例
        '<div class="tactics-legend card">' +
          '<div class="card-title">事件图例</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#10b981"></span>✅ 命中 MAKE</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#ef4444"></span>❌ 投失 MISS</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#3b82f6"></span>AST 助攻</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#8b5cf6"></span>REB 篮板</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#f59e0b"></span>PF 犯规</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#94a3b8"></span>TOV/SUB</div>' +
          '<hr class="tactics-hr"/>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#2563eb"></span>主队 HOME</div>' +
          '<div class="tactics-legend-row"><span class="tactics-dot" style="background:#ef4444"></span>客队 AWAY</div>' +
        '</div>' +
      '</div>' +
      // PBP 文字解说条（随帧同步节次 / 时钟 / 比分 / 解说）
      '<div class="tactics-pbp-bar card" id="tacticsPbpBar">' +
        '<div class="tactics-pbp-score" id="tacticsPbpScore"></div>' +
        '<div class="tactics-pbp-desc" id="tacticsPbpDesc">加载回放后显示 PBP 解说…</div>' +
      '</div>' +
      // 下：回放控制条
      '<div class="tactics-controls card">' +
        '<button id="tacticsPlay" class="btn btn-ghost">▶ 播放</button>' +
        '<div class="tactics-speed">' +
          '<button data-speed="1" class="active">1x</button>' +
          '<button data-speed="2">2x</button>' +
          '<button data-speed="4">4x</button>' +
        '</div>' +
        '<input id="tacticsProgress" class="tactics-progress" type="range" min="0" max="1000" value="0"/>' +
        '<span id="tacticsTime" class="tactics-time">0.0s</span>' +
      '</div>'
    );
  }

  // ───────────────────────── 融合回放布局（clutch 模式）─────────────────────────
  // 仅含：半场 SVG 球场 + 控制条（含高亮轨道插槽 #tacticsClutchTrack）+ 侧栏插槽
  // #tacticsClutchSidebar。选择面板 / 侧栏内容 / 高亮段由 clutch_replay.js 注入。
  function buildClutchLayout(courtMode) {
    var vb = (courtMode === 'full') ? '0 0 940 500' : '0 0 500 470';
    return (
      '<div class="clutch-layout">' +
        '<div class="clutch-court-wrap card">' +
          '<svg id="tacticsCourt" viewBox="' + vb + '" preserveAspectRatio="xMidYMid meet"></svg>' +
        '</div>' +
        '<div id="tacticsClutchSidebar" class="clutch-sidebar card"></div>' +
      '</div>' +
      // PBP 文字解说条（clutch 复用 tactics 播放引擎；events 由融合页透传则为空）
      '<div class="tactics-pbp-bar card" id="tacticsPbpBar">' +
        '<div class="tactics-pbp-score" id="tacticsPbpScore"></div>' +
        '<div class="tactics-pbp-desc" id="tacticsPbpDesc">融合回放加载后显示 PBP 解说…</div>' +
      '</div>' +
      '<div class="tactics-controls card">' +
        '<div id="tacticsClutchTrack" class="tactics-clutch-track" title="关键时刻高亮段（点击跳转）"></div>' +
        '<button id="tacticsPlay" class="btn btn-ghost">▶ 播放</button>' +
        '<div class="tactics-speed">' +
          '<button data-speed="1" class="active">1x</button>' +
          '<button data-speed="2">2x</button>' +
          '<button data-speed="4">4x</button>' +
        '</div>' +
        '<input id="tacticsProgress" class="tactics-progress" type="range" min="0" max="1000" value="0"/>' +
        '<span id="tacticsTime" class="tactics-time">0.0s</span>' +
      '</div>'
    );
  }

  // ───────────────────────── 底图分派（full=全场 / half=半场）─────────────────────────
  function buildCourt(mode) {
    var svg = el('tacticsCourt');
    if (!svg) return;
    svg.innerHTML = '';   // 清空重绘，切换 courtMode 时不叠加
    if (mode === 'full') {
      drawFullCourt();
    } else {
      drawHalfCourt();
    }
  }

  // ───────────────────────── 半场 SVG 底图（固定图形，非坐标计算）─────────────────────────
  function drawHalfCourt() {
    var svg = el('tacticsCourt');
    if (!svg) return;

    var defs = svgEl('defs');
    var marker = svgEl('marker', {
      id: 'tacticsArrow', markerWidth: 9, markerHeight: 9,
      refX: 6, refY: 3, orient: 'auto', markerUnits: 'userSpaceOnUse'
    });
    marker.appendChild(svgEl('path', { d: 'M0,0 L6,3 L0,6 Z', fill: '#94a3b8' }));
    defs.appendChild(marker);
    svg.appendChild(defs);

    var g = svgEl('g');
    // 底色
    g.appendChild(svgEl('rect', { x: 0, y: 0, width: 500, height: 470, fill: '#f8fafc', stroke: '#cbd5e1' }));
    // 边线
    g.appendChild(svgEl('rect', { x: 0, y: 0, width: 500, height: 470, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    // 三分弧（以篮筐 (250,470) 为圆心，半径 237）
    g.appendChild(svgEl('path', { d: 'M 13 470 A 237 237 0 0 1 487 470', fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    // 罚球区（paint）
    g.appendChild(svgEl('rect', { x: 170, y: 280, width: 160, height: 190, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    // 罚球圈
    g.appendChild(svgEl('circle', { cx: 250, cy: 280, r: 60, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    // 篮板 + 篮筐
    g.appendChild(svgEl('line', { x1: 232, y1: 452, x2: 268, y2: 452, stroke: '#334155', 'stroke-width': 3 }));
    g.appendChild(svgEl('circle', { cx: 250, cy: 462, r: 8, fill: 'none', stroke: '#ef4444', 'stroke-width': 2 }));
    // 半场中线提示
    g.appendChild(svgEl('line', { x1: 0, y1: 0, x2: 500, y2: 0, stroke: '#94a3b8', 'stroke-width': 1, 'stroke-dasharray': '3 3' }));
    svg.appendChild(g);

    // 动态层
    svg.appendChild(svgEl('g', { id: 'tacticsBallPath' }));
    svg.appendChild(svgEl('g', { id: 'tacticsArrows' }));
    svg.appendChild(svgEl('g', { id: 'tacticsPlayers' }));
    svg.appendChild(svgEl('g', { id: 'tacticsAnnotations' }));
    // 篮球
    var ball = svgEl('circle', { id: 'tacticsBallEl', cx: 250, cy: 462, r: 9, fill: '#e08a00', stroke: '#7c3f00', 'stroke-width': 1.5 });
    svg.appendChild(ball);
  }

  // ───────────────────────── 全场 SVG 底图（广播视角，双篮筐，固定图形非坐标计算）─────────────────────────
  function drawFullCourt() {
    var svg = el('tacticsCourt');
    if (!svg) return;

    var defs = svgEl('defs');
    var marker = svgEl('marker', {
      id: 'tacticsArrow', markerWidth: 9, markerHeight: 9,
      refX: 6, refY: 3, orient: 'auto', markerUnits: 'userSpaceOnUse'
    });
    marker.appendChild(svgEl('path', { d: 'M0,0 L6,3 L0,6 Z', fill: '#94a3b8' }));
    defs.appendChild(marker);
    svg.appendChild(defs);

    var g = svgEl('g');
    // 底色 + 边线
    g.appendChild(svgEl('rect', { x: 0, y: 0, width: 940, height: 500, fill: '#f8fafc', stroke: '#cbd5e1' }));
    g.appendChild(svgEl('rect', { x: 0, y: 0, width: 940, height: 500, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    // 中线 + 中圈
    g.appendChild(svgEl('line', { x1: 470, y1: 0, x2: 470, y2: 500, stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('circle', { cx: 470, cy: 250, r: 60, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));

    // 左端篮筐（中心 (0,250)）
    g.appendChild(svgEl('path', { d: 'M 0 13 A 237 237 0 0 1 0 487', fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('rect', { x: 0, y: 170, width: 190, height: 160, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('circle', { cx: 190, cy: 250, r: 60, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('line', { x1: 18, y1: 232, x2: 18, y2: 268, stroke: '#334155', 'stroke-width': 3 }));
    g.appendChild(svgEl('circle', { cx: 8, cy: 250, r: 8, fill: 'none', stroke: '#ef4444', 'stroke-width': 2 }));
    // 右端篮筐（镜像 fx → 940-fx，中心 (940,250)）
    g.appendChild(svgEl('path', { d: 'M 940 13 A 237 237 0 0 0 940 487', fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('rect', { x: 750, y: 170, width: 190, height: 160, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('circle', { cx: 750, cy: 250, r: 60, fill: 'none', stroke: '#334155', 'stroke-width': 2 }));
    g.appendChild(svgEl('line', { x1: 922, y1: 232, x2: 922, y2: 268, stroke: '#334155', 'stroke-width': 3 }));
    g.appendChild(svgEl('circle', { cx: 932, cy: 250, r: 8, fill: 'none', stroke: '#ef4444', 'stroke-width': 2 }));
    svg.appendChild(g);

    // 动态层
    svg.appendChild(svgEl('g', { id: 'tacticsBallPath' }));
    svg.appendChild(svgEl('g', { id: 'tacticsArrows' }));
    svg.appendChild(svgEl('g', { id: 'tacticsPlayers' }));
    svg.appendChild(svgEl('g', { id: 'tacticsAnnotations' }));
    // 篮球（初始置于中圈）
    var ball = svgEl('circle', { id: 'tacticsBallEl', cx: 470, cy: 250, r: 9, fill: '#e08a00', stroke: '#7c3f00', 'stroke-width': 1.5 });
    svg.appendChild(ball);
  }

  // ───────────────────────── 控制条绑定 ─────────────────────────
  function bindControls() {
    var playBtn = el('tacticsPlay');
    if (playBtn) playBtn.onclick = function () {
      if (!state.frames.length) return;
      state.playing = !state.playing;
      if (state.playing && state.cur >= state.frames.length - 1) state.cur = 0;
      setPlayBtn();
    };
    // 以下元素仅存在于完整（战术板）模式；clutch 模式由融合回放页接管
    var loadTpl = el('tacticsLoadTpl');
    if (loadTpl) loadTpl.onclick = function () {
      var id = el('tacticsTemplateSel').value;
      if (id) loadTemplate(id);
    };
    var loadGame = el('tacticsLoadGame');
    if (loadGame) loadGame.onclick = function () {
      var gid = el('tacticsGameSel').value;
      var season = el('tacticsSeasonSel').value;
      if (gid) loadGame(gid, season);
    };
    var seasonSel = el('tacticsSeasonSel');
    if (seasonSel) seasonSel.onchange = function () { loadGames(seasonSel.value); };
    var aiBtn = el('tacticsAiBtn');
    if (aiBtn) aiBtn.onclick = function () {
      if (typeof toast === 'function') toast('AI 战术生成即将上线（P2 / Mac+Ollama 远期目标）', 'info');
    };
    // 速度档（两种模式都存在）
    var speedBtns = document.querySelectorAll('.tactics-speed button');
    speedBtns.forEach(function (b) {
      b.onclick = function () {
        speedBtns.forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        state.speed = parseFloat(b.getAttribute('data-speed')) || 1;
      };
    });
    // 进度条
    var prog = el('tacticsProgress');
    if (prog) prog.oninput = function () {
      if (!state.frames.length) return;
      var frac = parseInt(prog.value, 10) / 1000;
      state.cur = frac * (state.frames.length - 1);
      state.playing = false;
      setPlayBtn();
      renderFrame(state.frames[Math.floor(state.cur)]);
      updateTime();
      fireTick();
    };
  }

  function setPlayBtn() {
    el('tacticsPlay').textContent = state.playing ? '⏸ 暂停' : '▶ 播放';
  }

  // ───────────────────────── 数据加载 ─────────────────────────
  function loadTemplates() {
    api('/tactics/templates').then(function (r) {
      var list = (r && r.data) || [];
      var sel = el('tacticsTemplateSel');
      sel.innerHTML = list.map(function (t) {
        return '<option value="' + eh(t.id) + '">' + eh(t.name) + '</option>';
      }).join('');
    }).catch(function (e) {
      console.error('tactics templates failed', e);
    });
  }

  function initSeason() {
    var sel = el('tacticsSeasonSel');
    sel.innerHTML = SEASONS.map(function (s) {
      return '<option value="' + s + '">' + s + '-' + String(s + 1).slice(-2) + '</option>';
    }).join('');
    sel.value = '2025';
    loadGames('2025');
  }

  function loadGames(season) {
    api('/tactics/games?season=' + encodeURIComponent(season)).then(function (r) {
      var games = (r && r.data) || [];
      var sel = el('tacticsGameSel');
      if (!games.length) {
        sel.innerHTML = '<option value="">该季暂无回放数据</option>';
        return;
      }
      sel.innerHTML = games.map(function (g) {
        var teams = (g.teams || []).join(' vs ');
        return '<option value="' + eh(g.game_id) + '">' + eh(teams) + ' · ' + g.event_count + '事件</option>';
      }).join('');
    }).catch(function (e) {
      console.error('tactics games failed', e);
    });
  }

  function loadTemplate(id) {
    api('/tactics/templates/' + encodeURIComponent(id) + '?fps=30').then(function (r) {
      var data = r.data;
      state.frames = data.frames || [];
      state.meta = data.meta || {};
      state.events = [];   // 战术板模板无 PBP 文字解说
      drawArrows(data.arrows_svg || []);
      drawBallPath(data.ball_path_svg || []);
      state.cur = 0; state.playing = true; state.last = null;
      setPlayBtn();
      setCourtMode('half');   // 战术板模板保持半场
      renderFrame(state.frames[0]);
      updateCaption(0, state.frames[0]);
      updateTime();
    }).catch(function (e) {
      if (typeof toast === 'function') toast('加载模板失败: ' + e.message, 'error');
    });
  }

  function loadGame(gameId, season) {
    api('/tactics/replay/metadata/' + encodeURIComponent(gameId) + '?season=' + encodeURIComponent(season))
      .then(function (m) {
        var meta = (m && m.data) || {};
        el('tacticsMeta').innerHTML =
          '赛季 ' + eh(season) + ' · 节 ' + (meta.period_min || '-') + '-' + (meta.period_max || '-') +
          '<br/>事件 ' + (meta.event_count || 0) + ' · 含坐标 ' + (meta.xy_count || 0);
        return api('/tactics/replay', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId, season: season, frame_rate: 30 })
        });
      })
      .then(function (r) {
        var data = r.data;
        state.frames = data.frames || [];
        state.meta = data.meta || {};
        state.events = data.events || [];   // PBP 文字解说（与 frames 同序）
        clearArrows();
        state.cur = 0; state.playing = true; state.last = null;
        setPlayBtn();
        setCourtMode('full');               // 回放恒全场双筐 + 清空重绘底图
        renderFrame(state.frames[0]);
        updateCaption(0, state.frames[0]);  // 立即填充首条解说
        updateTime();
      })
      .catch(function (e) {
        if (typeof toast === 'function') toast('加载回放失败: ' + e.message, 'error');
      });
  }

  // ───────────────────────── 箭头 / 篮球轨迹（预映射 SVG 像素）─────────────────────────
  function drawArrows(arrows) {
    var g = el('tacticsArrows');
    if (!g) return;
    g.innerHTML = '';
    arrows.forEach(function (pts) {
      if (!pts || pts.length < 2) return;
      var poly = svgEl('polyline', {
        points: pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' '),
        fill: 'none', stroke: '#94a3b8', 'stroke-width': 2,
        'stroke-dasharray': '4 3', 'marker-end': 'url(#tacticsArrow)'
      });
      g.appendChild(poly);
    });
  }

  function drawBallPath(pts) {
    var g = el('tacticsBallPath');
    if (!g) return;
    g.innerHTML = '';
    if (pts && pts.length >= 2) {
      g.appendChild(svgEl('polyline', {
        points: pts.map(function (p) { return p[0] + ',' + p[1]; }).join(' '),
        fill: 'none', stroke: '#f59e0b', 'stroke-width': 1.5, 'stroke-dasharray': '2 4', opacity: 0.7
      }));
    }
  }

  function clearArrows() {
    var a = el('tacticsArrows'); if (a) a.innerHTML = '';
    var b = el('tacticsBallPath'); if (b) b.innerHTML = '';
  }

  // ───────────────────────── 帧渲染（仅消费坐标）─────────────────────────
  function renderFrame(f) {
    if (!f) return;
    var layer = el('tacticsPlayers');
    if (!layer) return;
    var seen = {};

    (f.players || []).forEach(function (p) {
      seen[p.player_id] = true;
      var rec = playerEls[p.player_id];
      if (!rec) {
        var g = svgEl('g');
        var c = svgEl('circle', { r: 14, fill: p.color, stroke: '#ffffff', 'stroke-width': 2 });
        var t = svgEl('text', {
          'text-anchor': 'middle', 'dominant-baseline': 'central',
          'font-size': 11, 'font-weight': 700, fill: '#ffffff'
        });
        g.appendChild(c); g.appendChild(t);
        layer.appendChild(g);
        rec = playerEls[p.player_id] = { g: g, circle: c, text: t };
      }
      // 持球人高亮：金色描边，强调当前控球者（坐标由后端计算，前端仅渲染）
      var isHolder = !!(f.ball && f.ball.holder && p.player_id === f.ball.holder);
      rec.circle.setAttribute('cx', p.x_px);
      rec.circle.setAttribute('cy', p.y_px);
      rec.circle.setAttribute('stroke', isHolder ? '#fbbf24' : '#ffffff');
      rec.circle.setAttribute('stroke-width', isHolder ? 3.5 : 2);
      rec.text.setAttribute('x', p.x_px);
      rec.text.setAttribute('y', p.y_px);
      rec.text.textContent = p.label;
    });
    // 移除本帧不存在的球员
    Object.keys(playerEls).forEach(function (pid) {
      if (!seen[pid]) {
        var rec = playerEls[pid];
        if (rec && rec.g && rec.g.parentNode) rec.g.parentNode.removeChild(rec.g);
        delete playerEls[pid];
      }
    });

    // 篮球
    var ball = el('tacticsBallEl');
    if (ball && f.ball) {
      ball.setAttribute('cx', f.ball.x_px);
      ball.setAttribute('cy', f.ball.y_px);
    }

    // 事件标注气泡
    var ag = el('tacticsAnnotations');
    if (ag) {
      ag.innerHTML = '';
      (f.annotations || []).forEach(function (a) {
        var color = annotColor(a.type);
        var g = svgEl('g');
        var rect = svgEl('rect', {
          x: a.x_px - 16, y: a.y_px - 30, width: 32, height: 20, rx: 5,
          fill: color, stroke: '#ffffff', 'stroke-width': 1, opacity: 0.95
        });
        var t = svgEl('text', {
          x: a.x_px, y: a.y_px - 20, 'text-anchor': 'middle',
          'dominant-baseline': 'central', 'font-size': 12, 'font-weight': 700, fill: '#ffffff'
        });
        t.textContent = a.text;
        g.appendChild(rect); g.appendChild(t);
        ag.appendChild(g);
      });
    }
  }

  function annotColor(type) {
    switch (type) {
      case 'MAKE': return '#10b981';
      case 'MISS': return '#ef4444';
      case 'AST': return '#3b82f6';
      case 'REB': return '#8b5cf6';
      case 'PF': return '#f59e0b';
      default: return '#94a3b8';
    }
  }

  function updateTime() {
    var f = state.frames[Math.floor(state.cur)] || state.frames[0];
    if (f) el('tacticsTime').textContent = Number(f.t).toFixed(1) + 's';
  }

  function updateProgress() {
    var max = state.frames.length - 1;
    if (max <= 0) return;
    el('tacticsProgress').value = Math.round((state.cur / max) * 1000);
  }

  // ───────────────────────── rAF 推进 ─────────────────────────
  function tick(ts) {
    if (state.frames.length && state.playing) {
      if (state.last == null) state.last = ts;
      var dt = (ts - state.last) / 1000;
      state.last = ts;
      state.cur += state.speed * (state.meta.fps || 30) * dt;
      if (state.cur >= state.frames.length - 1) {
        state.cur = state.frames.length - 1;
        state.playing = false;
        setPlayBtn();
      }
      renderFrame(state.frames[Math.floor(state.cur)]);
      updateProgress();
      updateTime();
      fireTick();
    } else {
      state.last = null;
    }
    rafId = requestAnimationFrame(tick);
  }

  // ───────────────────────── 可驱动播放引擎 API（供融合回放页调用）─────────────────────────
  // 以下函数构成稳定的公共 API：setFrames / seekFrame / seekProgress / play / pause / onTick。
  // 渲染与坐标插值逻辑完全复用既有实现，未重写。

  // 注入帧序列并重置播放（由外部融合页在取数后调用）
  function setFrames(frames, meta, events) {
    state.frames = frames || [];
    state.meta = meta || {};
    state.events = events || [];   // PBP 解说（融合页透传；无则为空）
    state.cur = 0;
    state.playing = false;
    state.last = null;
    setPlayBtn();
    if (state.frames.length) renderFrame(state.frames[0]);
    updateProgress();
    updateTime();
    fireTick();
  }

  // 跳转到指定绝对帧下标
  function seekFrame(idx) {
    if (!state.frames.length) return;
    state.cur = Math.max(0, Math.min(state.frames.length - 1, Math.round(idx || 0)));
    state.playing = false;
    setPlayBtn();
    renderFrame(state.frames[Math.floor(state.cur)]);
    updateProgress();
    updateTime();
    fireTick();
  }

  // 按进度跳转：p ∈ [0,1] 或 [0,1000]（与 range 0–1000 一致），自动归一化
  function seekProgress(p) {
    if (!state.frames.length) return;
    var frac = (p > 1) ? (p / 1000) : (p || 0);
    frac = Math.max(0, Math.min(1, frac));
    seekFrame(frac * (state.frames.length - 1));
  }

  function play() {
    if (!state.frames.length) return;
    if (state.cur >= state.frames.length - 1) state.cur = 0;
    state.playing = true;
    setPlayBtn();
  }

  function pause() {
    state.playing = false;
    setPlayBtn();
  }

  // 注册每帧回调 (idx, frame)；返回注销函数。供融合页同步高亮/侧栏
  function onTick(cb) {
    if (typeof cb === 'function') tickCbs.push(cb);
    return function () { tickCbs = tickCbs.filter(function (f) { return f !== cb; }); };
  }

  function fireTick() {
    if (!state.frames.length) return;
    var idx = Math.floor(state.cur);
    var frame = state.frames[idx];
    for (var i = 0; i < tickCbs.length; i++) {
      try { tickCbs[i](idx, frame); } catch (e) { console.error('[Tactics.onTick]', e); }
    }
  }

  // ───────────────────────── 运行时切场（先模板后半场等场景）─────────────────────────
  // 更新 state.courtMode、改 SVG viewBox、清空并重绘底图、重渲染当前帧（不重置播放进度）。
  function setCourtMode(mode) {
    mode = mode || 'full';
    state.courtMode = mode;
    var svg = el('tacticsCourt');
    if (!svg) return;
    svg.setAttribute('viewBox', mode === 'full' ? '0 0 940 500' : '0 0 500 470');
    buildCourt(mode);   // 清空并重绘底图
    if (state.frames.length) {
      renderFrame(state.frames[Math.floor(state.cur)]);
      updateProgress();
      updateTime();
    }
  }

  // ───────────────────────── PBP 文字同步（经 onTick，每帧仅更新文字节点）─────────────────────────
  // 坐标只来自帧 px 与 events 文本，零坐标计算。
  function updateCaption(idx, frame) {
    var scoreEl = el('tacticsPbpScore');
    var descEl = el('tacticsPbpDesc');
    if (!scoreEl || !descEl) return;
    if (!frame) return;
    var ei = frame.event_index;
    // events 按 event_index 升序：取 event_index <= ei 且 description 非空的最近一条
    var chosen = null;
    var h = 0, a = 0;
    var evs = state.events || [];
    for (var i = 0; i < evs.length; i++) {
      var ev = evs[i];
      if (ev.event_index > ei) break;       // 升序，后续必更大
      if (ev.description) chosen = ev;
      if (ev.h_pts) h = ev.h_pts;            // 末次非空向前填充
      if (ev.a_pts) a = ev.a_pts;
    }
    if (!chosen) {
      scoreEl.textContent = '';
      descEl.textContent = '加载回放后显示 PBP 解说…';
      return;
    }
    var period = chosen.period || 0;
    var clock = chosen.clock_seconds != null ? chosen.clock_seconds : 0;
    var periodLabel = period > 4 ? ('OT' + (period - 4)) : ('Q' + period);
    var cs = Math.max(0, Number(clock) || 0);
    var mm = Math.floor(cs / 60);
    var ss = Math.floor(cs % 60);
    var clockLabel = mm + ':' + (ss < 10 ? '0' + ss : ss);
    scoreEl.textContent = periodLabel + ' · ' + clockLabel + ' · ' + h + '-' + a;
    descEl.textContent = chosen.description;
  }

  // ── Public API ──
  window.Tactics = {
    render: render,
    setFrames: setFrames,
    setCourtMode: setCourtMode,
    seekFrame: seekFrame,
    seekProgress: seekProgress,
    play: play,
    pause: pause,
    onTick: onTick,
  };
})();
