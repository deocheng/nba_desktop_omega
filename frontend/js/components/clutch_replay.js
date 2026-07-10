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
  var timelineHandle = null;  // window.ClutchReplay.Timeline.mount 返回的句柄

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
    timelineHandle = null;

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

      // 经锁定共享契约 Timeline.mount 渲染高亮轨道（DRY；录像库 video_library.js 亦复用同一组件）
      segPlayerNames = currentSegments.map(function (seg) {
        return (seg.players || []).map(function (p) { return p.player; });
      });
      timelineHandle = window.ClutchReplay.Timeline.mount(
        document.getElementById('tacticsClutchTrack'),
        {
          segments: currentSegments,
          frameCount: currentMeta.frame_count || 0,
          onSeek: function (p, idx) {
            var fc = currentMeta.frame_count || 0;
            if (!fc) return;
            var frameIndex = Math.round((p / 1000) * Math.max(1, fc - 1));
            window.Tactics.seekFrame(frameIndex);
            if (idx >= 0) { window.Tactics.play(); highlightActive(idx); }
          },
        }
      );

      // 注册每帧回调，联动高亮段（setProgress）与侧栏
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

  // ───────────────────────── 可复用 Timeline 高亮组件（锁定共享契约 §3.2 / §8.6）─────────────────────────
  // 单一事实源：融合页自身经 mount 消费；录像库 video_library.js 经 SyncController 复用同一组件，不重造。
  // 接口：mount(containerEl, {segments, frameCount, onSeek}) → { setProgress(p), onSeek(cb) }
  //   - 归一化空间恒为 0–1000（p）：组件只发 p、只收 p，零帧算术（帧↔p 换算交由消费者）。
  //   - onSeek 与 handle.onSeek(cb) 均为「追加注册」语义（多监听者并存，互不覆盖）。
  //   - setProgress(p) 仅用于外部反向同步游标，不触发 onSeek（避免回环）。
  var Timeline = (function () {
    function mount(containerEl, opts) {
      opts = opts || {};
      var segments = opts.segments || [];
      var frameCount = opts.frameCount || 0;
      var seekCbs = [];                  // 追加注册的 onSeek 监听者
      if (typeof opts.onSeek === 'function') seekCbs.push(opts.onSeek);

      var noop = { setProgress: function () {}, onSeek: function () {} };
      if (!containerEl) return noop;
      containerEl.innerHTML = '';
      if (!frameCount) return noop;

      var maxFrame = Math.max(1, frameCount - 1);   // 防 0 除
      var toPct = function (p) { return (p / 1000) * 100; };

      // 1) 渲染高亮段：投影 start_frame / end_frame → 0–1000 → 百分比定位
      segments.forEach(function (seg, i) {
        var leftP = (seg.start_frame / maxFrame) * 1000;
        var rightP = (seg.end_frame / maxFrame) * 1000;
        var wP = Math.max(8, rightP - leftP);        // 最小宽度，保证可点（8/1000 ≈ 0.8%）
        var div = document.createElement('div');
        div.className = 'clutch-seg';
        div.style.left = toPct(leftP) + '%';
        div.style.width = toPct(wP) + '%';
        div.title = '第' + seg.period + '节 · 剩 ' + seg.clock_start.toFixed(0) + 's · 分差 ' + seg.margin +
          ' · ' + (seg.players || []).map(function (p) { return p.player; }).join('、');
        var segP = leftP;                            // 段代表 p（取段起点，0–1000）
        div.onclick = function (e) {
          e.stopPropagation();
          for (var k = 0; k < seekCbs.length; k++) {
            try { seekCbs[k](segP, i); } catch (err) { /* 隔离单个监听者异常 */ }
          }
        };
        containerEl.appendChild(div);
      });

      // 2) 点击轨道空白处按比例跳转（同样只发 p，0–1000）
      containerEl.onclick = function (e) {
        if (e.target === containerEl && frameCount > 1) {
          var rect = containerEl.getBoundingClientRect();
          var frac = (e.clientX - rect.left) / rect.width;
          var p = Math.max(0, Math.min(1000, frac * 1000));
          for (var k = 0; k < seekCbs.length; k++) {
            try { seekCbs[k](p, -1); } catch (err) { /* 隔离单个监听者异常 */ }
          }
        }
      };

      // 3) setProgress(p)：外部（<video> 进度 / Tactics 每帧）反向同步游标，仅高亮命中段；
      //    不触发 onSeek（避免回环）。p ∈ [0,1000]，亦容错接受 [0,1]。
      function setProgress(p) {
        var pp = (p > 1) ? p : (p * 1000);
        pp = Math.max(0, Math.min(1000, pp));
        var active = -1;
        for (var i = 0; i < segments.length; i++) {
          var leftP = (segments[i].start_frame / maxFrame) * 1000;
          var rightP = (segments[i].end_frame / maxFrame) * 1000;
          if (pp >= leftP && pp <= rightP) { active = i; break; }
        }
        var segs = containerEl.querySelectorAll('.clutch-seg');
        for (var j = 0; j < segs.length; j++) {
          segs[j].classList.toggle('clutch-seg-active', j === active);
        }
      }

      // 4) onSeek(cb)：追加注册回调（不覆盖既有监听者）
      function onSeek(cb) {
        if (typeof cb === 'function') seekCbs.push(cb);
      }

      return { setProgress: setProgress, onSeek: onSeek };
    }

    return { mount: mount };
  })();

  // ───────────────────────── 播放联动 ─────────────────────────
  function onPlayerTick(idx) {
    var fc = currentMeta.frame_count || 0;
    if (!fc) return;
    var active = -1;
    for (var i = 0; i < currentSegments.length; i++) {
      var s = currentSegments[i];
      if (idx >= s.start_frame && idx <= s.end_frame) { active = i; break; }
    }
    // 反向同步 Timeline 高亮（p ∈ [0,1000]，setProgress 不触发 onSeek）
    if (timelineHandle) timelineHandle.setProgress((idx / Math.max(1, fc - 1)) * 1000);
    highlightActive(active);
  }

  function highlightActive(activeIdx) {
    // 联动侧栏球员行（轨道高亮由 Timeline.mount 的 setProgress 负责）
    var names = (activeIdx >= 0 && segPlayerNames[activeIdx]) ? segPlayerNames[activeIdx] : [];
    var rows = document.querySelectorAll('#tacticsClutchSidebar .clutch-player-row');
    rows.forEach(function (row) {
      var nm = row.getAttribute('data-name') || '';
      row.classList.toggle('clutch-player-active', names.indexOf(nm) >= 0);
    });
  }

  // ── Public API ──
  window.ClutchReplay = { render: render, Timeline: Timeline };
})();
