/**
 * NBACore v8 — 融合关键时刻回放组件（纯渲染，Layer 4）
 * ================================================================
 * 复用战术板播放引擎（window.Tactics 的可驱动 API：setFrames / seekFrame /
 * seekProgress / play / pause / onTick）将「战术板逐帧回放」与「clutch 关键时刻
 * 统计」融合为一页：
 *   - 调 /clutch-replay/replay 取 frames + clutch_segments + clutch_players
 *   - 把 frames 交给 Tactics 引擎播放（坐标渲染、rAF 推进全在 tactics 层）
 *   - 在 Timeline 高亮轨道画 clutch 高亮段（投影到 0–1000），点击跳片段
 *   - 右侧侧栏渲染 clutch_players，游标进入片段时高亮相关球员行
 *
 * 四层隔离红线：本组件**不做任何坐标映射 / 插值 / 映射 / clutch 计算**，
 * 仅消费后端返回的数据并驱动 Tactics 引擎。所有计算在 backend 的 Engine 层。
 */
(function () {
  'use strict';

  var SEASONS = [2026, 2025, 2024, 2023, 2022, 2021, 2020];

  // 模块级状态（每次 render 重置）
  var currentSegments = [];
  var currentMeta = {};
  var segPlayerNames = [];   // 第 i 个片段涉及的球员名（用于侧栏联动）
  var unTick = null;

  function eh(v) {
    if (typeof escapeHtml === 'function') return escapeHtml(v == null ? '' : String(v));
    return String(v == null ? '' : v);
  }

  function toastSafe(msg, type) {
    if (typeof toast === 'function') toast(msg, type || 'info');
  }

  // ───────────────────────── 渲染入口 ─────────────────────────
  function render(rootId) {
    var root = document.getElementById(rootId);
    if (!root) return;
    if (unTick) { try { unTick(); } catch (e) {} unTick = null; }
    currentSegments = [];
    currentMeta = {};
    segPlayerNames = [];

    // 1) 外壳：标题 + 赛季/比赛选择 + 挂载点
    root.innerHTML = buildShell();

    // 2) 挂载战术板播放引擎（clutch 模式：仅球场 + 控制条 + 侧栏/高亮插槽）
    if (window.Tactics && typeof window.Tactics.render === 'function') {
      window.Tactics.render('clutchPlayerMount', 'clutch');
    } else {
      var mount = document.getElementById('clutchPlayerMount');
      if (mount) mount.innerHTML = '<div class="card" style="padding:20px;color:var(--danger)">播放引擎未加载</div>';
      return;
    }

    bindHeader();
    initSeasons();
  }

  function buildShell() {
    return (
      '<div class="page-header">' +
        '<h2>融合关键时刻回放 <span style="font-size:13px;color:var(--text-dim);">Fusion Clutch Replay</span></h2>' +
        '<div class="form-row">' +
          '<label class="label">赛季</label>' +
          '<select class="select" id="crSeason"></select>' +
          '<label class="label">比赛</label>' +
          '<select class="select" id="crGame"></select>' +
          '<button class="btn btn-primary" id="crLoad">加载融合回放</button>' +
        '</div>' +
        '<div id="crMeta" class="tactics-meta" style="margin-top:6px;"></div>' +
      '</div>' +
      '<div id="clutchPlayerMount"></div>'
    );
  }

  // ───────────────────────── 头部交互 ─────────────────────────
  function bindHeader() {
    var seasonSel = document.getElementById('crSeason');
    var gameSel = document.getElementById('crGame');
    var loadBtn = document.getElementById('crLoad');
    if (seasonSel) seasonSel.onchange = function () { loadGamesInto(gameSel, seasonSel.value); };
    if (loadBtn) loadBtn.onclick = loadReplay;
  }

  function initSeasons() {
    var seasonSel = document.getElementById('crSeason');
    if (!seasonSel) return;
    seasonSel.innerHTML = SEASONS.map(function (s) {
      return '<option value="' + s + '">' + s + '-' + String(s + 1).slice(-2) + '</option>';
    }).join('');
    seasonSel.value = '2025';
    loadGamesInto(document.getElementById('crGame'), '2025');
  }

  function loadGamesInto(gameSel, season) {
    if (!gameSel) return;
    api('/clutch-replay/games?season=' + encodeURIComponent(season))
      .then(function (r) {
        var games = (r && r.data) || [];
        if (!games.length) {
          gameSel.innerHTML = '<option value="">该季暂无回放数据</option>';
          return;
        }
        gameSel.innerHTML = games.map(function (g) {
          var teams = (g.teams || []).join(' vs ');
          return '<option value="' + eh(g.game_id) + '">' + eh(teams) + ' · ' + g.event_count + '事件</option>';
        }).join('');
      })
      .catch(function () {
        gameSel.innerHTML = '<option value="">加载比赛失败</option>';
      });
  }

  // ───────────────────────── 取数 + 装配 ─────────────────────────
  function loadReplay() {
    var gameSel = document.getElementById('crGame');
    var seasonSel = document.getElementById('crSeason');
    var metaEl = document.getElementById('crMeta');
    if (!gameSel || !seasonSel) return;
    var gid = gameSel.value;
    var season = seasonSel.value;
    if (!gid) { toastSafe('请选择比赛', 'info'); return; }
    if (metaEl) metaEl.innerHTML = '加载中…';

    api('/clutch-replay/replay', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: gid, season: season, frame_rate: 30 }),
    }).then(function (r) {
      if (!r || r.code !== 0) {
        var msg = (r && r.message) || '加载失败';
        if (metaEl) metaEl.innerHTML = '⚠ ' + eh(msg);
        toastSafe(msg, 'error');
        return;
      }
      var data = r.data || {};
      currentMeta = data.meta || {};
      currentSegments = data.clutch_segments || [];

      // 注入帧序列并启动播放引擎
      window.Tactics.setFrames(data.frames || [], data.meta || {});
      drawSidebar(data.clutch_players || []);
      drawHighlights(currentSegments, currentMeta);

      // 注册每帧回调，联动高亮段与侧栏
      if (unTick) { try { unTick(); } catch (e) {} }
      unTick = window.Tactics.onTick(onPlayerTick);

      if (metaEl) {
        metaEl.innerHTML =
          '关键时刻片段 <b>' + currentSegments.length + '</b> · 球员 <b>' +
          (data.clutch_players ? data.clutch_players.length : 0) + '</b>' +
          (currentSegments.length === 0 ? '（本场无 br_crawler 内关键时刻数据）' : '');
      }
    }).catch(function (e) {
      if (metaEl) metaEl.innerHTML = '⚠ ' + eh(e.message || '加载失败');
      toastSafe(e.message || '加载失败', 'error');
    });
  }

  // ───────────────────────── 侧栏（clutch 球员榜）─────────────────────────
  function drawSidebar(players) {
    var sb = document.getElementById('tacticsClutchSidebar');
    if (!sb) return;
    if (!players.length) {
      sb.innerHTML = '<div class="card-title">关键时刻球员</div><div class="clutch-empty">本场无 clutch 数据</div>';
      return;
    }
    var rows = players.map(function (p, i) {
      var fg = p.fg_pct != null ? p.fg_pct.toFixed(1) + '%' : '—';
      var fg3 = p.fg3_pct != null ? p.fg3_pct.toFixed(1) + '%' : '—';
      var cov = p.dribble_coverage != null ? p.dribble_coverage.toFixed(1) + '%' : '—';
      return (
        '<div class="clutch-player-row" data-name="' + eh(p.player_name) + '">' +
          '<div class="clutch-player-head">' +
            '<span class="clutch-player-name">' + eh(p.player_name) + '</span>' +
            '<span class="clutch-player-team">' + eh(p.team || '') + '</span>' +
          '</div>' +
          '<div class="clutch-player-stats">' +
            stat('回合', p.poss) + stat('得分', p.pts) + stat('FG%', fg) +
            stat('3P%', fg3) + stat('助攻', p.ast) + stat('篮板', (p.oreb + p.dreb)) +
            stat('抢断', p.stl) + stat('失误', p.tov) + stat('运投占比', cov) +
          '</div>' +
        '</div>'
      );
    }).join('');
    sb.innerHTML = '<div class="card-title">关键时刻球员榜</div>' + rows;
  }

  function stat(label, val) {
    return '<span class="clutch-stat"><i>' + eh(label) + '</i>' + eh(val) + '</span>';
  }

  // ───────────────────────── Timeline 高亮轨道 ─────────────────────────
  function drawHighlights(segments, meta) {
    var track = document.getElementById('tacticsClutchTrack');
    if (!track) return;
    track.innerHTML = '';
    var fc = (meta && meta.frame_count) || 0;
    if (!fc) return;
    segPlayerNames = [];

    segments.forEach(function (seg, i) {
      var left = (seg.start_frame / (fc - 1)) * 100;
      var right = (seg.end_frame / (fc - 1)) * 100;
      var w = Math.max(0.8, right - left);
      var div = document.createElement('div');
      div.className = 'clutch-seg';
      div.style.left = left + '%';
      div.style.width = w + '%';
      div.title = '第' + seg.period + '节 · 剩 ' + seg.clock_start.toFixed(0) + 's · 分差 ' + seg.margin +
        ' · ' + (seg.players || []).map(function (p) { return p.player; }).join('、');
      div.onclick = function (e) {
        e.stopPropagation();
        window.Tactics.seekFrame(seg.start_frame);
        window.Tactics.play();
        highlightActive(i);
      };
      track.appendChild(div);
      segPlayerNames.push((seg.players || []).map(function (p) { return p.player; }));
    });

    // 点击轨道空白处按比例跳转（细粒度 scrub 仍由 range 负责）
    track.onclick = function (e) {
      if (e.target === track && fc > 1) {
        var rect = track.getBoundingClientRect();
        var frac = (e.clientX - rect.left) / rect.width;
        window.Tactics.seekProgress(frac);
      }
    };
  }

  // ───────────────────────── 播放联动 ─────────────────────────
  function onPlayerTick(idx) {
    var fc = currentMeta.frame_count || 0;
    if (!fc) return;
    var active = -1;
    for (var i = 0; i < currentSegments.length; i++) {
      var s = currentSegments[i];
      if (idx >= s.start_frame && idx <= s.end_frame) { active = i; break; }
    }
    highlightActive(active);
  }

  function highlightActive(activeIdx) {
    // 高亮轨道片段
    var segs = document.querySelectorAll('#tacticsClutchTrack .clutch-seg');
    for (var i = 0; i < segs.length; i++) {
      segs[i].classList.toggle('clutch-seg-active', i === activeIdx);
    }
    // 联动侧栏球员行
    var names = (activeIdx >= 0 && segPlayerNames[activeIdx]) ? segPlayerNames[activeIdx] : [];
    var rows = document.querySelectorAll('#tacticsClutchSidebar .clutch-player-row');
    rows.forEach(function (row) {
      var nm = row.getAttribute('data-name') || '';
      row.classList.toggle('clutch-player-active', names.indexOf(nm) >= 0);
    });
  }

  // ── Public API ──
  window.ClutchReplay = { render: render };
})();
