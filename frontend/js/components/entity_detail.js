/* NBACore Studio v8 — Entity Detail Pages (Player / Team dedicated views)
 * Layer 4: Pure Render. Talks to the v8 entity endpoints and renders an
 * overlay. Relies on globals from app.js: api(), escapeHtml(), seasonLabel(),
 * toast(), I18N, API_BASE.
 */
(function () {
  'use strict';

  const GRANS = ['season', 'month', 'week', 'game'];

  let entityState = { type: null, id: null, season: null };
  let _teamRadarChart = null;

  function currentSeason() {
    const el = document.getElementById('seasonSelect');
    return el && el.value ? parseInt(el.value, 10) : 2025;
  }

  function entityLink(type, id, label, extraClass) {
    const t = escapeHtml(type || '');
    const i = escapeHtml(id == null ? '' : String(id));
    const l = escapeHtml(label == null ? '' : String(label));
    const cls = 'entity-link' + (extraClass ? ' ' + extraClass : '');
    return `<span class="${cls}" data-entity-type="${t}" data-entity-id="${i}" role="button" tabindex="0">${l}</span>`;
  }

  function humanize(key) {
    return String(key).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function fmtVal(v) {
    if (v == null) return '—';
    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2);
    if (typeof v === 'object') {
      try { return JSON.stringify(v).slice(0, 200); } catch { return '[object]'; }
    }
    return String(v);
  }

  function showOverlay() {
    const ov = document.getElementById('entityOverlay');
    if (ov) ov.style.display = 'flex';
  }

  function closeEntityOverlay() {
    const ov = document.getElementById('entityOverlay');
    if (ov) ov.style.display = 'none';
    if (_teamRadarChart) { _teamRadarChart.dispose(); _teamRadarChart = null; }
    document.getElementById('entityOverlayBody').innerHTML = '';
    entityState = { type: null, id: null, season: null };
  }

  function renderKVTable(obj, opts) {
    opts = opts || {};
    const keys = Object.keys(obj || {});
    if (keys.length === 0) return `<div class="entity-empty">${I18N.t('common.noData')}</div>`;
    const rows = keys.map(k => {
      const v = obj[k];
      let body;
      if (v != null && typeof v === 'object' && !Array.isArray(v)) {
        body = renderKVTable(v, { nested: true });
      } else if (Array.isArray(v)) {
        body = `<span class="entity-muted">[${v.length}]</span>`;
      } else {
        body = escapeHtml(fmtVal(v));
      }
      if (opts.nested) return `<div class="entity-kv"><span class="entity-k">${escapeHtml(humanize(k))}</span><span class="entity-v">${body}</span></div>`;
      return `<tr><td class="entity-k">${escapeHtml(humanize(k))}</td><td class="entity-v">${body}</td></tr>`;
    }).join('');
    return opts.nested
      ? `<div class="entity-kv-grid">${rows}</div>`
      : `<table class="tbl entity-tbl"><tbody>${rows}</tbody></table>`;
  }

  function renderSeasonsChips(type, id, seasons) {
    if (!seasons || seasons.length === 0) return `<div class="entity-empty">${I18N.t('common.noData')}</div>`;
    return `<div class="entity-chips">` + seasons.map(s => {
      const label = s.label || seasonLabel(s.season);
      return `<span class="entity-chip" role="button" tabindex="0" data-entity-type="${escapeHtml(type)}" data-entity-id="${escapeHtml(id)}" data-season="${s.season}">${escapeHtml(label)}</span>`;
    }).join('') + `</div>`;
  }

  function renderGameGroups(groups, totals) {
    const totalLine = totals
      ? `<div class="entity-games-total">GP ${totals.gp} · 场均 ${totals.pts != null ? totals.pts : '—'} 分 · FG% ${totals.fg_pct != null ? totals.fg_pct : '—'}%</div>`
      : '';
    if (!groups || groups.length === 0) {
      return totalLine + `<div class="entity-empty">${I18N.t('common.noData')}</div>`;
    }
    const blocks = groups.map(g => {
      const agg = g.aggregate || {};
      const head = `<div class="entity-group-head">
        <span class="entity-group-label">${escapeHtml(g.label)}</span>
        <span class="entity-group-agg">GP ${agg.gp} · 场均 ${agg.pts != null ? agg.pts : '—'} · FG% ${agg.fg_pct != null ? agg.fg_pct : '—'}%</span>
      </div>`;
      const rows = (g.games || []).map(gm => {
        const res = gm.result === 'W' ? 'w' : (gm.result === 'L' ? 'l' : 't');
        const ha = gm.is_home ? 'VS' : '@';
        return `<tr>
          <td class="entity-game-date">${escapeHtml(gm.game_date || '—')}</td>
          <td>${ha} ${escapeHtml(gm.opponent || '—')}</td>
          <td class="entity-res entity-res-${res}">${escapeHtml(gm.result || '—')}</td>
          <td class="entity-pts">${gm.pts != null ? gm.pts : '—'}</td>
        </tr>`;
      }).join('');
      return `<div class="entity-group">
        ${head}
        <table class="tbl entity-tbl entity-games-tbl">
          <thead><tr><th>日期</th><th>对手</th><th>结果</th><th style="text-align:right;">得分</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    }).join('');
    return totalLine + blocks;
  }

  function granularityBar(type, id, season, granularity) {
    const btns = GRANS.map(g =>
      `<span class="entity-gran ${g === granularity ? 'active' : ''}" role="button" tabindex="0" data-gran="${g}" data-entity-type="${escapeHtml(type)}" data-entity-id="${escapeHtml(id)}" data-season="${season}">${g}</span>`
    ).join('');
    return `<div class="entity-gran-bar">${btns}</div>`;
  }

  async function openEntityDetail(type, id, season) {
    if (type === 'team' && season == null) {
      const ts = document.getElementById('teamsSeasonSelect');
      if (ts && ts.value) season = Number(ts.value);
    }
    entityState = { type, id, season: season != null ? season : currentSeason() };
    const body = document.getElementById('entityOverlayBody');
    showOverlay();
    body.innerHTML = `<div class="entity-loading"><div class="spinner"></div> ${I18N.t('common.loading')}</div>`;
    try {
      let data;
      if (type === 'player') {
        data = await api(`/players/${encodeURIComponent(id)}/detail?season=${entityState.season}`);
        renderPlayerDetail(data);
      } else {
        const [data, leagueRadarResp] = await Promise.all([
          api(`/teams/${encodeURIComponent(id)}/detail?season=${entityState.season}`),
          api(`/teams/league-avg/radar?season=${entityState.season}`).catch(() => null),
        ]);
        renderTeamDetail(data);
        const leagueAvg = leagueRadarResp && leagueRadarResp.data ? leagueRadarResp.data : null;
        renderEntityTeamRadar(data.radar, leagueAvg);
      }
    } catch (e) {
      body.innerHTML = `<div class="entity-error">${escapeHtml(e.message)}</div>`;
    }
  }

  function renderPlayerDetail(d) {
    const bio = d.bio || {};
    const name = bio.full_name || bio.player_name || entityState.id;
    const sub = [bio.team_abbr || bio.team, bio.position].filter(Boolean).join(' · ');
    const metricsHtml = renderKVTable(d.metrics || {});
    const seasonsHtml = renderSeasonsChips('player', entityState.id, d.seasons || []);
    const body = document.getElementById('entityOverlayBody');
    body.innerHTML = `
      <div class="entity-detail">
        <div class="entity-detail-head">
          <div>
            <div class="entity-name">${escapeHtml(name)}</div>
            <div class="entity-sub">${escapeHtml(sub)} · ${seasonLabel(d.season)}</div>
          </div>
        </div>

        <div class="entity-section">
          <div class="entity-section-title">${I18N.t('common.metrics')}</div>
          ${metricsHtml}
        </div>

        <div class="entity-row-2">
          <div class="entity-section">
            <div class="entity-section-title">投篮档案</div>
            ${renderKVTable(d.shooting || {})}
          </div>
          <div class="entity-section">
            <div class="entity-section-title">防守生涯</div>
            ${renderKVTable(d.defense || {})}
          </div>
        </div>

        <div class="entity-section">
          <div class="entity-section-title">球员情报</div>
          ${renderKVTable(d.intelligence || {})}
        </div>

        <div class="entity-section">
          <div class="entity-section-title">赛季（点击切换数据）</div>
          ${seasonsHtml}
          <div style="margin-top:10px;">
            <button class="entity-btn" data-entity-games="1" data-entity-type="${escapeHtml(entityState.type)}" data-entity-id="${escapeHtml(entityState.id)}" data-season="${entityState.season}">查看 ${seasonLabel(entityState.season)} 比赛</button>
          </div>
        </div>
      </div>`;
  }

  function renderTeamDetail(d) {
    const name = d.team_name || entityState.id;
    const standingsHtml = renderKVTable(d.standings || {});
    const statsHtml = renderKVTable(d.stats || {});
    const radarHtml = renderKVTable(d.radar || {});
    const trendHtml = (d.trend && d.trend.length)
      ? `<table class="tbl entity-tbl"><thead><tr><th>赛季</th><th style="text-align:right;">得分</th><th style="text-align:right;">+/-</th><th style="text-align:right;">场数</th></tr></thead><tbody>`
        + d.trend.map(t => `<tr><td>${t.season}</td><td style="text-align:right;">${fmtVal(t.pts)}</td><td style="text-align:right;">${fmtVal(t.plus_minus)}</td><td style="text-align:right;">${fmtVal(t.games)}</td></tr>`).join('')
        + `</tbody></table>`
      : `<div class="entity-empty">${I18N.t('common.noData')}</div>`;
    const seasonsHtml = renderSeasonsChips('team', entityState.id, d.seasons || []);
    // Season selector dropdown (built from available seasons)
    const seasonOptsHtml = (d.seasons || []).map(s =>
      `<option value="${s.season}"${s.season === entityState.season ? ' selected' : ''}>${seasonLabel(s.season)}</option>`
    ).join('');
    const body = document.getElementById('entityOverlayBody');
    body.innerHTML = `
      <div class="entity-detail">
        <div class="entity-detail-head">
          <div>
            <div class="entity-name">${escapeHtml(name)}</div>
            <div class="entity-sub">${escapeHtml(entityState.id)} · ${seasonLabel(d.season)}</div>
          </div>
          <select class="entity-season-select" onchange="openEntityDetail('team','${escapeHtml(entityState.id)}',parseInt(this.value))" title="切换赛季">${seasonOptsHtml}</select>
        </div>

        <div class="entity-row-2">
          <div class="entity-section">
            <div class="entity-section-title">排名 / 战绩</div>
            ${standingsHtml}
          </div>
          <div class="entity-section">
            <div class="entity-section-title">场均数据</div>
            ${statsHtml}
          </div>
        </div>

        <div class="entity-row-2">
          <div class="entity-section entity-section-wide">
            <div class="entity-section-title">雷达图</div>
            <div id="entityTeamRadar" class="entity-radar-chart"></div>
          </div>
          <div class="entity-section">
            <div class="entity-section-title">得分趋势</div>
            ${trendHtml}
          </div>
        </div>

        <div class="entity-section">
          <div class="entity-section-title">赛季（点击切换数据）</div>
          ${seasonsHtml}
          <div style="margin-top:10px;">
            <button class="entity-btn" data-entity-games="1" data-entity-type="${escapeHtml(entityState.type)}" data-entity-id="${escapeHtml(entityState.id)}" data-season="${entityState.season}">查看 ${seasonLabel(entityState.season)} 比赛</button>
          </div>
        </div>
      </div>`;
  }

  function renderEntityTeamRadar(radar, leagueAvg) {
    const el = document.getElementById('entityTeamRadar');
    if (!el) return;
    if (typeof echarts === 'undefined') {
      el.innerHTML = '<div class="entity-radar-empty">雷达图组件未加载</div>';
      return;
    }
    if (_teamRadarChart) { _teamRadarChart.dispose(); _teamRadarChart = null; }
    _teamRadarChart = echarts.init(el);
    const radarData = radar || {};
    const keys = Object.keys(radarData);
    if (keys.length === 0) {
      el.innerHTML = '<div class="entity-radar-empty">' + (window.I18N ? I18N.t('common.noData') : 'No data') + '</div>';
      return;
    }
    const accent = (window.THEME && THEME.accent) ? THEME.accent : '#00b888';
    const info = (window.THEME && THEME.info) ? THEME.info : '#3b82f6';
    const textDim = (window.THEME && THEME.textDim) ? THEME.textDim : '#6b7a99';
    const splitLine = (window.THEME && THEME.splitLine) ? THEME.splitLine : '#2a3142';
    const teamName = entityState.id || '球队';
    const hasLeagueAvg = leagueAvg && Object.keys(leagueAvg).length > 0;

    // Determine max per key from both series
    const teamValues = keys.map(k => Number(radarData[k]) || 0);
    const leagueValues = hasLeagueAvg ? keys.map(k => Number(leagueAvg[k]) || 0) : [];
    const indicator = keys.map((k, i) => ({
      name: humanize(k),
      max: Math.max(1, Math.max(teamValues[i] || 0, leagueValues[i] || 0) * 1.4),
    }));

    const seriesData = [{ value: teamValues, name: teamName, itemStyle: { color: accent }, areaStyle: { color: 'rgba(0,184,138,.2)' }, lineStyle: { width: 2.5 }, symbol: 'circle', symbolSize: 5 }];
    if (hasLeagueAvg) {
      seriesData.push({ value: leagueValues, name: (window.I18N ? I18N.t('teams.leagueAvg') : 'League Avg'), itemStyle: { color: info }, areaStyle: { color: 'rgba(59,130,246,.12)' }, lineStyle: { width: 2, type: 'dashed' }, symbol: 'diamond', symbolSize: 5 });
    }

    _teamRadarChart.setOption({
      tooltip: { trigger: 'item' },
      legend: {
        data: seriesData.map(s => s.name),
        textStyle: { color: textDim, fontSize: 11 },
        bottom: 0,
        left: 'center',
      },
      radar: {
        indicator: indicator,
        axisName: { color: textDim, fontSize: 11 },
        splitArea: { areaStyle: { color: ['rgba(0,184,138,.02)', 'rgba(0,184,138,.05)'] } },
        splitLine: { lineStyle: { color: splitLine } },
        center: ['50%', '52%'],
        radius: '62%',
      },
      series: [{
        type: 'radar',
        data: seriesData,
      }],
    });
  }

  async function openEntityGames(type, id, season, granularity) {
    entityState = { type, id, season };
    const body = document.getElementById('entityOverlayBody');
    showOverlay();
    body.innerHTML = `<div class="entity-back" role="button" tabindex="0" data-back="1">← ${I18N.t('games.backToGames')}</div>
      <div class="entity-loading"><div class="spinner"></div> ${I18N.t('common.loading')}</div>`;
    await loadGames(type, id, season, granularity);
  }

  async function loadGames(type, id, season, granularity) {
    const body = document.getElementById('entityOverlayBody');
    try {
      const data = await api(`/${type === 'player' ? 'players' : 'teams'}/${encodeURIComponent(id)}/games?season=${season}&granularity=${granularity}`);
      const bar = granularityBar(type, id, season, granularity);
      const groups = renderGameGroups(data.groups || [], data.totals || {});
      body.innerHTML = `
        <div class="entity-back" role="button" tabindex="0" data-back="1">← 返回</div>
        <div class="entity-detail-head">
          <div>
            <div class="entity-name">${escapeHtml(id)}</div>
            <div class="entity-sub">${seasonLabel(season)} · ${granularity}</div>
          </div>
        </div>
        ${bar}
        <div class="entity-games">${groups}</div>`;
    } catch (e) {
      body.innerHTML = `<div class="entity-back" role="button" tabindex="0" data-back="1">← 返回</div><div class="entity-error">${escapeHtml(e.message)}</div>`;
    }
  }

  // ── Global delegation (single listener) ──
  function delegate(e) {
    const t = e.target;
    const link = t.closest && t.closest('.entity-link');
    if (link) {
      e.preventDefault();
      e.stopPropagation();
      openEntityDetail(link.dataset.entityType, link.dataset.entityId);
      return;
    }
    const chip = t.closest && t.closest('.entity-chip');
    if (chip) {
      e.preventDefault();
      openEntityDetail(chip.dataset.entityType, chip.dataset.entityId, parseInt(chip.dataset.season, 10));
      return;
    }
    const gamesBtn = t.closest && t.closest('[data-entity-games]');
    if (gamesBtn) {
      e.preventDefault();
      openEntityGames(gamesBtn.dataset.entityType, gamesBtn.dataset.entityId, parseInt(gamesBtn.dataset.season, 10), 'month');
      return;
    }
    const gran = t.closest && t.closest('.entity-gran');
    if (gran) {
      e.preventDefault();
      loadGames(gran.dataset.entityType, gran.dataset.entityId, parseInt(gran.dataset.season, 10), gran.dataset.gran);
      return;
    }
    const back = t.closest && t.closest('[data-back]');
    if (back) {
      e.preventDefault();
      openEntityDetail(entityState.type, entityState.id, entityState.season);
      return;
    }
  }

  if (!window.__entityDelegateBound) {
    document.addEventListener('click', delegate);
    document.addEventListener('change', onSeasonChange);
    window.__entityDelegateBound = true;
  }

  function onSeasonChange(e) {
    if (e.target && e.target.id === 'seasonSelect' && entityState.type) {
      openEntityDetail(entityState.type, entityState.id, currentSeason());
    }
  }

  // Expose
  window.entityLink = entityLink;
  window.openEntityDetail = openEntityDetail;
  window.openEntityGames = openEntityGames;
  window.closeEntityOverlay = closeEntityOverlay;
})();
