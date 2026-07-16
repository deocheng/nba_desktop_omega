/**
 * NBACore Studio v8 — Frontend VS System
 * ========================================
 * Layer 4: Pure Render Only
 * - No computation, no aggregation, no filtering logic
 * - All data fetched from API endpoints (Layer 3)
 * - ECharts for chart rendering (mature library, v8 §2.4)
 */

// ── API Config ──
const API_BASE = '';

// ── Theme Colors (Light) ──
const THEME = {
  accent: '#00b88a',
  accentDim: '#009670',
  border: '#e1e8f0',
  borderLight: '#d0d9e4',
  splitLine: '#e8edf3',
  text: '#2c3e50',
  textDim: '#7f8c9b',
  axisLine: '#cbd5e1',
  info: '#3b82f6',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  purple: '#8b5cf6',
  cyan: '#06b6d4',
  orange: '#f97316',
};

async function api(path, opts) {
  try {
    const r = await fetch(API_BASE + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `HTTP ${r.status}`);
    }
    return r.json();
  } catch (e) {
    console.error('[API]', path, e);
    throw e;
  }
}

// ── State ──
let currentPage = 'vs';
let allMetrics = [];
let selectedMetrics = new Set();
let player1 = null;
let player2 = null;
let charts = {};
let searchTimeouts = {};

function resizeAllCharts() {
  Object.values(charts).forEach(chart => {
    if (chart && typeof chart.resize === 'function') {
      chart.resize();
    }
  });
}

let resizeTimer = null;
window.addEventListener('resize', () => {
  if (resizeTimer) clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resizeAllCharts, 150);
});

// Teams page state
let currentTeam = null;
let currentTeamAbbr = null;

// Games page state
let gamesPage = 1;
let gamesTotalPages = 1;

// System page state
let currentSysTable = null;
let sysDataPage = 1;
let sysDataTotalPages = 1;

// ── Toast ──
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Navigation ──
function nav(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach(e => {
    e.classList.toggle('active', e.dataset.page === page);
  });
  document.querySelectorAll('.page').forEach(e => e.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  if (page === 'rankings') loadRankingsPage();
  if (page === 'context') loadContextPage();
  if (page === 'teams') loadTeamsPage();
  if (page === 'games') loadGamesPage();
  if (page === 'system') loadSystemPage();
  if (page === 'crawler') loadCrawlerPage();
  if (page === 'dataimport') loadDataImportPage();
  if (page === 'intelligence') loadIntelligencePage();
  if (page === 'workspace') loadWorkspacePage();
  if (page === 'clutch') loadClutchPage();
  if (page === 'peak') loadPeakPage();
  if (page === 'age-curve') loadAgeCurvePage();
  if (page === 'similar-evolution') loadSimilarEvoPage();
  if (page === 'trade') loadTradePage();
  if (page === 'tactics') loadTacticsPage();
  if (page === 'clutch-replay') loadClutchReplayPage();
  if (page === 'video-library') loadVideoLibraryPage();
  if (page === 'cba') loadCbaPage();
  if (page === 'draft') loadDraftPage();
  setTimeout(resizeAllCharts, 50);
}

// ── Clutch Page ──
function loadClutchPage() {
  if (window.Clutch && typeof window.Clutch.render === 'function') {
    window.Clutch.render('clutchRoot');
  }
}

// ── Peak Page (v8.2-C) ──
function loadPeakPage() {
  if (window.Peak && typeof window.Peak.render === 'function') {
    window.Peak.render('peakRoot');
  }
}

// ── Age Curve Page (v8.2-C) ──
function loadAgeCurvePage() {
  if (window.AgeCurve && typeof window.AgeCurve.render === 'function') {
    window.AgeCurve.render('ageCurveRoot');
  }
}

// ── Similar Evolution Page (v8.2-C) ──
function loadSimilarEvoPage() {
  if (window.SimilarEvo && typeof window.SimilarEvo.render === 'function') {
    window.SimilarEvo.render('similarEvoRoot');
  }
}

// ── Trade Simulator Page ──
function loadTradePage() {
  if (window.Trade && typeof window.Trade.render === 'function') {
    window.Trade.render('tradeRoot');
  }
}

// ── Tactics Board Page ──
function loadTacticsPage() {
  if (window.Tactics && typeof window.Tactics.render === 'function') {
    window.Tactics.render('tacticsRoot');
  }
}

// ── Clutch Replay (Fusion) Page ──
function loadClutchReplayPage() {
  if (window.ClutchReplay && typeof window.ClutchReplay.render === 'function') {
    window.ClutchReplay.render('clutchReplayRoot');
  }
}

// ── Video Library Page ──
function loadVideoLibraryPage() {
  if (window.VideoLibrary && typeof window.VideoLibrary.renderList === 'function') {
    window.VideoLibrary.renderList('videoLibraryRoot');
  }
}

// ── CBA Aux Page (v8.3.2+ · T01/T02) ──
function loadCbaPage() {
  if (window.Cba && typeof window.Cba.render === 'function') {
    window.Cba.render('cbaRoot');
  }
}

// ── Draft History Page (A1-4: BR-link graceful degradation) ──
// Read-only render of /draft/history. No aggregation / coordinate math — the
// backend returns weight (A2 JOIN-at-read) + an in_dim_players flag that tells
// us whether the player's BBR id resolves to a master player. When it does not,
// we render "无资料" instead of a clickable dead BR link.
let currentDraftSeason = null;

function populateDraftSeasons() {
  const sel = document.getElementById('draftSeasonSelect');
  if (!sel || sel.children.length > 0) return;
  const thisYear = new Date().getFullYear();
  const opts = [];
  for (let y = thisYear; y >= 1947; y--) {
    opts.push(`<option value="${y}">${y}</option>`);
  }
  sel.innerHTML = opts.join('');
  sel.value = String(thisYear);
}

function loadDraftPage() {
  populateDraftSeasons();
  const sel = document.getElementById('draftSeasonSelect');
  const season = sel ? Number(sel.value) : null;
  currentDraftSeason = season;

  const tbody = document.getElementById('draftTableBody');
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:30px; color:var(--text-dim);">
      <div class="spinner"></div> ${I18N.t('draft.loading')}
    </td></tr>`;
  }

  let url = '/draft/history?limit=5000';
  if (season) {
    url += '&season=' + season;
  }

  api(url).then(d => renderDraft(d)).catch(e => {
    const tb = document.getElementById('draftTableBody');
    if (tb) {
      tb.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:30px; color:var(--danger);">
        ${I18N.t('draft.failedToLoad')}: ${escapeHtml(e.message)}
      </td></tr>`;
    }
  });
}

function renderDraft(data) {
  const tbody = document.getElementById('draftTableBody');
  if (!tbody) return;
  const rows = (data && data.rows) || [];
  const countEl = document.getElementById('draftCount');
  if (countEl) countEl.textContent = (data && data.count != null ? data.count : rows.length);

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:30px; color:var(--text-dim);">
      ${I18N.t('common.noData')}
    </td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const pid = r.player_id || '';
    const name = escapeHtml(r.player_name || r.player_name_orig || pid || I18N.t('common.unknown'));
    const round = r.round != null ? r.round : '—';
    const pick = r.pick_overall != null ? r.pick_overall : '—';
    const team = escapeHtml(r.team_abbr || '—');
    const wLbs = (r.weight_lbs != null) ? r.weight_lbs : '—';
    const wKg = (r.weight_kg != null) ? r.weight_kg : '—';
    const wSpan = (r.wingspan_cm != null) ? r.wingspan_cm : '—';

    // A1-4: degrade BR link to "无资料" when player not in dim_players.
    let brCell;
    if (r.in_dim_players) {
      const brUrl = 'https://www.basketball-reference.com/players/'
        + encodeURIComponent(pid.charAt(0).toLowerCase())
        + '/' + encodeURIComponent(pid.toLowerCase()) + '.html';
      brCell = `<a href="${brUrl}" target="_blank" rel="noopener" style="color:var(--accent); text-decoration:none;">↗ BR</a>`;
    } else {
      brCell = `<span class="badge badge-dim" style="background:var(--bg-dark); color:var(--text-dim);">${I18N.t('draft.noData')}</span>`;
    }

    return `<tr>
      <td>${r.season != null ? r.season : '—'}</td>
      <td style="text-align:center;">${round}</td>
      <td style="text-align:right; font-family:var(--mono);">${pick}</td>
      <td><span class="badge badge-blue">${team}</span></td>
      <td style="font-weight:600;">${name}</td>
      <td style="text-align:right; font-family:var(--mono);">${wLbs}</td>
      <td style="text-align:right; font-family:var(--mono);">${wKg}</td>
      <td style="text-align:right; font-family:var(--mono);">${wSpan}</td>
      <td style="text-align:center;">${brCell}</td>
    </tr>`;
  }).join('');
}

// ── Server Status ──
async function checkServerStatus() {
  const dot = document.querySelector('.status-dot');
  const text = document.querySelector('.status-text');
  try {
    const r = await api('/health');
    if (r.database_connected) {
      dot.className = 'status-dot ready';
      text.textContent = I18N.t('serverStatus.serverDbReady');
    } else {
      dot.className = 'status-dot error';
      text.textContent = I18N.t('serverStatus.dbOffline');
    }
  } catch {
    dot.className = 'status-dot error';
    text.textContent = I18N.t('serverStatus.offline');
  }
}

// ── Season Selector ──
function seasonLabel(s) {
  const start = s - 1;
  const end = s % 100;
  return `${start}-${end < 10 ? '0' + end : end}`;
}

async function initSeasonSelectors() {
  try {
    const seasons = await api('/players/seasons');
    const opts = seasons.map(s => `<option value="${s}">${seasonLabel(s)}</option>`).join('');
    const sel2025 = seasons.includes(2025) ? 2025 : seasons[0];
    document.getElementById('seasonSelect').innerHTML = opts;
    document.getElementById('seasonSelect').value = sel2025;
    document.getElementById('rankSeasonSelect').innerHTML = opts;
    document.getElementById('rankSeasonSelect').value = sel2025;
    document.getElementById('ctxSeasonSelect').innerHTML = opts;
    document.getElementById('ctxSeasonSelect').value = sel2025;
    document.getElementById('teamsSeasonSelect').innerHTML = opts;
    document.getElementById('teamsSeasonSelect').value = sel2025;
    document.getElementById('gamesSeasonSelect').innerHTML = opts;
    document.getElementById('gamesSeasonSelect').value = sel2025;
    document.getElementById('sysSeasonSelect').innerHTML = opts;
    document.getElementById('sysSeasonSelect').value = sel2025;
  } catch (e) {
    // Fallback: hardcode common seasons
    const fallback = [2025, 2024, 2023];
    const opts = fallback.map(s => `<option value="${s}">${seasonLabel(s)}</option>`).join('');
    document.getElementById('seasonSelect').innerHTML = opts;
    document.getElementById('rankSeasonSelect').innerHTML = opts;
    document.getElementById('ctxSeasonSelect').innerHTML = opts;
    document.getElementById('teamsSeasonSelect').innerHTML = opts;
    document.getElementById('gamesSeasonSelect').innerHTML = opts;
    document.getElementById('sysSeasonSelect').innerHTML = opts;
  }
}

function onSeasonChange() {
  // If both players selected, re-compare for new season
  if (player1 && player2 && selectedMetrics.size > 0) {
    runCompare();
  }
}

// ── Player Search ──
function searchPlayer(slot) {
  const input = document.getElementById('player' + slot + 'Search');
  const query = input.value.trim();
  clearTimeout(searchTimeouts[slot]);
  if (query.length < 2) {
    hideDropdown(slot);
    return;
  }
  searchTimeouts[slot] = setTimeout(async () => {
    try {
      const d = await api('/players?name=' + encodeURIComponent(query) + '&limit=10');
      const dd = document.getElementById('player' + slot + 'Dropdown');
      if (!d.players || d.players.length === 0) {
        dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">' + I18N.t('common.noResults') + '</div>';
      } else {
        dd.innerHTML = d.players.map(p => {
          const team = p.team_abbr || p.team || '';
          const pos = p.position || '';
          const sub = [team, pos].filter(Boolean).join(' · ');
          const pname = escapeHtml(p.full_name || p.player_name || '');
          const pid = escapeHtml(p.player_id || '');
          return `<div class="dropdown-item" onmousedown="selectPlayer(${slot}, '${pid}')">
            <div>${pname}</div>
            ${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ''}
          </div>`;
        }).join('');
      }
      showDropdown(slot);
    } catch (e) {
      toast(e.message, 'error');
    }
  }, 300);
}

function showDropdown(slot) {
  const input = document.getElementById('player' + slot + 'Search');
  if (input.value.trim().length >= 2) {
    document.getElementById('player' + slot + 'Dropdown').classList.add('show');
  }
}

function hideDropdown(slot) {
  document.getElementById('player' + slot + 'Dropdown').classList.remove('show');
}

function hideDropdownDelay(slot) {
  setTimeout(() => hideDropdown(slot), 200);
}

// ── Player Selection ──
async function selectPlayer(slot, playerId) {
  const season = document.getElementById('seasonSelect').value;
  try {
    const d = await api('/players/' + playerId + '?season=' + season);
    if (slot === 1) {
      player1 = d.bio;
      player1.season_metrics = d.metrics || {};
    } else {
      player2 = d.bio;
      player2.season_metrics = d.metrics || {};
    }
    renderVSPlayerCard(slot, d.bio);
    updateCompareButton();
    // Update search input with player name
    document.getElementById('player' + slot + 'Search').value =
      d.bio.full_name || d.bio.player_name || '';
    hideDropdown(slot);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function renderVSPlayerCard(slot, bio) {
  const card = document.getElementById('player' + slot + 'Card');
  const name = bio.full_name || bio.player_name || 'Unknown';
  const initials = name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
  const team = bio.team_abbr || bio.team || '—';
  const pos = bio.position || '';
  // 有头像则渲染 <img> 覆盖在圆头像上；加载失败（onerror）自动移除回退到首字母
  const avatarInner = bio.headshot_path
    ? `<img class="player-avatar-img" src="/headshots/${encodeURIComponent(bio.player_id || '')}" alt="${escapeHtml(name)}" onerror="this.remove()" loading="lazy">`
    : escapeHtml(initials);
  card.className = 'player-card player-' + slot + ' has-player';
  card.innerHTML = `
    <div class="player-avatar ${slot === 2 ? 'p2' : ''}">${avatarInner}</div>
    <div class="player-name">${entityLink('player', bio.player_id || '', name, 'entity-link-name')}</div>
    <div class="player-team">${escapeHtml([team, pos].filter(Boolean).join(' · '))}</div>
  `;
}

// ── Metrics ──
async function loadMetrics() {
  try {
    const d = await api('/metrics');
    allMetrics = d.metrics || [];
    renderMetricGrid();
    populateRankMetricSelect();
  } catch (e) {
    toast(I18N.t('vs.failedToLoadMetrics') + ': ' + e.message, 'error');
    document.getElementById('metricGrid').innerHTML =
      '<div class="metric-loading" style="color:var(--danger);">' + I18N.t('vs.failedToLoadMetrics') + '</div>';
  }
}

function renderMetricGrid() {
  const grid = document.getElementById('metricGrid');
  if (allMetrics.length === 0) {
    grid.innerHTML = '<div class="metric-loading">' + I18N.t('common.noMetricsAvailable') + '</div>';
    return;
  }
  // Auto-select first 5 metrics if none selected
  if (selectedMetrics.size === 0) {
    allMetrics.slice(0, 5).forEach(m => selectedMetrics.add(m.name));
  }
  grid.innerHTML = allMetrics.map(m => {
    const sel = selectedMetrics.has(m.name) ? 'selected' : '';
    const mname = escapeHtml(m.name);
    return `<div class="metric-item ${sel}" onclick="toggleMetric('${mname}')">
      <div class="metric-checkbox"></div>
      <div class="metric-info">
        <div class="metric-name">${mname}</div>
        <div class="metric-kind">${escapeHtml(m.kind)} · ${escapeHtml(m.source_table)}</div>
      </div>
    </div>`;
  }).join('');
  updateCompareButton();
}

function toggleMetric(name) {
  if (selectedMetrics.has(name)) {
    selectedMetrics.delete(name);
  } else {
    selectedMetrics.add(name);
  }
  renderMetricGrid();
}

function selectAllMetrics() {
  allMetrics.forEach(m => selectedMetrics.add(m.name));
  renderMetricGrid();
}

function clearMetrics() {
  selectedMetrics.clear();
  renderMetricGrid();
}

// ── Compare Button State ──
function updateCompareButton() {
  const btn = document.getElementById('compareBtn');
  btn.disabled = !(player1 && player2 && selectedMetrics.size > 0);
}

// ── Run VS Compare ──
async function runCompare() {
  if (!player1 || !player2 || selectedMetrics.size === 0) return;
  const season = document.getElementById('seasonSelect').value;
  const metrics = Array.from(selectedMetrics).join(',');

  const btn = document.getElementById('compareBtn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> ' + I18N.t('vs.comparing');

  try {
    const d = await api(
      '/vs/compare?p1=' + encodeURIComponent(player1.player_id) +
      '&p2=' + encodeURIComponent(player2.player_id) +
      '&season=' + season +
      '&metrics=' + encodeURIComponent(metrics)
    );
    renderVSResults(d);
    document.getElementById('vsResults').style.display = 'block';
  } catch (e) {
    toast(I18N.t('vs.compareFailed') + ': ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = I18N.t('vs.comparePlayers');
  }
}

function renderVSResults(d) {
  const p1 = d.player_1;
  const p2 = d.player_2;
  const p1Name = (player1 && (player1.full_name || player1.player_name)) || p1;
  const p2Name = (player2 && (player2.full_name || player2.player_name)) || p2;

  // Update table headers
  document.getElementById('vsTableP1').textContent = p1Name;
  document.getElementById('vsTableP2').textContent = p2Name;

  // Build table rows
  const tbody = document.getElementById('vsTableBody');
  const metrics = d.metrics || {};
  tbody.innerHTML = Object.keys(metrics).map(mname => {
    const vals = metrics[mname];
    const v1 = vals[p1];
    const v2 = vals[p2];
    const s1 = v1 != null ? Number(v1).toFixed(2) : '—';
    const s2 = v2 != null ? Number(v2).toFixed(2) : '—';
    let win1 = '';
    let win2 = '';
    if (v1 != null && v2 != null) {
      // Higher is better for all current metrics
      if (v1 > v2) win1 = 'vs-win player-1';
      else if (v2 > v1) win2 = 'vs-win player-2';
    }
    return `<tr>
      <td style="font-weight:500;">${escapeHtml(mname)}</td>
      <td style="text-align:right;" class="${win1}">${s1}</td>
      <td style="text-align:right;" class="${win2}">${s2}</td>
    </tr>`;
  }).join('');

  // Render charts
  renderRadarChart(d, p1Name, p2Name);
  renderBarChart(d, p1Name, p2Name);
}

// ── Radar Chart ──
function renderRadarChart(d, p1Name, p2Name) {
  const el = document.getElementById('radarChart');
  if (!el) return;
  if (charts.radar) charts.radar.dispose();
  charts.radar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  // Get max values for normalization (150% of max)
  const maxVals = names.map(name => {
    const v1 = metrics[name][p1];
    const v2 = metrics[name][p2];
    const max = Math.max(v1 || 0, v2 || 0);
    return max > 0 ? max * 1.3 : 1;
  });

  const p1Values = names.map((name, i) => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : 0;
  });
  const p2Values = names.map((name, i) => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : 0;
  });

  charts.radar.setOption({
    tooltip: {},
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    radar: {
      indicator: names.map((name, i) => ({
        name: name,
        max: maxVals[i],
      })),
      axisName: { color: THEME.textDim, fontSize: 11 },
      splitArea: {
        areaStyle: { color: ['rgba(0, 184, 138,.02)', 'rgba(0, 184, 138,.05)'] },
      },
      splitLine: { lineStyle: { color: THEME.splitLine } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: p1Values,
          name: p1Name,
          itemStyle: { color: THEME.accent },
          areaStyle: { color: 'rgba(0, 184, 138,.15)' },
          lineStyle: { width: 2 },
        },
        {
          value: p2Values,
          name: p2Name,
          itemStyle: { color: THEME.info },
          areaStyle: { color: 'rgba(59, 130, 246,.15)' },
          lineStyle: { width: 2 },
        },
      ],
    }],
  });
}

// ── Bar Chart ──
function renderBarChart(d, p1Name, p2Name) {
  const el = document.getElementById('barChart');
  if (!el) return;
  if (charts.bar) charts.bar.dispose();
  charts.bar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  const p1Values = names.map(name => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : null;
  });
  const p2Values = names.map(name => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : null;
  });

  charts.bar.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: THEME.textDim, fontSize: 10, rotate: 30 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: THEME.textDim },
      splitLine: { lineStyle: { color: THEME.splitLine } },
    },
    series: [
      {
        name: p1Name,
        type: 'bar',
        data: p1Values,
        itemStyle: { color: THEME.accent, borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
      {
        name: p2Name,
        type: 'bar',
        data: p2Values,
        itemStyle: { color: THEME.info, borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
    ],
  });
}

// ── Rankings Page ──
const _PER_GAME_STATS = ['pts', 'reb', 'ast', 'stl', 'blk', 'tov', 'fg_pct', 'fg3_pct', 'ft_pct', 'mp'];
const _ADVANCED_STATS = ['per', 'ts_pct', 'usg_pct', 'bpm', 'vorp', 'ws', 'mp'];

function populateRankMetricSelect() {
  const source = document.getElementById('rankSourceSelect').value;
  const sel = document.getElementById('rankMetricSelect');
  const label = document.getElementById('rankMetricLabel');

  if (source === 'metric') {
    label.textContent = I18N.t('rankings.metricLabel');
    if (allMetrics.length === 0) return;
    sel.innerHTML = allMetrics.map(m =>
      `<option value="${m.name}">${m.name}</option>`
    ).join('');
  } else if (source === 'per_game') {
    label.textContent = I18N.t('rankings.statLabel');
    sel.innerHTML = _PER_GAME_STATS.map(s =>
      `<option value="${s}">${s.toUpperCase()}</option>`
    ).join('');
  } else if (source === 'advanced') {
    label.textContent = I18N.t('rankings.statLabel');
    sel.innerHTML = _ADVANCED_STATS.map(s =>
      `<option value="${s}">${s.toUpperCase()}</option>`
    ).join('');
  }
}

function onRankSourceChange() {
  populateRankMetricSelect();
  loadRankings();
}

function loadRankingsPage() {
  const source = document.getElementById('rankSourceSelect').value;
  const sel = document.getElementById('rankMetricSelect');
  if (source === 'metric') {
    if (allMetrics.length > 0) loadRankings();
  } else {
    if (sel.children.length > 0) loadRankings();
  }
}

async function loadRankings() {
  const source = document.getElementById('rankSourceSelect').value;
  const metric = document.getElementById('rankMetricSelect').value;
  const season = document.getElementById('rankSeasonSelect').value;
  if (!metric) return;

  const thead = document.getElementById('rankTableHead');
  const tbody = document.getElementById('rankTableBody');
  tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;

  try {
    let d;
    if (source === 'metric') {
      d = await api('/metrics/evaluate/' + metric + '?season=' + season + '&limit=50');
      renderMetricRankings(d);
    } else {
      d = await api('/leaderboard/' + source + '?season=' + season + '&limit=50&sort=' + encodeURIComponent(metric));
      renderStatRankings(d, source);
    }
  } catch (e) {
    thead.innerHTML = `
      <tr>
        <th style="width:60px;">#</th>
        <th>${I18N.t('common.player')}</th>
        <th style="width:120px; text-align:right;">${I18N.t('common.value')}</th>
        <th style="width:100px; text-align:right;">${I18N.t('common.percentile')}</th>
      </tr>`;
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--danger);">
      ${I18N.t('common.failedToLoad')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

function renderMetricRankings(d) {
  const thead = document.getElementById('rankTableHead');
  const tbody = document.getElementById('rankTableBody');
  document.getElementById('rankTitle').textContent = d.metric + ' — ' + I18N.t('rankings.topPlayers');
  document.getElementById('rankCount').textContent = d.total + I18N.t('rankings.playersSuffix');

  thead.innerHTML = `
    <tr>
      <th style="width:60px;">#</th>
      <th>${I18N.t('common.player')}</th>
      <th style="width:120px; text-align:right;">${I18N.t('common.value')}</th>
      <th style="width:100px; text-align:right;">${I18N.t('common.percentile')}</th>
    </tr>`;

  const rankings = d.rankings || [];
  tbody.innerHTML = rankings.map(r => {
    const medalColors = ['var(--warn)', 'var(--text-dim)', '#cd7f32'];
    const rankColor = r.rank <= 3 ? medalColors[r.rank - 1] : 'var(--text-dim)';
    const rawName = r.player_name || r.player_id || '';
    const nameHtml = entityLink('player', r.player_id || '', rawName, 'entity-link-name');
    const pos = escapeHtml(r.position || '');
    return `<tr>
      <td style="font-weight:700; color:${rankColor};">${r.rank}</td>
      <td>
        ${nameHtml}
        ${pos ? `<div class="sub">${pos}</div>` : ''}
      </td>
      <td style="text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);">${Number(r.value).toFixed(2)}</td>
      <td style="text-align:right; color:var(--text-dim);">${Number(r.percentile).toFixed(1)}%</td>
    </tr>`;
  }).join('');
}

function renderStatRankings(d, source) {
  const thead = document.getElementById('rankTableHead');
  const tbody = document.getElementById('rankTableBody');
  const title = source === 'per_game' ? I18N.t('rankings.perGameStats') : I18N.t('rankings.advancedStats');
  document.getElementById('rankTitle').textContent = title + ' — ' + I18N.t('rankings.topPlayers');
  document.getElementById('rankCount').textContent = (d.total || (d.leaderboard || []).length) + I18N.t('rankings.playersSuffix');

  const players = d.leaderboard || d.players || d.data || [];
  let statColumns = [];

  if (players.length > 0) {
    const first = players[0];
    const allKeys = Object.keys(first);
    const excludeKeys = ['rank', 'player_name', 'player_id', 'name', 'team_abbr', 'team', 'team_name', 'position', 'pos'];
    statColumns = allKeys.filter(k => !excludeKeys.includes(k));
  }

  thead.innerHTML = `
    <tr>
      <th style="width:60px;">#</th>
      <th>${I18N.t('common.player')}</th>
      <th style="width:100px;">${I18N.t('common.team')}</th>
      ${statColumns.map(c => `<th style="text-align:right;">${c}</th>`).join('')}
    </tr>`;

  if (players.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${3 + statColumns.length}" style="text-align:center; padding:30px; color:var(--text-dim);">
      ${I18N.t('common.noData')}
    </td></tr>`;
    return;
  }

  tbody.innerHTML = players.map(p => {
    const rank = p.rank || '—';
    const rawName = p.player_name || p.name || p.player_id || 'Unknown';
    const nameHtml = entityLink('player', p.player_id || '', rawName, 'entity-link-name');
    const team = escapeHtml(p.team_abbr || p.team || '—');
    const pos = escapeHtml(p.position || p.pos || '');
    const medalColors = ['var(--warn)', 'var(--text-dim)', '#cd7f32'];
    const rankColor = typeof rank === 'number' && rank <= 3 ? medalColors[rank - 1] : 'var(--text-dim)';

    return `<tr>
      <td style="font-weight:700; color:${rankColor};">${rank}</td>
      <td>
        ${nameHtml}
        ${pos ? `<div class="sub">${pos}</div>` : ''}
      </td>
      <td><span class="badge badge-blue">${team}</span></td>
      ${statColumns.map(c => {
        const v = p[c];
        const display = typeof v === 'number' ? v.toFixed(2) : (v != null ? escapeHtml(String(v)) : '—');
        return `<td style="text-align:right; font-family:var(--mono);">${display}</td>`;
      }).join('')}
    </tr>`;
  }).join('');
}

// ── Context Page State ──
let ctxPlayer = null;
let ctxSearchTimer = null;

function searchContextPlayer() {
  const q = document.getElementById('ctxPlayerSearch').value;
  clearTimeout(ctxSearchTimer);
  ctxSearchTimer = setTimeout(() => doContextSearch(q), 300);
}

async function doContextSearch(q) {
  const dd = document.getElementById('ctxPlayerDropdown');
  if (!q || q.length < 2) {
    dd.classList.remove('show');
    return;
  }
  try {
    const d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
    const players = d.players || [];
    if (players.length === 0) {
      dd.innerHTML = '<div class="dropdown-empty">' + I18N.t('common.noPlayersFound') + '</div>';
    } else {
      dd.innerHTML = players.map(p => {
        const pname = escapeHtml(p.full_name || p.player_name || p.player_id || '');
        const pid = escapeHtml(p.player_id || '');
        const ppos = escapeHtml(p.position || '');
        return `
        <div class="dropdown-item" onmousedown="selectContextPlayer('${pid}')">
          <div>${pname}</div>
          <div class="sub">${ppos}</div>
        </div>
      `;}).join('');
    }
    dd.classList.add('show');
  } catch {
    dd.classList.remove('show');
  }
}

function showContextDropdown() {
  const q = document.getElementById('ctxPlayerSearch').value;
  if (q && q.length >= 2) {
    document.getElementById('ctxPlayerDropdown').classList.add('show');
  }
}

function hideContextDropdownDelay() {
  setTimeout(() => {
    document.getElementById('ctxPlayerDropdown').classList.remove('show');
  }, 200);
}

function selectContextPlayer(pid) {
  ctxPlayer = pid;
  document.getElementById('ctxPlayerSearch').value = pid;
  document.getElementById('ctxPlayerDropdown').classList.remove('show');
  loadContext();
}

function loadContextPage() {
  if (ctxPlayer) {
    loadContext();
  }
}

async function loadContext() {
  if (!ctxPlayer) return;
  const season = document.getElementById('ctxSeasonSelect').value;
  const posFilter = document.getElementById('ctxPosFilter').checked;

  document.getElementById('ctxEmpty').style.display = 'none';
  document.getElementById('ctxResults').style.display = 'block';

  // Similar players
  loadSimilarPlayers(ctxPlayer, season, posFilter);

  // Role evolution (last 5 seasons up to current)
  const s = parseInt(season);
  const evoSeasons = [];
  for (let i = 4; i >= 0; i--) {
    evoSeasons.push(s - i);
  }
  loadRoleEvolution(ctxPlayer, evoSeasons);

  // Trend
  const trendMetric = document.getElementById('trendMetricSelect').value;
  if (trendMetric) {
    loadTrend();
  } else {
    populateTrendMetricSelect();
  }
}

async function loadSimilarPlayers(playerId, season, posFilter) {
  const tbody = document.getElementById('similarTableBody');
  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;
  try {
    const d = await api('/context/similar?player_id=' + playerId + '&season=' + season +
      '&position_filter=' + posFilter + '&limit=10');
    const players = d.similar_players || [];
    if (players.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-dim);">
        ${I18N.t('context.noSimilarPlayers')}
      </td></tr>`;
      return;
    }
    tbody.innerHTML = players.map((p, i) => `
      <tr>
        <td style="font-weight:700; color:var(--text-dim);">${i + 1}</td>
        <td style="font-weight:600;">
          <a href="javascript:void(0)" onclick="viewSimilarPlayerContext('${escapeHtml(p.player_id)}', '${escapeHtml(p.name || '')}')"
             style="color:var(--accent); text-decoration:none; hover-text-decoration:underline;">
            ${escapeHtml(p.name || '')}
          </a>
        </td>
        <td style="color:var(--text-dim);">${escapeHtml([p.team, p.position].filter(Boolean).join(' · '))}</td>
        <td style="text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);">
          ${(p.similarity * 100).toFixed(1)}%
        </td>
        <td style="text-align:right;">
          <button class="btn btn-ghost btn-sm" onclick="viewSimilarPlayerGrowth('${escapeHtml(p.player_id)}', '${escapeHtml(p.name || '')}')" title="查看成长报告">
            📈
          </button>
          <button class="btn btn-ghost btn-sm" onclick="addSimilarPlayerToVS('${escapeHtml(p.player_id)}', '${escapeHtml(p.name || '')}')" title="加入 VS 比较">
            ⚔️
          </button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--danger);">
      ${I18N.t('common.failed')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

function viewSimilarPlayerContext(playerId, playerName) {
  ctxPlayer = playerId;
  document.getElementById('ctxPlayerSearch').value = playerName;
  loadContext();
}

function viewSimilarPlayerGrowth(playerId, playerName) {
  document.getElementById('growthPlayerSearch').value = playerName;
  nav('growth');
  setTimeout(() => loadGrowthReport(playerId), 100);
}

async function addSimilarPlayerToVS(playerId, playerName) {
  if (currentPage === 'context') {
    switchCtxTab('vs');
    await selectCtxVsPlayer2(playerId);
    toast(`已将 ${playerName} 添加到 VS 比较`, 'success');
    if (ctxPlayer && ctxVsPlayer2 && ctxVsSelectedMetrics.size > 0) {
      setTimeout(() => runCtxVsCompare(), 300);
    }
    return;
  }
  const slot = player1 ? 2 : 1;
  await selectPlayer(slot, playerId);
  toast(`已将 ${playerName} 添加到 Player ${slot}`, 'success');
  if (player1 && player2) {
    nav('vs');
  }
}

// ── Context Page Tabs ──
function switchCtxTab(tab) {
  document.querySelectorAll('.ctx-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
  document.querySelectorAll('.ctx-tab-content').forEach(el => {
    el.classList.remove('active');
  });
  document.getElementById('ctx-tab-' + tab).classList.add('active');
  if (tab === 'vs') {
    initCtxVs();
  }
}

// ── Context VS State ──
let ctxVsPlayer2 = null;
let ctxVsSelectedMetrics = new Set();
let ctxVsCharts = {};
let ctxVsSearchTimer = null;

function initCtxVs() {
  if (!ctxPlayer) return;
  const season = document.getElementById('ctxSeasonSelect').value;
  loadCtxVsPlayer1();
  if (allMetrics.length === 0) {
    loadCtxVsMetrics();
  } else {
    renderCtxVsMetricGrid();
  }
  updateCtxVsCompareButton();
}

async function loadCtxVsPlayer1() {
  if (!ctxPlayer) return;
  const season = document.getElementById('ctxSeasonSelect').value;
  try {
    const d = await api('/players/' + ctxPlayer + '?season=' + season);
    renderCtxVsPlayerCard(1, d.bio);
  } catch (e) {
    console.error('Failed to load ctx vs player 1:', e);
  }
}

function renderCtxVsPlayerCard(slot, bio) {
  const card = document.getElementById('ctxVsPlayer' + slot + 'Card');
  if (!card) return;
  const name = bio.full_name || bio.player_name || 'Unknown';
  const initials = name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
  const team = bio.team_abbr || bio.team || '—';
  const pos = bio.position || '';
  // 有头像则渲染 <img> 覆盖在圆头像上；加载失败（onerror）自动移除回退到首字母
  const avatarInner = bio.headshot_path
    ? `<img class="player-avatar-img" src="/headshots/${encodeURIComponent(bio.player_id || '')}" alt="${escapeHtml(name)}" onerror="this.remove()" loading="lazy">`
    : escapeHtml(initials);
  card.className = 'player-card ctx-vs-card player-' + slot + ' has-player';
  card.innerHTML = `
    <div class="player-avatar ${slot === 2 ? 'p2' : ''}">${avatarInner}</div>
    <div class="player-name">${entityLink('player', bio.player_id || '', name, 'entity-link-name')}</div>
    <div class="player-team">${escapeHtml([team, pos].filter(Boolean).join(' · '))}</div>
  `;
}

// ── Context VS Player 2 Search ──
function searchCtxVsPlayer2() {
  const q = document.getElementById('ctxVsPlayer2Search').value;
  clearTimeout(ctxVsSearchTimer);
  ctxVsSearchTimer = setTimeout(() => doCtxVsPlayer2Search(q), 300);
}

async function doCtxVsPlayer2Search(q) {
  const dd = document.getElementById('ctxVsPlayer2Dropdown');
  if (!q || q.length < 2) {
    dd.classList.remove('show');
    return;
  }
  try {
    const d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
    const players = d.players || [];
    if (players.length === 0) {
      dd.innerHTML = '<div class="dropdown-empty">' + I18N.t('common.noPlayersFound') + '</div>';
    } else {
      dd.innerHTML = players.map(p => {
        const pname = escapeHtml(p.full_name || p.player_name || p.player_id || '');
        const pid = escapeHtml(p.player_id || '');
        const ppos = escapeHtml(p.position || '');
        return `
        <div class="dropdown-item" onmousedown="selectCtxVsPlayer2('${pid}')">
          <div>${pname}</div>
          <div class="sub">${ppos}</div>
        </div>
      `;}).join('');
    }
    dd.classList.add('show');
  } catch {
    dd.classList.remove('show');
  }
}

function showCtxVsPlayer2Dropdown() {
  const q = document.getElementById('ctxVsPlayer2Search').value;
  if (q && q.length >= 2) {
    document.getElementById('ctxVsPlayer2Dropdown').classList.add('show');
  }
}

function hideCtxVsPlayer2DropdownDelay() {
  setTimeout(() => {
    document.getElementById('ctxVsPlayer2Dropdown').classList.remove('show');
  }, 200);
}

async function selectCtxVsPlayer2(playerId) {
  const season = document.getElementById('ctxSeasonSelect').value;
  try {
    const d = await api('/players/' + playerId + '?season=' + season);
    ctxVsPlayer2 = d.bio;
    ctxVsPlayer2.season_metrics = d.metrics || {};
    renderCtxVsPlayerCard(2, d.bio);
    document.getElementById('ctxVsPlayer2Search').value =
      d.bio.full_name || d.bio.player_name || '';
    document.getElementById('ctxVsPlayer2Dropdown').classList.remove('show');
    updateCtxVsCompareButton();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Context VS Metrics ──
async function loadCtxVsMetrics() {
  const grid = document.getElementById('ctxVsMetricGrid');
  try {
    const d = await api('/metrics');
    allMetrics = d.metrics || [];
    renderCtxVsMetricGrid();
  } catch (e) {
    grid.innerHTML = '<div class="metric-loading" style="color:var(--danger);">' + I18N.t('vs.failedToLoadMetrics') + '</div>';
  }
}

function renderCtxVsMetricGrid() {
  const grid = document.getElementById('ctxVsMetricGrid');
  if (!grid) return;
  if (allMetrics.length === 0) {
    grid.innerHTML = '<div class="metric-loading">' + I18N.t('common.noMetricsAvailable') + '</div>';
    return;
  }
  if (ctxVsSelectedMetrics.size === 0) {
    allMetrics.slice(0, 5).forEach(m => ctxVsSelectedMetrics.add(m.name));
  }
  grid.innerHTML = allMetrics.map(m => {
    const sel = ctxVsSelectedMetrics.has(m.name) ? 'selected' : '';
    const mname = escapeHtml(m.name);
    return `<div class="metric-item ${sel}" onclick="toggleCtxVsMetric('${mname}')">
      <div class="metric-checkbox"></div>
      <div class="metric-info">
        <div class="metric-name">${mname}</div>
        <div class="metric-kind">${escapeHtml(m.kind)} · ${escapeHtml(m.source_table)}</div>
      </div>
    </div>`;
  }).join('');
  updateCtxVsCompareButton();
}

function toggleCtxVsMetric(name) {
  if (ctxVsSelectedMetrics.has(name)) {
    ctxVsSelectedMetrics.delete(name);
  } else {
    ctxVsSelectedMetrics.add(name);
  }
  renderCtxVsMetricGrid();
}

function ctxVsSelectAllMetrics() {
  allMetrics.forEach(m => ctxVsSelectedMetrics.add(m.name));
  renderCtxVsMetricGrid();
}

function ctxVsClearMetrics() {
  ctxVsSelectedMetrics.clear();
  renderCtxVsMetricGrid();
}

function updateCtxVsCompareButton() {
  const btn = document.getElementById('ctxVsCompareBtn');
  if (!btn) return;
  btn.disabled = !(ctxPlayer && ctxVsPlayer2 && ctxVsSelectedMetrics.size > 0);
}

// ── Context VS Compare ──
async function runCtxVsCompare() {
  if (!ctxPlayer || !ctxVsPlayer2 || ctxVsSelectedMetrics.size === 0) return;
  const season = document.getElementById('ctxSeasonSelect').value;
  const metrics = Array.from(ctxVsSelectedMetrics).join(',');

  const btn = document.getElementById('ctxVsCompareBtn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> ' + I18N.t('vs.comparing');

  try {
    const d = await api(
      '/vs/compare?p1=' + encodeURIComponent(ctxPlayer) +
      '&p2=' + encodeURIComponent(ctxVsPlayer2.player_id) +
      '&season=' + season +
      '&metrics=' + encodeURIComponent(metrics)
    );
    renderCtxVsResults(d);
    document.getElementById('ctxVsResults').style.display = 'block';
  } catch (e) {
    toast(I18N.t('vs.compareFailed') + ': ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = I18N.t('vs.comparePlayers');
  }
}

function renderCtxVsResults(d) {
  const p1 = d.player_1;
  const p2 = d.player_2;
  const p1Bio = document.querySelector('#ctxVsPlayer1Card .player-name');
  const p2Bio = document.querySelector('#ctxVsPlayer2Card .player-name');
  const p1Name = p1Bio ? p1Bio.textContent : p1;
  const p2Name = p2Bio ? p2Bio.textContent : p2;

  document.getElementById('ctxVsTableP1').textContent = p1Name;
  document.getElementById('ctxVsTableP2').textContent = p2Name;

  const tbody = document.getElementById('ctxVsTableBody');
  const metrics = d.metrics || {};
  tbody.innerHTML = Object.keys(metrics).map(mname => {
    const vals = metrics[mname];
    const v1 = vals[p1];
    const v2 = vals[p2];
    const s1 = v1 != null ? Number(v1).toFixed(2) : '—';
    const s2 = v2 != null ? Number(v2).toFixed(2) : '—';
    let win1 = '';
    let win2 = '';
    if (v1 != null && v2 != null) {
      if (v1 > v2) win1 = 'vs-win player-1';
      else if (v2 > v1) win2 = 'vs-win player-2';
    }
    return `<tr>
      <td style="font-weight:500;">${escapeHtml(mname)}</td>
      <td style="text-align:right;" class="${win1}">${s1}</td>
      <td style="text-align:right;" class="${win2}">${s2}</td>
    </tr>`;
  }).join('');

  renderCtxVsRadarChart(d, p1Name, p2Name);
  renderCtxVsBarChart(d, p1Name, p2Name);
}

function renderCtxVsRadarChart(d, p1Name, p2Name) {
  const el = document.getElementById('ctxVsRadarChart');
  if (!el) return;
  if (ctxVsCharts.radar) ctxVsCharts.radar.dispose();
  ctxVsCharts.radar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  const maxVals = names.map(name => {
    const v1 = metrics[name][p1];
    const v2 = metrics[name][p2];
    const max = Math.max(v1 || 0, v2 || 0);
    return max > 0 ? max * 1.3 : 1;
  });

  const p1Values = names.map(name => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : 0;
  });
  const p2Values = names.map(name => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : 0;
  });

  ctxVsCharts.radar.setOption({
    tooltip: {},
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    radar: {
      indicator: names.map((name, i) => ({
        name: name,
        max: maxVals[i],
      })),
      axisName: { color: THEME.textDim, fontSize: 11 },
      splitArea: {
        areaStyle: { color: ['rgba(0, 184, 138,.02)', 'rgba(0, 184, 138,.05)'] },
      },
      splitLine: { lineStyle: { color: THEME.splitLine } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: p1Values,
          name: p1Name,
          itemStyle: { color: THEME.accent },
          areaStyle: { color: 'rgba(0, 184, 138,.15)' },
          lineStyle: { width: 2 },
        },
        {
          value: p2Values,
          name: p2Name,
          itemStyle: { color: THEME.info },
          areaStyle: { color: 'rgba(59, 130, 246,.15)' },
          lineStyle: { width: 2 },
        },
      ],
    }],
  });
}

function renderCtxVsBarChart(d, p1Name, p2Name) {
  const el = document.getElementById('ctxVsBarChart');
  if (!el) return;
  if (ctxVsCharts.bar) ctxVsCharts.bar.dispose();
  ctxVsCharts.bar = echarts.init(el);

  const metrics = d.metrics || {};
  const names = Object.keys(metrics);
  const p1 = d.player_1;
  const p2 = d.player_2;

  const p1Values = names.map(name => {
    const v = metrics[name][p1];
    return v != null ? Number(v) : null;
  });
  const p2Values = names.map(name => {
    const v = metrics[name][p2];
    return v != null ? Number(v) : null;
  });

  ctxVsCharts.bar.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      data: [p1Name, p2Name],
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: THEME.textDim, fontSize: 10, rotate: 30 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: THEME.textDim },
      splitLine: { lineStyle: { color: THEME.splitLine } },
    },
    series: [
      {
        name: p1Name,
        type: 'bar',
        data: p1Values,
        itemStyle: { color: THEME.accent, borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
      {
        name: p2Name,
        type: 'bar',
        data: p2Values,
        itemStyle: { color: THEME.info, borderRadius: [4, 4, 0, 0] },
        barWidth: '35%',
      },
    ],
  });
}

// ── Context Season Change ──
function onCtxSeasonChange() {
  loadContext();
  if (ctxVsPlayer2) {
    const season = document.getElementById('ctxSeasonSelect').value;
    api('/players/' + ctxVsPlayer2.player_id + '?season=' + season).then(d => {
      ctxVsPlayer2 = d.bio;
      ctxVsPlayer2.season_metrics = d.metrics || {};
      renderCtxVsPlayerCard(2, d.bio);
    }).catch(() => {});
  }
  if (document.getElementById('ctx-tab-vs')?.classList.contains('active')) {
    loadCtxVsPlayer1();
    if (ctxPlayer && ctxVsPlayer2 && ctxVsSelectedMetrics.size > 0) {
      runCtxVsCompare();
    }
  }
}

async function loadRoleEvolution(playerId, seasons) {
  const grid = document.getElementById('evolutionGrid');
  grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--text-dim);"><div class="spinner"></div> ' + I18N.t('common.loading') + '</div>';

  try {
    const seasonParam = seasons.join(',');
    const d = await api('/context/evolution?player_id=' + playerId + '&seasons=' + seasonParam);

    document.getElementById('evolutionSeasons').textContent = d.seasons.length + I18N.t('context.seasonsSuffix');
    document.getElementById('overallShift').textContent = (d.overall_shift_magnitude * 100).toFixed(1) + '%';
    document.getElementById('topGrowth').textContent = d.top_growth.slice(0, 2).join(', ') || '—';
    document.getElementById('topDecline').textContent = d.top_decline.slice(0, 2).join(', ') || '—';

    const changes = d.metric_changes || [];
    if (changes.length === 0) {
      grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--text-dim);">' + I18N.t('common.notEnoughData') + '</div>';
      return;
    }

    grid.innerHTML = changes.map(c => {
      const dirColor = c.direction === 'up' ? 'var(--success)' : c.direction === 'down' ? 'var(--danger)' : 'var(--text-dim)';
      const arrow = c.direction === 'up' ? '▲' : c.direction === 'down' ? '▼' : '—';
      const pct = c.pct_change !== null ? (c.pct_change > 0 ? '+' : '') + c.pct_change.toFixed(1) + '%' : '—';
      return `
        <div class="metric-tile">
          <div class="metric-tile-name">${escapeHtml(c.metric)}</div>
          <div class="metric-tile-value" style="color:${dirColor};">
            ${arrow} ${pct}
          </div>
          <div class="metric-tile-sub">
            ${c.first_value !== null ? c.first_value.toFixed(2) : '—'} → ${c.last_value !== null ? c.last_value.toFixed(2) : '—'}
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:20px; color:var(--danger);">${I18N.t('common.failed')}: ${escapeHtml(e.message)}</div>`;
  }
}

function populateTrendMetricSelect() {
  const sel = document.getElementById('trendMetricSelect');
  if (allMetrics.length === 0) return;
  sel.innerHTML = allMetrics.map(m =>
    `<option value="${m.name}">${m.name}</option>`
  ).join('');
}

async function loadTrend() {
  const metric = document.getElementById('trendMetricSelect').value;
  const season = parseInt(document.getElementById('ctxSeasonSelect').value);
  if (!metric || !ctxPlayer) return;

  const seasons = [];
  for (let i = 4; i >= 0; i--) {
    seasons.push(season - i);
  }

  try {
    const d = await api('/context/trend?player_id=' + ctxPlayer +
      '&metric=' + metric + '&seasons=' + seasons.join(','));

    // Stats
    const dirColors = { up: 'var(--success)', down: 'var(--danger)', flat: 'var(--text-dim)', insufficient_data: 'var(--text-dim)' };
    document.getElementById('trendDir').textContent = d.direction;
    document.getElementById('trendDir').style.color = dirColors[d.direction] || 'var(--text-dim)';
    document.getElementById('trendSlope').textContent = d.slope !== null ? d.slope.toFixed(3) : '—';
    document.getElementById('trendR2').textContent = d.r_squared !== null ? d.r_squared.toFixed(3) : '—';
    document.getElementById('trendPred').textContent = d.predicted_next !== null ? d.predicted_next.toFixed(2) : '—';

    // Chart
    renderTrendChart(d, metric);
  } catch (e) {
    toast(I18N.t('context.trendLoadFailed') + ': ' + e.message, 'error');
  }
}

function renderTrendChart(data, metric) {
  const chartDom = document.getElementById('trendChart');
  if (!chartDom) return;

  if (charts.trend) {
    charts.trend.dispose();
  }
  charts.trend = echarts.init(chartDom);

  const seasonLabels = data.seasons.map(s => seasonLabel(s));
  const values = data.values;

  // Build trend line points
  const trendPoints = [];
  if (data.slope !== null && data.intercept !== null) {
    data.seasons.forEach((s, i) => {
      if (values[i] !== null) {
        trendPoints.push(data.slope * s + data.intercept);
      } else {
        trendPoints.push(null);
      }
    });
  }

  charts.trend.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonLabels,
      axisLine: { lineStyle: { color: 'var(--border)' } },
      axisLabel: { color: 'var(--text-dim)' },
    },
    yAxis: {
      type: 'value',
      name: metric,
      nameTextStyle: { color: 'var(--text-dim)' },
      axisLine: { lineStyle: { color: 'var(--border)' } },
      splitLine: { lineStyle: { color: 'var(--border-light)' } },
      axisLabel: { color: 'var(--text-dim)' },
    },
    series: [
      {
        name: 'Actual',
        type: 'line',
        data: values,
        smooth: true,
        lineStyle: { color: THEME.accent, width: 3 },
        itemStyle: { color: THEME.accent },
        symbolSize: 8,
      },
      {
        name: 'Trend',
        type: 'line',
        data: trendPoints,
        lineStyle: { color: '#ff9f43', width: 2, type: 'dashed' },
        itemStyle: { color: '#ff9f43' },
        symbol: 'none',
      },
    ],
  });
}

// ── Teams Page ──
function switchTeamsTab(tab) {
  document.querySelectorAll('#page-teams .tab').forEach(e => e.classList.remove('active'));
  document.querySelectorAll('#page-teams .tab-content').forEach(e => e.classList.remove('active'));
  document.querySelector('#page-teams .tab[data-tab="teams-' + tab + '"]').classList.add('active');
  document.getElementById('teams-' + tab).classList.add('active');
}

async function loadTeamsPage() {
  const tbody = document.getElementById('teamsTableBody');
  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;

  try {
    const season = document.getElementById('teamsSeasonSelect').value;
    const d = await api('/teams/board?season=' + season);
    const groups = d.groups || [];
    const total = groups.reduce((n, g) => n + (g.teams ? g.teams.length : 0), 0);
    document.getElementById('teamsCount').textContent = total + I18N.t('teams.teamsSuffix');

    if (total === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">
        ${I18N.t('teams.noTeamsFound')}
      </td></tr>`;
      return;
    }

    let html = '';
    for (const g of groups) {
      const confLabel = g.conference === 'East' ? '东部' : (g.conference === 'West' ? '西部' : '');
      const confClass = g.conference === 'East' ? 'badge-blue' : 'badge-purple';
      html += `<tr class="division-row">
        <td colspan="5">
          <span class="division-name">${escapeHtml(g.division)}</span>
          <span class="badge ${confClass} division-conf">${confLabel}</span>
        </td>
      </tr>`;
      for (const t of (g.teams || [])) {
        const rawName = t.team_name || t.name || I18N.t('common.unknown');
        const abbr = escapeHtml(t.team_abbr || '—');
        const linkAbbr = t.team_abbr || '';
        const abbrLower = (t.team_abbr || '').toLowerCase();
        const logoHtml = `<img src="/assets/logos/${abbrLower}.svg" class="team-logo-sm" alt="${abbr}" onerror="this.style.display='none'">`;
        const wl = (t.w != null && t.l != null) ? `${t.w}-${t.l}` : '—';
        const winPct = (t.win_pct != null) ? (t.win_pct * 100).toFixed(1) + '%' : '—';
        const poBadge = t.made_playoffs
          ? `<span class="badge badge-gold" title="季后赛">PO</span>` : '';
        html += `<tr style="cursor:pointer;" onclick="selectTeam('${abbr}')">
          <td style="font-weight:700; color:var(--text-dim); text-align:center;">${t.div_rank}</td>
          <td>${logoHtml}</td>
          <td style="font-weight:600;">${entityLink('team', linkAbbr, rawName, 'entity-link-name')} ${poBadge}</td>
          <td style="text-align:center; font-variant-numeric:tabular-nums;">${wl}</td>
          <td style="text-align:center; font-variant-numeric:tabular-nums;">${winPct}</td>
        </tr>`;
      }
    }
    tbody.innerHTML = html;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--danger);">
      ${I18N.t('common.failedToLoad')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

async function selectTeam(teamAbbr) {
  currentTeam = teamAbbr;
  const ts = document.getElementById('teamsSeasonSelect');
  const season = ts && ts.value ? Number(ts.value) : undefined;
  if (window.openEntityDetail) {
    window.openEntityDetail('team', teamAbbr, season);
  }
}

async function loadTeamDetail(teamAbbr) {
  currentTeamAbbr = teamAbbr;
  const season = document.getElementById('teamsSeasonSelect').value;
  document.getElementById('teamDetailEmpty').style.display = 'none';
  document.getElementById('teamDetailContent').style.display = 'block';

  const abbrLower = teamAbbr.toLowerCase();
  document.getElementById('teamDetailLogo').innerHTML = `<img src="/assets/logos/${abbrLower}.svg" class="team-detail-logo-img" alt="${teamAbbr}" onerror="this.parentElement.style.display='none'">`;
  document.getElementById('teamDetailAbbr').textContent = teamAbbr;

  switchTeamDetailTab('history');

  loadTeamStatsData(teamAbbr, season);
  loadTeamHistoryData(teamAbbr);
  loadTeamLegendsData(teamAbbr);
  loadTeamRosterSeasons(teamAbbr);
}

function switchTeamDetailTab(tabName) {
  document.querySelectorAll('.team-detail-tab').forEach(e => e.classList.remove('active'));
  document.querySelectorAll('.team-detail-tab-content').forEach(e => e.classList.remove('active'));
  document.querySelector(`.team-detail-tab[data-tab="${tabName}"]`)?.classList.add('active');
  document.getElementById('teamTab' + tabName.charAt(0).toUpperCase() + tabName.slice(1))?.classList.add('active');
}

async function loadTeamStatsData(teamAbbr, season) {
  const labelMap = {
    pts: 'PTS', reb: 'REB', ast: 'AST', stl: 'STL', blk: 'BLK',
    fg_pct: 'FG%', fg3_pct: '3P%', ft_pct: 'FT%',
    pace: 'PACE', x3p_ar: '3P Rate', fta: 'FTA',
    tov: 'TOV', pf: 'PF',
    plus_minus: '+/-'
  };
  const percentKeys = ['fg_pct', 'fg3_pct', 'ft_pct', 'x3p_ar'];
  const lowerIsBetter = ['tov', 'pf'];

  const fixedMax = {
    pts: 125,
    reb: 50,
    ast: 32,
    stl: 10,
    blk: 7,
    fg_pct: 55,
    fg3_pct: 45,
    ft_pct: 88,
    pace: 108,
    x3p_ar: 55,
    fta: 32,
    tov: 20,
    pf: 28,
    plus_minus: 12,
  };

  try {
    const [radarResp, avgResp] = await Promise.all([
      api('/teams/' + teamAbbr + '/radar?season=' + season),
      api('/teams/league-avg/radar?season=' + season),
    ]);
    const radarRaw = radarResp.data || radarResp || {};
    const avgRaw = avgResp.data || avgResp || {};

    const indicators = [];
    const teamValues = [];
    const avgValues = [];
    const teamRealValues = [];
    const avgRealValues = [];
    for (const [key, label] of Object.entries(labelMap)) {
      if (radarRaw[key] != null) {
        let teamVal = radarRaw[key];
        let avgVal = avgRaw[key];
        if (percentKeys.includes(key)) {
          if (teamVal <= 1) teamVal = teamVal * 100;
          if (avgVal != null && avgVal <= 1) avgVal = avgVal * 100;
        }
        const teamReal = Math.round(teamVal * 10) / 10;
        const avgReal = avgVal != null ? Math.round(avgVal * 10) / 10 : 0;
        const max = fixedMax[key] != null ? fixedMax[key] : teamVal * 1.5;
        const displayLabel = lowerIsBetter.includes(key) ? label + ' ↓' : label;
        indicators.push({ name: displayLabel, max: max });

        if (lowerIsBetter.includes(key)) {
          teamValues.push(Math.round((max - teamVal) * 10) / 10);
          avgValues.push(avgVal != null ? Math.round((max - avgVal) * 10) / 10 : 0);
        } else {
          teamValues.push(teamReal);
          avgValues.push(avgReal);
        }
        teamRealValues.push(teamReal);
        avgRealValues.push(avgReal);
      }
    }

    renderTeamRadarChart(
      { indicators, teamValues, avgValues, teamRealValues, avgRealValues },
      teamAbbr
    );
  } catch (e) {
    toast(I18N.t('teams.failedLoadRadar') + ': ' + e.message, 'error');
  }

  try {
    const standingsData = await api('/teams/standings?season=' + season);
    renderTeamStandings(standingsData, teamAbbr);
  } catch (e) {
    document.getElementById('teamStandings').innerHTML =
      '<div style="color:var(--danger);">Failed: ' + escapeHtml(e.message) + '</div>';
  }

  try {
    const statsData = await api('/teams/stats?season=' + season);
    renderTeamStats(statsData, teamAbbr);
  } catch (e) {
    document.getElementById('teamStatsBody').innerHTML =
      '<tr><td colspan="2" style="text-align:center; padding:20px; color:var(--danger);">Failed: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function loadTeamHistoryData(teamAbbr) {
  try {
    const historyData = await api('/teams/' + teamAbbr + '/history');
    renderTeamHistory(historyData);
  } catch (e) {
    document.getElementById('teamHistoryBody').innerHTML =
      '<tr><td colspan="7" style="text-align:center; padding:20px; color:var(--danger);">Failed: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function loadTeamLegendsData(teamAbbr) {
  try {
    const legendsData = await api('/teams/' + teamAbbr + '/legends');
    renderTeamLegends(legendsData);
  } catch (e) {
    document.getElementById('teamLegendsBody').innerHTML =
      '<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--danger);">Failed: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function loadTeamRosterSeasons(teamAbbr) {
  try {
    const historyData = await api('/teams/' + teamAbbr + '/history');
    const seasons = (historyData.data || []).map(h => h.season).sort((a, b) => b - a);
    const sel = document.getElementById('teamRosterSeasonSelect');
    sel.innerHTML = '';
    seasons.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s + '-' + (s + 1).toString().slice(-2);
      sel.appendChild(opt);
    });
    if (seasons.length > 0) {
      loadTeamRoster();
    }
  } catch (e) {
    console.error('Failed to load roster seasons:', e);
  }
}

async function loadTeamRoster() {
  if (!currentTeamAbbr) return;
  const season = document.getElementById('teamRosterSeasonSelect').value;
  try {
    const rosterData = await api('/teams/' + currentTeamAbbr + '/roster/' + season);
    renderTeamRoster(rosterData);
  } catch (e) {
    document.getElementById('teamRosterBody').innerHTML =
      '<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--danger);">Failed: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

function renderTeamRadarChart(data, teamAbbr) {
  const el = document.getElementById('teamRadarChart');
  if (!el) return;
  if (charts.teamRadar) charts.teamRadar.dispose();
  charts.teamRadar = echarts.init(el);

  const indicators = data.indicators || data.metrics || [];
  const teamValues = data.teamValues || data.values || data.value || [];
  const avgValues = data.avgValues || [];
  const teamRealValues = data.teamRealValues || teamValues;
  const avgRealValues = data.avgRealValues || avgValues;

  if (indicators.length === 0) {
    el.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-dim);">No radar data available</div>';
    return;
  }

  const seriesData = [];

  if (avgValues.length > 0) {
    seriesData.push({
      value: avgValues,
      name: I18N.t('teams.leagueAvg'),
      itemStyle: { color: THEME.textDim },
      areaStyle: { color: 'rgba(107,122,153,.1)' },
      lineStyle: { width: 1.5, type: 'dashed' },
      symbol: 'circle',
      symbolSize: 4,
    });
  }

  seriesData.push({
    value: teamValues,
    name: teamAbbr,
    itemStyle: { color: THEME.accent },
    areaStyle: { color: 'rgba(0, 184, 138,.2)' },
    lineStyle: { width: 2.5 },
    symbol: 'circle',
    symbolSize: 5,
  });

  charts.teamRadar.setOption({
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        const name = params.name;
        const values = params.value;
        const realVals = name === teamAbbr ? teamRealValues : avgRealValues;
        let html = '<div style="font-weight:600; margin-bottom:4px;">' + name + '</div>';
        indicators.forEach(function (ind, i) {
          const val = realVals[i] != null ? realVals[i] : values[i];
          html += '<div style="display:flex; justify-content:space-between; gap:16px;">'
            + '<span>' + ind.name + '</span>'
            + '<span style="font-family:var(--mono); font-weight:600;">' + val + '</span>'
            + '</div>';
        });
        return html;
      },
    },
    legend: {
      data: avgValues.length > 0 ? [I18N.t('teams.leagueAvg'), teamAbbr] : [teamAbbr],
      bottom: 0,
      textStyle: { color: THEME.textDim, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 10,
    },
    radar: {
      indicator: indicators.map((ind, i) => ({
        name: ind.name || ind.label || ind,
        max: ind.max || (teamValues[i] || 0) * 1.3,
      })),
      axisName: { color: THEME.textDim, fontSize: 11 },
      splitArea: {
        areaStyle: { color: ['rgba(0, 184, 138,.02)', 'rgba(0, 184, 138,.05)'] },
      },
      splitLine: { lineStyle: { color: THEME.splitLine } },
      center: ['50%', '45%'],
      radius: '60%',
    },
    series: [{
      type: 'radar',
      data: seriesData,
    }],
  });
}

function renderTeamStandings(data, teamAbbr) {
  const el = document.getElementById('teamStandings');
  const standings = data.standings || data.data || [];
  const team = standings.find(s =>
    (s.team_abbr || s.abbreviation || s.abbr || '') === teamAbbr ||
    (s.team_name || s.name || '') === teamAbbr
  );

  if (team) {
    const teamName = team.team_name || team.name || teamAbbr;
    document.getElementById('teamDetailName').textContent = teamName;
  }

  if (!team) {
    el.innerHTML = '<div style="color:var(--text-dim);">' + I18N.t('teams.noStandingsData') + '</div>';
    return;
  }

  const wins = team.wins ?? team.w ?? '—';
  const losses = team.losses ?? team.l ?? '—';
  const winPct = team.win_pct ?? team.pct ?? '—';
  const rank = team.rank ?? team.position ?? '—';
  const conf = team.conference ?? team.conf ?? '';

  el.innerHTML = `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
      <div class="metric-tile">
        <div class="metric-tile-name">${I18N.t('teams.record')}</div>
        <div class="metric-tile-value" style="color:var(--accent);">${wins}-${losses}</div>
        <div class="metric-tile-sub">${I18N.t('teams.winPercent')}: ${typeof winPct === 'number' ? (winPct * 100).toFixed(1) + '%' : winPct}</div>
      </div>
      <div class="metric-tile">
        <div class="metric-tile-name">${conf || I18N.t('teams.conference')} ${I18N.t('teams.rank')}</div>
        <div class="metric-tile-value" style="color:var(--info);">#${rank}</div>
        <div class="metric-tile-sub">of ${standings.length} ${I18N.t('teams.teamsSuffix')}</div>
      </div>
    </div>
  `;
}

function renderTeamStats(data, teamAbbr) {
  const tbody = document.getElementById('teamStatsBody');
  const stats = data.stats || data.data || [];
  const team = Array.isArray(stats)
    ? stats.find(s => (s.team_abbr || s.abbreviation || s.abbr || '') === teamAbbr)
    : (data[teamAbbr] || null);

  if (!team) {
    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center; padding:20px; color:var(--text-dim);">' + I18N.t('teams.noStatsData') + '</td></tr>';
    return;
  }

  const labelMap = {
    off_pts: 'PTS (Off)',
    def_pts: 'PTS (Def)',
    g: 'Games',
    fg_percent: 'FG%',
    x3p_percent: '3P%',
    ft_percent: 'FT%',
    trb_per_game: 'REB',
    ast_per_game: 'AST',
    stl_per_game: 'STL',
    blk_per_game: 'BLK',
    tov_per_game: 'TOV',
    pf_per_game: 'PF',
    fta_per_game: 'FTA',
  };
  const percentKeys = ['fg_percent', 'x3p_percent', 'ft_percent'];
  const order = [
    'off_pts', 'def_pts', 'g',
    'fg_percent', 'x3p_percent', 'ft_percent',
    'trb_per_game', 'ast_per_game', 'stl_per_game', 'blk_per_game',
    'tov_per_game', 'pf_per_game', 'fta_per_game',
  ];

  const rows = [];
  for (const key of order) {
    if (team[key] == null) continue;
    let val = team[key];
    if (percentKeys.includes(key) && val <= 1) {
      val = (val * 100).toFixed(1) + '%';
    } else if (typeof val === 'number') {
      val = val.toFixed(1);
    }
    const label = labelMap[key] || key;
    rows.push(`<tr>
      <td style="font-weight:500;">${label}</td>
      <td style="text-align:right; font-family:var(--mono); font-weight:600; color:var(--accent);">${val}</td>
    </tr>`);
  }

  tbody.innerHTML = rows.join('');
}

function renderTeamHistory(data) {
  const history = data.data || [];
  document.getElementById('teamHistoryCount').textContent = history.length + ' 赛季';

  const tbody = document.getElementById('teamHistoryBody');
  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:20px; color:var(--text-dim);">暂无历史数据</td></tr>';
    return;
  }

  const rows = history.map(h => {
    const season = h.season;
    const w = h.w || 0;
    const l = h.l || 0;
    const winPct = h.win_pct != null ? (h.win_pct * 100).toFixed(1) + '%' : '—';
    const pts = h.pts_per_game != null ? h.pts_per_game.toFixed(1) : '—';
    const ast = h.ast_per_game != null ? h.ast_per_game.toFixed(1) : '—';
    const reb = h.trb_per_game != null ? h.trb_per_game.toFixed(1) : '—';
    const playoffs = h.made_playoffs ? '✓' : '';
    const playoffsClass = h.made_playoffs ? 'style="color:var(--accent); font-weight:bold;"' : 'style="color:var(--text-dim);"';

    return `<tr>
      <td style="font-weight:500;">${season}</td>
      <td style="text-align:center;">${w}-${l}</td>
      <td style="text-align:right; font-family:var(--mono);">${winPct}</td>
      <td style="text-align:right; font-family:var(--mono);">${pts}</td>
      <td style="text-align:right; font-family:var(--mono);">${ast}</td>
      <td style="text-align:right; font-family:var(--mono);">${reb}</td>
      <td style="text-align:center;" ${playoffsClass}>${playoffs}</td>
    </tr>`;
  });
  tbody.innerHTML = rows.join('');

  const el = document.getElementById('teamHistoryChart');
  if (el) {
    if (charts.teamHistory) charts.teamHistory.dispose();
    charts.teamHistory = echarts.init(el);

    const sortedHistory = [...history].reverse();
    const seasons = sortedHistory.map(h => h.season.toString());
    const winPcts = sortedHistory.map(h => h.win_pct != null ? h.win_pct * 100 : null);
    const points = sortedHistory.map(h => h.pts_per_game != null ? h.pts_per_game : null);

    charts.teamHistory.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['胜率%', '场均得分'], textStyle: { color: THEME.textDim } },
      grid: { left: 50, right: 20, top: 30, bottom: 40 },
      xAxis: {
        type: 'category',
        data: seasons,
        axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
        axisLine: { lineStyle: { color: THEME.axisLine } },
      },
      yAxis: [
        {
          type: 'value',
          name: '胜率%',
          nameTextStyle: { color: THEME.textDim },
          axisLabel: { color: THEME.textDim, formatter: '{value}%' },
          splitLine: { lineStyle: { color: THEME.border } },
          max: 100,
        },
        {
          type: 'value',
          name: '得分',
          nameTextStyle: { color: THEME.textDim },
          axisLabel: { color: THEME.textDim },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '胜率%',
          type: 'line',
          data: winPcts,
          smooth: true,
          itemStyle: { color: THEME.accent },
          symbol: 'circle',
          symbolSize: 4,
          areaStyle: { color: 'rgba(0, 184, 138, 0.15)' },
        },
        {
          name: '场均得分',
          type: 'bar',
          yAxisIndex: 1,
          data: points,
          itemStyle: { color: 'rgba(59, 130, 246, 0.6)' },
          barWidth: '40%',
        },
      ],
    });
  }
}

function renderTeamLegends(data) {
  const legends = data.data || [];
  document.getElementById('teamLegendsCount').textContent = legends.length + ' 人';

  const tbody = document.getElementById('teamLegendsBody');
  if (legends.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--text-dim);">暂无传奇球员数据</td></tr>';
    return;
  }

  const rows = legends.map((p, idx) => {
    const rank = idx + 1;
    const pos = p.position || '-';
    const posBadge = `<span class="pos-badge" style="font-size:11px; padding:2px 6px;">${pos}</span>`;
    const allStar = p.all_star_count || 0;

    return `<tr>
      <td style="text-align:center; font-weight:bold; color:var(--text-dim);">${rank}</td>
      <td>
        <a href="#" onclick="viewPlayerContext('${p.player_id}'); return false;" 
           style="color:var(--accent); text-decoration:underline;">${p.player_name}</a>
      </td>
      <td style="text-align:center;">${posBadge}</td>
      <td style="text-align:center;">${p.seasons_played}</td>
      <td style="text-align:right; font-family:var(--mono);">${p.ppg != null ? p.ppg : '—'}</td>
      <td style="text-align:right; font-family:var(--mono);">${p.rpg != null ? p.rpg : '—'}</td>
      <td style="text-align:right; font-family:var(--mono);">${p.apg != null ? p.apg : '—'}</td>
      <td style="text-align:center;">${allStar > 0 ? '<span style="color:var(--warn);">★' + allStar + '</span>' : '-'}</td>
    </tr>`;
  });
  tbody.innerHTML = rows.join('');
}

function renderTeamRoster(data) {
  const roster = data.data || [];

  const tbody = document.getElementById('teamRosterBody');
  if (roster.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--text-dim);">暂无阵容数据</td></tr>';
    return;
  }

  const rows = roster.map(p => {
    const pos = p.position || p.primary_position || '-';
    const posBadge = `<span class="pos-badge" style="font-size:11px; padding:2px 6px;">${pos}</span>`;
    const gp = p.games_played || 0;
    const gs = p.games_started || 0;
    const ppg = p.points_per_game != null ? p.points_per_game : '—';
    const rpg = p.rebounds_per_game != null ? p.rebounds_per_game : '—';
    const apg = p.assists_per_game != null ? p.assists_per_game : '—';
    const mpg = p.minutes_per_game != null ? p.minutes_per_game : '—';

    return `<tr>
      <td>
        <a href="#" onclick="viewPlayerContext('${p.player_id}'); return false;" 
           style="color:var(--accent); text-decoration:underline;">${p.player_name}</a>
      </td>
      <td style="text-align:center;">${posBadge}</td>
      <td style="text-align:center; font-family:var(--mono);">${gp}</td>
      <td style="text-align:center; font-family:var(--mono);">${gs}</td>
      <td style="text-align:right; font-family:var(--mono);">${ppg}</td>
      <td style="text-align:right; font-family:var(--mono);">${rpg}</td>
      <td style="text-align:right; font-family:var(--mono);">${apg}</td>
      <td style="text-align:right; font-family:var(--mono);">${mpg}</td>
    </tr>`;
  });
  tbody.innerHTML = rows.join('');
}

// ── Crawler Page ──
let crawlerEventSource = null;

async function loadCrawlerPage() {
  checkCrawlerStatus();
  setupCrawlerModeSelect();
  await loadTableOverview();
}

// ── Data Import Page ──
async function loadDataImportPage() {
  try {
    const d = await api('/data-import/tables');
    const sel = document.getElementById('importTableSelect');
    sel.innerHTML = '';
    (d.tables || []).forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
  } catch (e) {
    toast(I18N.t('common.failed') + ': ' + e.message, 'error');
  }
}

async function uploadCsv() {
  const fileInput = document.getElementById('importFile');
  const table = document.getElementById('importTableSelect').value;
  const mode = document.getElementById('importModeSelect').value;
  const resultEl = document.getElementById('importResult');

  if (!fileInput.files || fileInput.files.length === 0) {
    toast(I18N.t('common.failed') + ': please choose a CSV file', 'error');
    return;
  }

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  fd.append('target_table', table);
  fd.append('mode', mode);

  resultEl.textContent = I18N.t('dataImport.importing') || 'Importing...';
  try {
    const d = await api('/data-import/upload', { method: 'POST', body: fd });
    const errCount = (d.errors || []).length;
    let html = `<div style="color:var(--success);"><b>${d.inserted}</b> rows inserted into <b>${d.table}</b></div>`;
    html += `<div style="color:var(--text-dim); margin-top:6px;">columns: ${(d.columns || []).join(', ')}</div>`;
    if (errCount > 0) {
      html += `<div style="color:var(--danger); margin-top:8px;">${errCount} row(s) skipped due to errors:</div>`;
      html += `<pre style="max-height:200px; overflow:auto; background:var(--bg-dark); padding:8px; border-radius:6px; font-size:12px;">${(d.errors || []).slice(0, 50).map(e => String(e).replace(/</g, '&lt;')).join('\n')}</pre>`;
    }
    resultEl.innerHTML = html;
    toast(I18N.t('dataImport.importDone') + d.inserted, 'success');
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--danger);">${String(e.message || e).replace(/</g, '&lt;')}</span>`;
    toast(I18N.t('common.failed') + ': ' + e.message, 'error');
  }
}

function setupCrawlerModeSelect() {
  const modeSel = document.getElementById('crawlModeSelect');
  const tableRow = document.getElementById('crawlTableRow');
  const seasonRow = document.getElementById('crawlSeasonRow');
  const daysRow = document.getElementById('crawlDaysRow');

  modeSel.addEventListener('change', () => {
    const mode = modeSel.value;
    tableRow.style.display = mode === 'single' ? 'block' : 'none';
    seasonRow.style.display = (mode === 'single' || mode === 'full_season') ? 'block' : 'none';
    daysRow.style.display = mode === 'backfill' ? 'block' : 'none';
  });
}

async function checkCrawlerStatus() {
  try {
    const d = await api('/crawler/status');
    const badge = document.getElementById('crawlerStatusBadge');
    const stopBtn = document.getElementById('crawlStopBtn');

    if (d.running) {
      badge.className = 'badge badge-green';
      badge.textContent = I18N.t('crawler.running');
      stopBtn.style.display = 'inline-block';
      startLogStream();
    } else {
      badge.className = 'badge badge-gray';
      badge.textContent = I18N.t('crawler.idle');
      stopBtn.style.display = 'none';
      stopLogStream();
    }
  } catch (e) {
    const badge = document.getElementById('crawlerStatusBadge');
    badge.className = 'badge badge-red';
    badge.textContent = I18N.t('crawler.error');
  }
}

async function loadTableOverview() {
  try {
    const tables = await api('/crawler/tables');
    const overviewEl = document.getElementById('crawlerTableOverview');
    const countEl = document.getElementById('crawlerTableCount');
    const selectEl = document.getElementById('crawlerTableSelect');

    // Populate overview
    let html = '<table class="tbl" style="font-size:12px;"><thead><tr>' +
      '<th>表名</th><th style="text-align:right;">列数</th><th style="text-align:right;">行数</th><th>说明</th></tr></thead><tbody>';
    tables.forEach(t => {
      const rowLabel = t.rows >= 1000000 ? (t.rows / 1000000).toFixed(1) + 'M'
        : t.rows >= 1000 ? (t.rows / 1000).toFixed(0) + 'K'
        : String(t.rows);
      html += '<tr><td><code>' + escapeHtml(t.name) + '</code></td>' +
        '<td style="text-align:right;">' + t.columns + '</td>' +
        '<td style="text-align:right;">' + rowLabel + '</td>' +
        '<td style="color:var(--text-dim);">' + escapeHtml(t.description || '') + '</td></tr>';
    });
    html += '</tbody></table>';
    overviewEl.innerHTML = html;

    if (countEl) countEl.textContent = tables.length + ' 张表';

    // Populate dropdown (null-guarded against transient Heisenbug)
    if (selectEl) {
      selectEl.innerHTML = '<option value="">— 选择表 —</option>';
      tables.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.name;
        opt.textContent = t.name + ' (' + (t.description || '') + ')';
        selectEl.appendChild(opt);
      });
    }
  } catch (e) {
    const el = document.getElementById('crawlerTableOverview');
    if (el) el.innerHTML = '<div style="color:var(--danger); padding:12px;">加载失败: ' + escapeHtml(e.message) + '</div>';
  }
}

async function startCrawl(mode) {
  try {
    const d = await api('/crawler/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode, params: {} }),
    });
    toast(I18N.t('crawler.crawlStarted') + mode, 'success');
    appendCrawlLog('INFO', I18N.t('crawler.startedCrawl') + mode);
    checkCrawlerStatus();
    startLogStream();
  } catch (e) {
    toast(I18N.t('common.failed') + ': ' + e.message, 'error');
  }
}

async function startCustomCrawl() {
  const mode = document.getElementById('crawlModeSelect').value;
  const params = {};

  if (mode === 'single') {
    params.table = document.getElementById('crawlTableSelect').value;
    if (!params.table) { toast('请选择一个表', 'error'); return; }
    const season = document.getElementById('crawlSeasonInput').value;
    if (season) params.season = parseInt(season);
  } else if (mode === 'full_season') {
    const season = document.getElementById('crawlSeasonInput').value;
    if (season) params.season = parseInt(season);
  } else if (mode === 'backfill') {
    const days = document.getElementById('crawlDaysInput').value;
    if (days) params.days = parseInt(days);
  }

  try {
    const d = await api('/crawler/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode, params: params }),
    });
    toast(I18N.t('crawler.crawlStarted') + mode, 'success');
    appendCrawlLog('INFO', I18N.t('crawler.startedCrawl') + mode + ' with params: ' + JSON.stringify(params));
    checkCrawlerStatus();
    startLogStream();
  } catch (e) {
    toast(I18N.t('common.failed') + ': ' + e.message, 'error');
  }
}

async function stopCrawl() {
  try {
    await api('/crawler/stop', { method: 'POST' });
    toast(I18N.t('crawler.crawlStopped'), 'success');
    appendCrawlLog('INFO', I18N.t('crawler.crawlStoppedByUser'));
    checkCrawlerStatus();
  } catch (e) {
    toast(I18N.t('common.failed') + ': ' + e.message, 'error');
  }
}

function startLogStream() {
  if (crawlerEventSource) return;

  try {
    crawlerEventSource = new EventSource('/crawler/logs/stream');
    crawlerEventSource.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        appendCrawlLog(msg.level, msg.msg);
      } catch {
        appendCrawlLog('INFO', event.data);
      }
    };
    crawlerEventSource.onerror = () => {
      stopLogStream();
      setTimeout(() => {
        checkCrawlerStatus().then(running => {
          if (running) startLogStream();
        });
      }, 3000);
    };
  } catch (e) {
    console.error('SSE error:', e);
  }
}

function stopLogStream() {
  if (crawlerEventSource) {
    crawlerEventSource.close();
    crawlerEventSource = null;
  }
}

function appendCrawlLog(level, msg) {
  const container = document.getElementById('crawlLogContainer');
  if (!container) return;

  if (container.querySelector('div[style*="color:var(--text-dim)"]')) {
    container.innerHTML = '';
  }

  const line = document.createElement('div');
  const time = new Date().toLocaleTimeString();
  let color = 'var(--text)';
  if (level === 'ERROR') color = 'var(--danger)';
  else if (level === 'WARNING') color = 'var(--warn)';
  else if (level === 'INFO') color = 'var(--text-dim)';

  line.innerHTML = `<span style="color:var(--text-dim);">[${time}]</span> <span style="color:${color};">[${level}]</span> ${escapeHtml(msg)}`;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function clearCrawlLog() {
  const container = document.getElementById('crawlLogContainer');
  if (container) {
    container.innerHTML = '<div style="color:var(--text-dim);">' + I18N.t('crawler.noLogs') + '</div>';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ── Games Page ──
async function loadGamesPage() {
  const season = document.getElementById('gamesSeasonSelect').value;
  const perPage = 50;
  const tbody = document.getElementById('gamesTableBody');

  tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;

  try {
    const d = await api('/games?season=' + season + '&page=' + gamesPage + '&per_page=' + perPage);
    const games = d.games || d.data || [];
    const total = d.total || d.count || 0;
    gamesTotalPages = Math.ceil(total / perPage) || 1;

    document.getElementById('gamesCount').textContent = total + I18N.t('games.gamesSuffix');
    document.getElementById('gamesPageInfo').textContent = gamesPage + ' / ' + gamesTotalPages;
    document.getElementById('gamesPrevBtn').disabled = gamesPage <= 1;
    document.getElementById('gamesNextBtn').disabled = gamesPage >= gamesTotalPages;

    if (games.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--text-dim);">
        ${I18N.t('games.noGamesFound')}
      </td></tr>`;
      return;
    }

    tbody.innerHTML = games.map(g => {
      const date = escapeHtml(g.game_date || g.date || '—');
      const home = escapeHtml(g.home_team_abbr || g.home_team || g.home || '—');
      const away = escapeHtml(g.away_team_abbr || g.away_team || g.visitor || g.away || '—');
      const homeScore = g.home_pts != null ? g.home_pts : (g.home_score != null ? g.home_score : (g.pts_home != null ? g.pts_home : ''));
      const awayScore = g.away_pts != null ? g.away_pts : (g.away_score != null ? g.away_score : (g.pts_away != null ? g.pts_away : ''));
      const scoreDisplay = (homeScore !== '' && awayScore !== '')
        ? escapeHtml(`${homeScore} - ${awayScore}`)
        : 'vs';
      const gid = escapeHtml(g.game_id || '');
      const clickable = gid ? `style="cursor:pointer;" onclick="showGameDetail('${gid}')"` : '';

      return `<tr ${clickable}>
        <td style="font-family:var(--mono);">${date}</td>
        <td style="text-align:right; font-weight:600;">${home}</td>
        <td style="text-align:center; font-family:var(--mono); font-weight:700; color:var(--accent);">${scoreDisplay}</td>
        <td style="font-weight:600;">${away}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:30px; color:var(--danger);">
      ${I18N.t('common.failedToLoad')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

function gamesPrevPage() {
  if (gamesPage > 1) {
    gamesPage--;
    loadGamesPage();
  }
}

function gamesNextPage() {
  if (gamesPage < gamesTotalPages) {
    gamesPage++;
    loadGamesPage();
  }
}

// ── Game Detail ──
function showGamesList() {
  document.getElementById('gameDetailView').style.display = 'none';
  document.getElementById('gamesListView').style.display = 'block';
  // Dispose radar chart if exists
  if (charts.gameRadar) {
    charts.gameRadar.dispose();
    charts.gameRadar = null;
  }
}

function formatClock(clk) {
  if (!clk) return '—';
  // Input format: "PT11M19.00S" → "11:19"
  const m = clk.match(/PT(\d+)M([\d.]+)S/i);
  if (m) {
    const mins = parseInt(m[1], 10);
    const secs = Math.floor(parseFloat(m[2]));
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }
  return clk;
}

async function showGameDetail(gameId) {
  document.getElementById('gamesListView').style.display = 'none';
  document.getElementById('gameDetailView').style.display = 'block';

  // Reset
  document.getElementById('gameDetailTitle').textContent = I18N.t('common.loading');
  document.getElementById('gameDetailScore').textContent = '—';
  document.getElementById('gameDetailMeta').textContent = '—';
  document.getElementById('gameQuartersRow').innerHTML = '';
  document.getElementById('gameStatsHead').innerHTML = '';
  document.getElementById('gameStatsBody').innerHTML =
    '<tr><td style="text-align:center; padding:20px; color:var(--text-dim);">' + I18N.t('common.loading') + '</td></tr>';
  document.getElementById('gamePlayersTimeline').innerHTML =
    '<div style="text-align:center; padding:20px; color:var(--text-dim);">' + I18N.t('common.loading') + '</div>';
  document.getElementById('gamePlayersCount').textContent = '—';
  if (charts.gameRadar) {
    charts.gameRadar.dispose();
    charts.gameRadar = null;
  }

  // Fetch all data in parallel
  try {
    const [detailResp, radarResp, playersResp] = await Promise.all([
      api('/games/' + encodeURIComponent(gameId)),
      api('/games/' + encodeURIComponent(gameId) + '/radar'),
      api('/games/' + encodeURIComponent(gameId) + '/players'),
    ]);

    renderGameHeader(detailResp.data || {});
    renderGameQuarters(detailResp.data || {});
    renderGameRadar(radarResp);
    renderGameStatsTable(detailResp.data || {});
    renderGamePlayerTimeline(playersResp.players || []);
  } catch (e) {
    toast(I18N.t('games.failedLoadDetail') + ': ' + e.message, 'error');
    document.getElementById('gameDetailTitle').textContent = I18N.t('common.error') + ': ' + e.message;
  }
}

function renderGameHeader(detail) {
  const home = detail.home_team_abbr || '—';
  const away = detail.away_team_abbr || '—';
  const homePts = detail.home_pts != null ? detail.home_pts : '—';
  const awayPts = detail.away_pts != null ? detail.away_pts : '—';
  const date = detail.game_date || '—';
  const season = detail.season || '—';
  const seasonType = detail.season_type || '';

  document.getElementById('gameDetailTitle').textContent = `${away} @ ${home}`;
  document.getElementById('gameDetailScore').textContent = `${away} ${awayPts}  —  ${home} ${homePts}`;
  document.getElementById('gameDetailMeta').textContent =
    `${date} | ${seasonLabel(season)} ${seasonType}`.trim();
}

function renderGameQuarters(detail) {
  const home = detail.home_team_abbr || 'HOME';
  const away = detail.away_team_abbr || 'AWAY';
  const quarters = [
    { label: 'Q1', home: detail.home_q1, away: detail.away_q1 },
    { label: 'Q2', home: detail.home_q2, away: detail.away_q2 },
    { label: 'Q3', home: detail.home_q3, away: detail.away_q3 },
    { label: 'Q4', home: detail.home_q4, away: detail.away_q4 },
  ];
  if (detail.home_ot != null && detail.away_ot != null) {
    quarters.push({ label: 'OT', home: detail.home_ot, away: detail.away_ot });
  }

  const container = document.getElementById('gameQuartersRow');
  container.innerHTML = quarters.map(q => {
    const h = q.home != null ? q.home : '—';
    const a = q.away != null ? q.away : '—';
    return `<div style="flex:1; min-width:100px; background:var(--bg-dark); border-radius:8px; padding:8px; text-align:center;">
      <div style="font-size:11px; color:var(--text-dim); margin-bottom:4px;">${q.label}</div>
      <div style="font-family:var(--mono); font-size:14px;">
        <span style="color:var(--text-dim);">${a}</span>
        <span style="color:var(--text-dim); margin:0 4px;">|</span>
        <span style="color:var(--text-dim);">${h}</span>
      </div>
      <div style="font-size:10px; color:var(--text-dim); margin-top:2px;">${away} | ${home}</div>
    </div>`;
  }).join('');
}

function renderGameRadar(radarResp) {
  const el = document.getElementById('gameRadarChart');
  if (!el) return;
  if (charts.gameRadar) charts.gameRadar.dispose();
  charts.gameRadar = echarts.init(el);

  const home = radarResp.home || {};
  const away = radarResp.away || {};
  const homeTeam = radarResp.home_team || 'HOME';
  const awayTeam = radarResp.away_team || 'AWAY';

  // Radar metrics (display only — single-game values)
  const metrics = [
    { key: 'pts', label: 'PTS' },
    { key: 'reb', label: 'REB' },
    { key: 'ast', label: 'AST' },
    { key: 'stl', label: 'STL' },
    { key: 'blk', label: 'BLK' },
    { key: 'fg_pct', label: 'FG%', scale: 100 },
    { key: 'fg3_pct', label: '3P%', scale: 100 },
    { key: 'ft_pct', label: 'FT%', scale: 100 },
    { key: 'tov', label: 'TOV', invert: true },
    { key: 'pf', label: 'PF', invert: true },
  ];

  // Calculate max for each metric (150% of max value)
  const maxVals = metrics.map(m => {
    const hv = home[m.key] || 0;
    const av = away[m.key] || 0;
    const scale = m.scale || 1;
    const max = Math.max(hv * scale, av * scale);
    return max > 0 ? max * 1.3 : 1;
  });

  // For inverted metrics (TOV, PF), lower is better — display as (max - value)
  const buildValues = (stats) => metrics.map((m, i) => {
    const v = stats[m.key];
    if (v == null) return 0;
    const scaled = v * (m.scale || 1);
    if (m.invert) {
      return Math.round((maxVals[i] - scaled) * 10) / 10;
    }
    return Math.round(scaled * 10) / 10;
  });

  const homeValues = buildValues(home);
  const awayValues = buildValues(away);

  // Tooltip formatter showing real values
  const buildTooltip = (stats) => {
    return metrics.map(m => {
      const v = stats[m.key];
      const display = v != null
        ? (m.scale ? (v * 100).toFixed(1) + '%' : v)
        : '—';
      return `${m.label}: ${display}`;
    }).join('<br/>');
  };

  charts.gameRadar.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const isHome = params.name === homeTeam;
        const stats = isHome ? home : away;
        return `<b>${params.name}</b><br/>${buildTooltip(stats)}`;
      },
    },
    legend: {
      data: [homeTeam, awayTeam],
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    radar: {
      indicator: metrics.map((m, i) => ({
        name: m.label,
        max: maxVals[i],
      })),
      axisName: { color: THEME.textDim, fontSize: 11 },
      splitArea: {
        areaStyle: { color: ['rgba(0, 184, 138,.02)', 'rgba(0, 184, 138,.05)'] },
      },
      splitLine: { lineStyle: { color: THEME.splitLine } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: homeValues,
          name: homeTeam,
          itemStyle: { color: THEME.accent },
          areaStyle: { color: 'rgba(0, 184, 138,0.25)' },
          lineStyle: { color: THEME.accent, width: 2 },
        },
        {
          value: awayValues,
          name: awayTeam,
          itemStyle: { color: '#5b8cff' },
          areaStyle: { color: 'rgba(91,140,255,0.25)' },
          lineStyle: { color: '#5b8cff', width: 2 },
        },
      ],
    }],
  });
}

function renderGameStatsTable(detail) {
  const home = detail.home_team_abbr || 'HOME';
  const away = detail.away_team_abbr || 'AWAY';

  const stats = [
    { key: 'pts', label: I18N.t('games.points'), home: detail.home_pts, away: detail.away_pts },
    { key: 'fgm', label: I18N.t('games.fgMade'), home: detail.home_fgm, away: detail.away_fgm },
    { key: 'fga', label: I18N.t('games.fgAtt'), home: detail.home_fga, away: detail.away_fga },
    { key: 'fg_pct', label: 'FG%', home: detail.home_fg_pct, away: detail.away_fg_pct, fmt: 'pct' },
    { key: 'fg3m', label: I18N.t('games.fg3Made'), home: detail.home_fg3m, away: detail.away_fg3m },
    { key: 'fg3a', label: I18N.t('games.fg3Att'), home: detail.home_fga3, away: detail.away_fga3 },
    { key: 'fg3_pct', label: '3P%', home: detail.home_fg3_pct, away: detail.away_fg3_pct, fmt: 'pct' },
    { key: 'ftm', label: I18N.t('games.ftMade'), home: detail.home_ftm, away: detail.away_ftm },
    { key: 'fta', label: I18N.t('games.ftAtt'), home: detail.home_fta, away: detail.away_fta },
    { key: 'ft_pct', label: 'FT%', home: detail.home_ft_pct, away: detail.away_ft_pct, fmt: 'pct' },
    { key: 'reb', label: I18N.t('games.rebounds'), home: detail.home_reb, away: detail.away_reb },
    { key: 'oreb', label: I18N.t('games.offReb'), home: detail.home_oreb, away: detail.away_oreb },
    { key: 'dreb', label: I18N.t('games.defReb'), home: detail.home_dreb, away: detail.away_dreb },
    { key: 'ast', label: I18N.t('games.assists'), home: detail.home_ast, away: detail.away_ast },
    { key: 'stl', label: I18N.t('games.steals'), home: detail.home_stl, away: detail.away_stl },
    { key: 'blk', label: I18N.t('games.blocks'), home: detail.home_blk, away: detail.away_blk },
    { key: 'tov', label: I18N.t('games.turnovers'), home: detail.home_tov, away: detail.away_tov },
    { key: 'pf', label: I18N.t('games.fouls'), home: detail.home_pf, away: detail.away_pf },
  ];

  const head = document.getElementById('gameStatsHead');
  const body = document.getElementById('gameStatsBody');

  head.innerHTML = `<tr>
    <th style="text-align:left;">${I18N.t('games.stat')}</th>
    <th style="text-align:right;">${escapeHtml(away)}</th>
    <th style="text-align:right;">${escapeHtml(home)}</th>
  </tr>`;

  body.innerHTML = stats.map(s => {
    const fmt = (v) => {
      if (v == null) return '—';
      if (s.fmt === 'pct') return (v * 100).toFixed(1) + '%';
      return v;
    };
    const aVal = fmt(s.away);
    const hVal = fmt(s.home);
    // Highlight winner (higher is better, except TOV/PF where lower is better)
    const lowerBetter = s.key === 'tov' || s.key === 'pf';
    let aClass = '';
    let hClass = '';
    if (s.home != null && s.away != null) {
      if (lowerBetter) {
        if (s.away < s.home) aClass = 'style="color:var(--accent); font-weight:700;"';
        else if (s.home < s.away) hClass = 'style="color:var(--accent); font-weight:700;"';
      } else {
        if (s.away > s.home) aClass = 'style="color:var(--accent); font-weight:700;"';
        else if (s.home > s.away) hClass = 'style="color:var(--accent); font-weight:700;"';
      }
    }
    return `<tr>
      <td style="font-weight:500;">${escapeHtml(s.label)}</td>
      <td style="text-align:right; font-family:var(--mono);" ${aClass}>${aVal}</td>
      <td style="text-align:right; font-family:var(--mono);" ${hClass}>${hVal}</td>
    </tr>`;
  }).join('');
}

function renderGamePlayerTimeline(players) {
  const container = document.getElementById('gamePlayersTimeline');
  document.getElementById('gamePlayersCount').textContent = players.length + I18N.t('games.rowsSuffix');

  if (!players || players.length === 0) {
    container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--text-dim);">' +
      I18N.t('games.noPlayByPlayData') + '</div>';
    return;
  }

  // Group by team
  const teams = {};
  players.forEach(p => {
    const t = p.team || '?';
    if (!teams[t]) teams[t] = {};
    if (!teams[t][p.player]) {
      teams[t][p.player] = {
        player: p.player,
        team: t,
        periods: [],
        player_full_name: p.player_full_name || p.player,
        gamelog: p.gamelog || null,
      };
    }
    teams[t][p.player].periods.push(p);
  });

  // For each team, aggregate player totals across periods
  // Prefer gamelog stats (authoritative) over pbp aggregation
  const buildTeamSection = (teamAbbr, teamPlayers) => {
    const playerList = Object.values(teamPlayers);
    const totals = playerList.map(tp => {
      const gl = tp.gamelog;
      const t = {
        player: tp.player_full_name || tp.player,
        team: tp.team,
        periods: tp.periods,
        gamelog: gl,
      };
      if (gl) {
        t.pts = gl.pts != null ? gl.pts : 0;
        t.ast = gl.ast != null ? gl.ast : 0;
        t.reb = gl.reb != null ? gl.reb : 0;
        t.oreb = gl.oreb != null ? gl.oreb : 0;
        t.dreb = gl.dreb != null ? gl.dreb : 0;
        t.stl = gl.stl != null ? gl.stl : 0;
        t.blk = gl.blk != null ? gl.blk : 0;
        t.tov = gl.tov != null ? gl.tov : 0;
        t.pf = gl.pf != null ? gl.pf : 0;
        t.fgm = gl.fgm != null ? gl.fgm : 0;
        t.fga = gl.fga != null ? gl.fga : 0;
        t.fg3m = gl.fg3m != null ? gl.fg3m : 0;
        t.fg3a = gl.fg3a != null ? gl.fg3a : 0;
        t.ftm = gl.ftm != null ? gl.ftm : 0;
        t.fta = gl.fta != null ? gl.fta : 0;
        t.minutes = gl.minutes || gl.seconds_played ? Math.round((gl.seconds_played || 0) / 60) : null;
      } else {
        t.pts = 0; t.fgm = 0; t.fga = 0; t.fg3m = 0; t.fg3a = 0;
        t.ftm = 0; t.fta = 0; t.reb = 0; t.oreb = 0; t.dreb = 0;
        t.ast = 0; t.stl = 0; t.blk = 0; t.tov = 0; t.pf = 0;
        tp.periods.forEach(p => {
          t.pts += p.pts || 0;
          t.fgm += p.fgm || 0;
          t.fga += p.fga || 0;
          t.fg3m += p.fg3m || 0;
          t.fg3a += p.fg3a || 0;
          t.ftm += p.ftm || 0;
          t.fta += p.fta || 0;
          t.reb += p.reb || 0;
          t.oreb += p.oreb || 0;
          t.dreb += p.dreb || 0;
          t.ast += p.ast || 0;
          t.stl += p.stl || 0;
          t.blk += p.blk || 0;
          t.tov += p.tov || 0;
          t.pf += p.pf || 0;
        });
      }
      return t;
    });
    totals.sort((a, b) => b.pts - a.pts);

    return `<div style="margin-bottom:24px;">
      <h3 style="color:var(--accent); margin-bottom:8px; font-size:14px;">${escapeHtml(teamAbbr)}</h3>
      ${totals.map(p => renderPlayerCard(p)).join('')}
    </div>`;
  };

  const html = Object.keys(teams).sort().map(t => buildTeamSection(t, teams[t])).join('');
  container.innerHTML = html;
}

function renderPlayerCard(p) {
  const periodBadges = p.periods.map(pp => {
    const timeIn = pp.time_in ? formatClock(pp.time_in) : I18N.t('games.start');
    const timeOut = pp.time_out ? formatClock(pp.time_out) : I18N.t('games.end');
    const hasStats = (pp.pts || 0) + (pp.reb || 0) + (pp.ast || 0) + (pp.tov || 0) + (pp.pf || 0) > 0;
    const statsSummary = hasStats
      ? ` | ${pp.pts || 0}PTS ${pp.reb || 0}REB ${pp.ast || 0}AST ${pp.tov || 0}TOV ${pp.pf || 0}PF`
      : '';
    return `<span style="display:inline-block; background:var(--bg-dark); border-radius:4px; padding:2px 6px; margin:2px; font-size:11px; font-family:var(--mono);">
      Q${pp.period}: ${timeIn} → ${timeOut}${statsSummary}
    </span>`;
  }).join('');

  // Foul details
  const foulDetails = p.periods.flatMap(pp => (pp.foul_details || []).map(d => ({...d, period: pp.period})));
  const tovDetails = p.periods.flatMap(pp => (pp.tov_details || []).map(d => ({...d, period: pp.period})));

  const detailsHtml = [];
  if (foulDetails.length > 0) {
    detailsHtml.push(`<div style="margin-top:4px; font-size:11px; color:var(--warning);">
      <b>${I18N.t('games.fouls')}:</b> ${foulDetails.map(d => `Q${d.period} ${formatClock(d.clock)} (${escapeHtml(d.desc)})`).join('; ')}
    </div>`);
  }
  if (tovDetails.length > 0) {
    detailsHtml.push(`<div style="margin-top:4px; font-size:11px; color:var(--danger);">
      <b>${I18N.t('games.turnovers')}:</b> ${tovDetails.map(d => `Q${d.period} ${formatClock(d.clock)} (${escapeHtml(d.desc)})`).join('; ')}
    </div>`);
  }

  return `<div style="background:var(--bg-dark); border-radius:8px; padding:10px; margin-bottom:8px; border-left:3px solid var(--accent);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
      <div style="font-weight:600; font-size:14px;">${escapeHtml(p.player)}</div>
      <div style="font-family:var(--mono); font-size:13px;">
        <span style="color:var(--accent); font-weight:700;">${p.pts}PTS</span>
        <span style="color:var(--text-dim); margin:0 6px;">|</span>
        ${p.fgm}/${p.fga}FG ${p.fg3m}/${p.fg3a}3P ${p.ftm}/${p.fta}FT
        <span style="color:var(--text-dim); margin:0 6px;">|</span>
        ${p.reb}REB ${p.ast}AST ${p.stl}STL ${p.blk}BLK ${p.tov}TOV ${p.pf}PF
      </div>
    </div>
    <div style="font-size:11px; color:var(--text-dim);">Periods:</div>
    <div style="margin-top:2px;">${periodBadges}</div>
    ${detailsHtml.join('')}
  </div>`;
}

// ── System Page ──
async function loadSystemPage() {
  const season = document.getElementById('sysSeasonSelect').value;

  // Load status
  try {
    const status = await api('/system/status?season=' + season);
    document.getElementById('sysDbStatus').innerHTML =
      status.database_connected
        ? '<span style="color:var(--accent);">' + I18N.t('system.connected') + '</span>'
        : '<span style="color:var(--danger);">' + I18N.t('system.disconnected') + '</span>';
    document.getElementById('sysTableCount').textContent = status.table_count ?? status.total_tables ?? (status.tables ? status.tables.length : '—');
    document.getElementById('sysTotalRecords').textContent = status.total_records ?? status.records ?? '—';
  } catch (e) {
    document.getElementById('sysDbStatus').innerHTML = '<span style="color:var(--danger);">' + I18N.t('common.error') + '</span>';
    toast(I18N.t('system.failedLoadStatus') + ': ' + e.message, 'error');
  }

  // Load tables
  loadSystemTables();
}

async function loadSystemTables() {
  const tbody = document.getElementById('sysTablesBody');
  tbody.innerHTML = `<tr><td colspan="2" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;

  try {
    const d = await api('/system/tables');
    const tables = d.tables || d.data || [];

    if (tables.length === 0) {
      tbody.innerHTML = `<tr><td colspan="2" style="text-align:center; padding:30px; color:var(--text-dim);">
        ${I18N.t('system.noTablesFound')}
      </td></tr>`;
      return;
    }

    tbody.innerHTML = tables.map(t => {
      const name = escapeHtml(t.table_name || t.name || t);
      const count = t.row_count ?? t.count ?? t.rows ?? '—';
      return `<tr style="cursor:pointer;" onclick="loadTableData('${name}')">
        <td style="font-weight:600; font-family:var(--mono);">${name}</td>
        <td style="text-align:right; font-family:var(--mono); color:var(--text-dim);">${count.toLocaleString ? count.toLocaleString() : count}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="2" style="text-align:center; padding:30px; color:var(--danger);">
      ${I18N.t('common.failedToLoad')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

async function loadTableData(tableName) {
  currentSysTable = tableName;
  sysDataPage = 1;
  const card = document.getElementById('sysTableDataCard');
  card.style.display = 'block';
  document.getElementById('sysTableDataTitle').textContent = I18N.t('system.tableName') + ': ' + tableName;
  await loadSysTableDataPage();
}

async function loadSysTableDataPage() {
  const perPage = 50;
  const thead = document.getElementById('sysDataTableHead');
  const tbody = document.getElementById('sysDataTableBody');

  tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--text-dim);">
    <div class="spinner"></div> ${I18N.t('common.loading')}
  </td></tr>`;

  try {
    const d = await api('/system/tables/' + currentSysTable + '?page=' + sysDataPage + '&per_page=' + perPage);
    const rows = d.rows || d.data || [];
    const total = d.total || d.count || 0;
    sysDataTotalPages = Math.ceil(total / perPage) || 1;

    document.getElementById('sysDataPageInfo').textContent = sysDataPage + ' / ' + sysDataTotalPages;
    document.getElementById('sysDataPrevBtn').disabled = sysDataPage <= 1;
    document.getElementById('sysDataNextBtn').disabled = sysDataPage >= sysDataTotalPages;

    if (rows.length === 0) {
      thead.innerHTML = '';
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--text-dim);">
        ${I18N.t('common.noData')}
      </td></tr>`;
      return;
    }

    const columns = Object.keys(rows[0]);
    thead.innerHTML = `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>`;

    tbody.innerHTML = rows.map(row => `<tr>
      ${columns.map(c => {
        const val = row[c];
        let display = val;
        if (val == null) display = '—';
        else if (typeof val === 'object') display = escapeHtml(JSON.stringify(val));
        else if (typeof val === 'number') display = Number.isInteger(val) ? val : val.toFixed(3);
        else display = escapeHtml(String(val));
        return `<td style="font-family:var(--mono); font-size:12px;">${display}</td>`;
      }).join('')}
    </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--danger);">
      ${I18N.t('common.failedToLoad')}: ${escapeHtml(e.message)}
    </td></tr>`;
  }
}

function sysDataPrevPage() {
  if (sysDataPage > 1) {
    sysDataPage--;
    loadSysTableDataPage();
  }
}

function sysDataNextPage() {
  if (sysDataPage < sysDataTotalPages) {
    sysDataPage++;
    loadSysTableDataPage();
  }
}

// ── Resize Handler ──
window.addEventListener('resize', () => {
  Object.values(charts).forEach(c => c && c.resize());
});

// ── Export Functions ──
function exportRankings(format) {
  const source = document.getElementById('rankSourceSelect').value;
  const metric = document.getElementById('rankMetricSelect').value;
  const season = document.getElementById('rankSeasonSelect').value;
  if (!metric) { toast(I18N.t('common.selectStatFirst'), 'error'); return; }

  if (source === 'metric') {
    const url = '/export/rankings?metric=' + encodeURIComponent(metric) +
      '&season=' + season + '&format=' + format + '&limit=50';
    window.location.href = url;
    toast(I18N.t('common.exporting') + format.toUpperCase() + '...', 'success');
  } else {
    toast(I18N.t('rankings.exportNotAvailable'), 'error');
  }
}

function exportVS(format) {
  if (!player1 || !player2) { toast(I18N.t('common.selectBothPlayers'), 'error'); return; }
  const season = document.getElementById('seasonSelect').value;
  const metrics = Array.from(selectedMetrics).join(',');
  const url = '/export/vs?p1=' + encodeURIComponent(player1.player_id) +
    '&p2=' + encodeURIComponent(player2.player_id) +
    '&season=' + season + '&format=' + format +
    (metrics ? '&metrics=' + encodeURIComponent(metrics) : '');
  window.location.href = url;
  toast(I18N.t('common.exporting') + format.toUpperCase() + '...', 'success');
}

// ── Growth Report Page ──
let growthPlayer = null;
let growthCharts = {};

function searchGrowthPlayer() {
  const q = document.getElementById('growthPlayerSearch').value;
  if (searchTimeouts.growth) clearTimeout(searchTimeouts.growth);
  if (q.length < 2) {
    document.getElementById('growthPlayerDropdown').style.display = 'none';
    return;
  }
  searchTimeouts.growth = setTimeout(async () => {
    try {
      const r = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
      const dd = document.getElementById('growthPlayerDropdown');
      if (!r.players || r.players.length === 0) {
        dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">' + I18N.t('common.noResults') + '</div>';
      } else {
        dd.innerHTML = r.players.map(p =>
          `<div class="dropdown-item" onmousedown="selectGrowthPlayer('${p.player_id}', '${p.player_name.replace(/'/g, "\\'")}')">
            <strong>${p.player_name}</strong>
            <span style="color:var(--text-dim); margin-left:8px; font-size:12px;">${p.position || ''} · ${p.team || ''}</span>
          </div>`
        ).join('');
      }
      dd.style.display = 'block';
    } catch (e) {
      console.error(e);
    }
  }, 250);
}

function showGrowthDropdown() {
  const q = document.getElementById('growthPlayerSearch').value;
  if (q.length >= 2) {
    document.getElementById('growthPlayerDropdown').style.display = 'block';
  }
}

function hideGrowthDropdownDelay() {
  setTimeout(() => {
    document.getElementById('growthPlayerDropdown').style.display = 'none';
  }, 150);
}

function selectGrowthPlayer(playerId, playerName) {
  document.getElementById('growthPlayerSearch').value = playerName;
  document.getElementById('growthPlayerDropdown').style.display = 'none';
  loadGrowthReport(playerId);
}

function loadLeBronExample() {
  document.getElementById('growthPlayerSearch').value = 'LeBron James';
  loadGrowthReport('jamesle01');
}

async function loadGrowthReport(playerId) {
  growthPlayer = playerId;
  try {
    const report = await api('/players/' + playerId + '/growth');
    renderGrowthReport(report);
  } catch (e) {
    toast('加载失败: ' + e.message, 'error');
  }
}

function getGrowthChart(id) {
  if (!growthCharts[id]) {
    const el = document.getElementById(id);
    if (el) growthCharts[id] = echarts.init(el);
  }
  return growthCharts[id];
}

function disposeGrowthCharts() {
  Object.values(growthCharts).forEach(c => c.dispose());
  growthCharts = {};
}

function seasonLabel(s) {
  const start = s - 1;
  const end = s % 100;
  return `${start}-${end < 10 ? '0' + end : end}`;
}

function renderGrowthReport(report) {
  disposeGrowthCharts();

  document.getElementById('growthEmpty').style.display = 'none';
  document.getElementById('growthResults').style.display = 'block';

  const { bio, seasons, positions, shooting, milestones } = report;

  // Bio
  document.getElementById('growthPlayerName').textContent = bio.player_name || bio.full_name || '—';
  document.getElementById('growthPlayerPos').textContent = bio.position || '—';
  document.getElementById('growthHeight').textContent = bio.height_display
    ? `${bio.height_display} (${bio.height_cm}cm)` : '—';
  document.getElementById('growthWeight').textContent = bio.weight_lbs
    ? `${bio.weight_lbs} lbs / ${bio.weight_kg} kg` : '—';
  document.getElementById('growthBirth').textContent = bio.birth_date || '—';
  document.getElementById('growthCareer').textContent = (bio.year_from && bio.year_to)
    ? `${bio.year_from} - ${bio.year_to} (${bio.experience || '—'} 个赛季)` : '—';

  // Totals
  document.getElementById('growthTotalGames').textContent = formatNum(bio.total_games);
  document.getElementById('growthTotalPts').textContent = formatNum(bio.total_points);
  document.getElementById('growthTotalOReb').textContent = formatNum(bio.total_offensive_rebounds);
  document.getElementById('growthTotalDReb').textContent = formatNum(bio.total_defensive_rebounds);
  document.getElementById('growthTotalAst').textContent = formatNum(bio.total_assists);
  document.getElementById('growthTotalSteals').textContent = formatNum(bio.total_steals);
  document.getElementById('growthTotalBlocks').textContent = formatNum(bio.total_blocks);
  document.getElementById('growthTotalFouls').textContent = formatNum(bio.total_fouls);

  // Milestones
  renderMilestones(milestones);

  // Season count
  document.getElementById('growthSeasonCount').textContent = seasons.length + ' 个赛季';

  // Charts
  renderScoringChart(seasons);
  renderPerChart(seasons);
  renderRebAstChart(seasons);
  renderWsChart(seasons);
  renderPosPieChart(positions);
  renderPosRadarChart(positions);
  if (shooting && shooting.length > 0) {
    renderShootingChart(shooting);
  }
  renderPhysChart(bio, seasons);
  renderShootingPctChart(seasons);
  renderAdvancedChart(seasons);
  renderMinutesChart(seasons);

  // Tables
  renderSeasonTable(seasons);
  renderPosTable(positions);

  // v8.1 Deep Analysis cards
  loadV81Analysis(growthPlayer, report);
}

function formatNum(n) {
  if (n == null) return '—';
  return n.toLocaleString();
}

function renderMilestones(milestones) {
  const container = document.getElementById('growthMilestones');
  const typeColors = {
    debut: '#10b981',
    peak_scoring: '#f59e0b',
    peak_per: '#8b5cf6',
    peak_ws: '#3b82f6',
    breakout: '#ef4444',
    position_change: '#06b6d4',
    current: THEME.textDim,
  };
  container.innerHTML = milestones.map(m => {
    const color = typeColors[m.type] || THEME.textDim;
    return `<div style="flex:0 0 auto; min-width:180px; background:var(--bg-card); border:1px solid var(--border); border-left:4px solid ${color}; border-radius:8px; padding:12px 16px;">
      <div style="font-size:12px; color:var(--text-dim); margin-bottom:4px;">${m.season}赛季</div>
      <div style="font-weight:600; margin-bottom:4px;">${m.label}</div>
      <div style="font-size:14px; color:var(--accent); margin-bottom:4px;">${m.value}</div>
      <div style="font-size:12px; color:var(--text-dim);">${m.detail || ''}</div>
    </div>`;
  }).join('');
}

function renderScoringChart(seasons) {
  const chart = getGrowthChart('growthScoringChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const ppg = seasons.map(s => s.pts_per_game);
  const scoringShare = seasons.map(s => s.scoring_share || null);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['场均得分', '球队得分占比%'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'PPG',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { lineStyle: { color: THEME.border } },
      },
      {
        type: 'value',
        name: '得分占比%',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '场均得分',
        type: 'line',
        data: ppg,
        smooth: true,
        itemStyle: { color: '#f59e0b' },
        areaStyle: { color: 'rgba(245, 158, 11, 0.1)' },
        symbol: 'circle',
        symbolSize: 6,
      },
      {
        name: '球队得分占比%',
        type: 'line',
        yAxisIndex: 1,
        data: scoringShare,
        smooth: true,
        itemStyle: { color: '#8b5cf6' },
        symbol: 'circle',
        symbolSize: 5,
      },
    ],
  });
}

function renderPerChart(seasons) {
  const chart = getGrowthChart('growthPerChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const per = seasons.map(s => s.per);
  const usg = seasons.map(s => s.usg_percent);
  const ts = seasons.map(s => s.ts_percent ? s.ts_percent * 100 : null);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['PER', 'USG%', 'TS%'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: THEME.textDim },
      splitLine: { lineStyle: { color: THEME.border } },
    },
    series: [
      {
        name: 'PER',
        type: 'line',
        data: per,
        smooth: true,
        itemStyle: { color: '#3b82f6' },
        symbol: 'circle',
        symbolSize: 6,
      },
      {
        name: 'USG%',
        type: 'line',
        data: usg,
        smooth: true,
        itemStyle: { color: '#ef4444' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: 'TS%',
        type: 'line',
        data: ts,
        smooth: true,
        itemStyle: { color: '#10b981' },
        symbol: 'circle',
        symbolSize: 5,
      },
    ],
  });
}

function renderRebAstChart(seasons) {
  const chart = getGrowthChart('growthRebAstChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const orpg = seasons.map(s => s.orb_per_game);
  const drpg = seasons.map(s => s.drb_per_game);
  const apg = seasons.map(s => s.ast_per_game);
  const spg = seasons.map(s => s.stl_per_game);
  const bpg = seasons.map(s => s.blk_per_game);
  const sbf = seasons.map(s => s.steal_block_per_foul || null);
  const apt = seasons.map(s => s.ast_per_tov || null);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['进攻篮板', '防守篮板', '助攻', '抢断', '盖帽', '(抢断+盖帽)/犯规', '助攻/失误'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 50, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: [
      {
        type: 'value',
        axisLabel: { color: THEME.textDim },
        splitLine: { lineStyle: { color: THEME.border } },
      },
      {
        type: 'value',
        axisLabel: { color: THEME.textDim },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '进攻篮板',
        type: 'bar',
        data: orpg,
        itemStyle: { color: 'rgba(59, 130, 246, 0.6)' },
        barWidth: '20%',
      },
      {
        name: '防守篮板',
        type: 'bar',
        data: drpg,
        itemStyle: { color: 'rgba(59, 130, 246, 0.3)' },
        barWidth: '20%',
      },
      {
        name: '助攻',
        type: 'line',
        data: apg,
        smooth: true,
        itemStyle: { color: '#8b5cf6' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: '抢断',
        type: 'line',
        data: spg,
        smooth: true,
        itemStyle: { color: '#10b981' },
        symbol: 'circle',
        symbolSize: 4,
      },
      {
        name: '盖帽',
        type: 'line',
        data: bpg,
        smooth: true,
        itemStyle: { color: '#f59e0b' },
        symbol: 'circle',
        symbolSize: 4,
      },
      {
        name: '(抢断+盖帽)/犯规',
        type: 'line',
        yAxisIndex: 1,
        data: sbf,
        smooth: true,
        itemStyle: { color: '#ef4444' },
        symbol: 'diamond',
        symbolSize: 5,
      },
      {
        name: '助攻/失误',
        type: 'line',
        yAxisIndex: 1,
        data: apt,
        smooth: true,
        itemStyle: { color: '#06b6d4' },
        symbol: 'diamond',
        symbolSize: 5,
      },
    ],
  });
}

function renderWsChart(seasons) {
  const chart = getGrowthChart('growthWsChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const ws = seasons.map(s => s.ws);
  const vorp = seasons.map(s => s.vorp);
  const bpm = seasons.map(s => s.bpm);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['WS', 'VORP', 'BPM'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: THEME.textDim },
      splitLine: { lineStyle: { color: THEME.border } },
    },
    series: [
      {
        name: 'WS',
        type: 'bar',
        data: ws,
        itemStyle: { color: 'rgba(59, 130, 246, 0.7)' },
        barWidth: '50%',
      },
      {
        name: 'VORP',
        type: 'line',
        data: vorp,
        smooth: true,
        itemStyle: { color: '#ef4444' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: 'BPM',
        type: 'line',
        data: bpm,
        smooth: true,
        itemStyle: { color: '#10b981' },
        symbol: 'circle',
        symbolSize: 4,
      },
    ],
  });
}

function renderPosPieChart(positions) {
  const chart = getGrowthChart('growthPosPieChart');
  const data = positions.map(p => ({
    name: (p.pos_cn || p.pos) + ' (' + p.pos + ')',
    value: p.total_games,
  }));

  const colors = ['#3b82f6', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6', '#06b6d4', '#f97316'];

  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 场 ({d}%)',
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { color: THEME.textDim },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: THEME.textDim,
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold', color: '#fff' },
        },
        data: data,
        color: colors,
      },
    ],
  });
}

function renderPosRadarChart(positions) {
  const chart = getGrowthChart('growthPosRadarChart');

  const topPositions = positions.slice(0, 5);
  const indicators = [
    { name: '得分', max: Math.max(...topPositions.map(p => p.ppg || 0)) * 1.2 || 30 },
    { name: '篮板', max: Math.max(...topPositions.map(p => p.rpg || 0)) * 1.2 || 15 },
    { name: '助攻', max: Math.max(...topPositions.map(p => p.apg || 0)) * 1.2 || 12 },
    { name: 'PER', max: Math.max(...topPositions.map(p => p.avg_per || 0)) * 1.2 || 35 },
    { name: 'USG%', max: Math.max(...topPositions.map(p => p.avg_usg || 0)) * 1.2 || 40 },
  ];

  const colors = ['#3b82f6', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6'];

  const series = topPositions.map((p, i) => ({
    name: p.pos_cn || p.pos,
    type: 'radar',
    data: [{
      value: [p.ppg || 0, p.rpg || 0, p.apg || 0, p.avg_per || 0, p.avg_usg || 0],
      name: p.pos_cn || p.pos,
      areaStyle: { opacity: 0.1 },
      lineStyle: { width: 2 },
    }],
    itemStyle: { color: colors[i] },
  }));

  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: {
      data: topPositions.map(p => p.pos_cn || p.pos),
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    radar: {
      indicator: indicators,
      axisName: { color: THEME.textDim },
      splitLine: { lineStyle: { color: THEME.axisLine } },
      splitArea: { areaStyle: { color: ['rgba(31, 41, 55, 0.3)', 'rgba(31, 41, 55, 0.1)'] } },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    series: series,
  });
}

function renderShootingChart(shooting) {
  const chart = getGrowthChart('growthShootingChart');
  const seasonsLabels = shooting.map(s => seasonLabel(s.season));
  
  const zoneNames = ['0-3英尺', '3-10英尺', '10-16英尺', '16-三分线', '三分球'];
  const zoneColors = ['#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6'];
  
  const series = zoneNames.map((name, i) => {
    const fieldName = `percent_fga_from_x${[0, 3, 10, 16, '3p'][i]}_range`;
    return {
      name: name,
      type: 'bar',
      stack: 'total',
      data: shooting.map(s => (s[fieldName] || 0) * 100),
      itemStyle: { color: zoneColors[i] },
    };
  });

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: function(params) {
        let result = params[0].axisValue + '<br/>';
        let total = 0;
        params.forEach(p => {
          total += p.value;
          result += `${p.marker} ${p.seriesName}: ${p.value.toFixed(1)}%<br/>`;
        });
        result += `总计: ${total.toFixed(1)}%`;
        return result;
      },
    },
    legend: {
      data: zoneNames,
      textStyle: { color: THEME.textDim },
      bottom: 0,
    },
    grid: { left: 50, right: 20, top: 40, bottom: 60 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: {
      type: 'value',
      name: '出手占比%',
      nameTextStyle: { color: THEME.textDim },
      axisLabel: { color: THEME.textDim, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border } },
      max: 100,
    },
    series: series,
  });
}

function renderPhysChart(bio, seasons) {
  const chart = getGrowthChart('growthPhysChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  
  const height = bio.height_cm || 0;
  const weight = bio.weight_kg || 0;
  
  const ages = seasons.map(s => s.age);
  const weights = seasons.map(() => weight);
  const heights = seasons.map(() => height);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['年龄', '身高(cm)', '体重(kg)'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: [
      {
        type: 'value',
        name: '年龄',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { lineStyle: { color: THEME.border } },
      },
      {
        type: 'value',
        name: 'cm/kg',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '年龄',
        type: 'line',
        data: ages,
        smooth: true,
        itemStyle: { color: '#8b5cf6' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: '身高(cm)',
        type: 'line',
        yAxisIndex: 1,
        data: heights,
        smooth: false,
        itemStyle: { color: '#3b82f6' },
        symbol: 'none',
        lineStyle: { type: 'dashed' },
      },
      {
        name: '体重(kg)',
        type: 'line',
        yAxisIndex: 1,
        data: weights,
        smooth: false,
        itemStyle: { color: '#f59e0b' },
        symbol: 'none',
        lineStyle: { type: 'dashed' },
      },
    ],
  });
}

function renderShootingPctChart(seasons) {
  const chart = getGrowthChart('growthShootingPctChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const fg = seasons.map(s => s.fg_percent ? s.fg_percent * 100 : null);
  const x3p = seasons.map(s => s.x3p_percent ? s.x3p_percent * 100 : null);
  const ft = seasons.map(s => s.ft_percent ? s.ft_percent * 100 : null);
  const efg = seasons.map(s => s.e_fg_percent ? s.e_fg_percent * 100 : null);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['投篮命中率', '三分命中率', '罚球命中率', '有效命中率'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: {
      type: 'value',
      name: '命中率%',
      nameTextStyle: { color: THEME.textDim },
      axisLabel: { color: THEME.textDim, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border } },
      max: 70,
    },
    series: [
      {
        name: '投篮命中率',
        type: 'line',
        data: fg,
        smooth: true,
        itemStyle: { color: '#3b82f6' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: '三分命中率',
        type: 'line',
        data: x3p,
        smooth: true,
        itemStyle: { color: '#ef4444' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: '罚球命中率',
        type: 'line',
        data: ft,
        smooth: true,
        itemStyle: { color: '#10b981' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: '有效命中率',
        type: 'line',
        data: efg,
        smooth: true,
        itemStyle: { color: '#f59e0b' },
        symbol: 'diamond',
        symbolSize: 5,
      },
    ],
  });
}

function renderAdvancedChart(seasons) {
  const chart = getGrowthChart('growthAdvancedChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const per = seasons.map(s => s.per);
  const ts = seasons.map(s => s.ts_percent ? s.ts_percent * 100 : null);
  const ws = seasons.map(s => s.ws);
  const bpm = seasons.map(s => s.bpm);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['PER', 'TS%', 'WS', 'BPM'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'PER/WS',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { lineStyle: { color: THEME.border } },
      },
      {
        type: 'value',
        name: '%/BPM',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'PER',
        type: 'line',
        data: per,
        smooth: true,
        itemStyle: { color: '#8b5cf6' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: 'TS%',
        type: 'line',
        yAxisIndex: 1,
        data: ts,
        smooth: true,
        itemStyle: { color: '#10b981' },
        symbol: 'circle',
        symbolSize: 5,
      },
      {
        name: 'WS',
        type: 'bar',
        data: ws,
        itemStyle: { color: 'rgba(59, 130, 246, 0.6)' },
        barWidth: '20%',
      },
      {
        name: 'BPM',
        type: 'line',
        yAxisIndex: 1,
        data: bpm,
        smooth: true,
        itemStyle: { color: '#f59e0b' },
        symbol: 'circle',
        symbolSize: 5,
      },
    ],
  });
}

function renderMinutesChart(seasons) {
  const chart = getGrowthChart('growthMinutesChart');
  const seasonsLabels = seasons.map(s => seasonLabel(s.season));
  const mpg = seasons.map(s => Number(s.mp_per_game));
  const g = seasons.map(s => s.g);
  const gs = seasons.map(s => s.gs);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['场均出场时间', '出场场次', '首发场次'], textStyle: { color: THEME.textDim } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: seasonsLabels,
      axisLabel: { color: THEME.textDim, rotate: 45, fontSize: 10 },
      axisLine: { lineStyle: { color: THEME.axisLine } },
    },
    yAxis: [
      {
        type: 'value',
        name: '分钟',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { lineStyle: { color: THEME.border } },
      },
      {
        type: 'value',
        name: '场次',
        nameTextStyle: { color: THEME.textDim },
        axisLabel: { color: THEME.textDim },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '场均出场时间',
        type: 'line',
        data: mpg,
        smooth: true,
        itemStyle: { color: '#3b82f6' },
        symbol: 'circle',
        symbolSize: 5,
        areaStyle: { color: 'rgba(59, 130, 246, 0.1)' },
      },
      {
        name: '出场场次',
        type: 'bar',
        yAxisIndex: 1,
        data: g,
        itemStyle: { color: 'rgba(16, 185, 129, 0.5)' },
        barWidth: '30%',
      },
      {
        name: '首发场次',
        type: 'bar',
        yAxisIndex: 1,
        data: gs,
        itemStyle: { color: 'rgba(16, 185, 129, 0.8)' },
        barWidth: '30%',
      },
    ],
  });
}

function renderSeasonTable(seasons) {
  const tbody = document.getElementById('growthSeasonTableBody');
  const num = v => v == null || v === '' ? null : Number(v);
  const fmt = (v, d = 1) => v == null || v === '' ? '—' : Number(v).toFixed(d);
  tbody.innerHTML = seasons.map(s => `
    <tr>
      <td>${seasonLabel(s.season)}</td>
      <td>${s.age || '—'}</td>
      <td>${s.team || '—'}</td>
      <td><span class="pos-badge">${s.pos_cn || s.pos || '—'}</span></td>
      <td style="text-align:right;">${s.g || 0}</td>
      <td style="text-align:right; font-weight:600;">${fmt(s.pts_per_game)}</td>
      <td style="text-align:right;">${fmt(s.trb_per_game)}</td>
      <td style="text-align:right;">${fmt(s.ast_per_game)}</td>
      <td style="text-align:right;">${fmt(s.per)}</td>
      <td style="text-align:right;">${fmt(s.usg_percent)}</td>
      <td style="text-align:right;">${fmt(s.ws)}</td>
      <td style="text-align:right;">${fmt(s.ts_percent != null ? Number(s.ts_percent) * 100 : null)}</td>
    </tr>
  `).join('');
}

function renderPosTable(positions) {
  const tbody = document.getElementById('growthPosTableBody');
  const fmt = (v, d = 1) => v == null || v === '' ? '—' : Number(v).toFixed(d);
  tbody.innerHTML = positions.map(p => `
    <tr>
      <td><span class="pos-badge">${p.pos_cn || p.pos}</span></td>
      <td style="text-align:right;">${p.seasons || 0}</td>
      <td style="text-align:right;">${p.total_games || 0}</td>
      <td style="text-align:right; font-weight:600;">${fmt(p.ppg)}</td>
      <td style="text-align:right;">${fmt(p.rpg)}</td>
      <td style="text-align:right;">${fmt(p.apg)}</td>
      <td style="text-align:right;">${fmt(p.avg_per)}</td>
      <td style="text-align:right;">${fmt(p.avg_usg)}</td>
    </tr>
  `).join('');
}

// ── v8.1 Deep Analysis ──
function loadV81Analysis(playerId, report) {
  if (!report || !window.V81) return;
  const seasons = report.seasons || [];
  const latest = seasons.length ? seasons[seasons.length - 1] : null;
  try {
    window.V81.renderReboundingCard('rebCard', latest);
    window.V81.renderPlaymakingCard('playCard', latest);
    window.V81.renderDefenseProfileCard('defCard', latest);
    window.V81.renderTeamContributionChart('teamShareChart', seasons);
  } catch (e) {
    console.error('[v8.1] card render failed', e);
  }
  api('/players/' + playerId + '/shooting-profile').then(d => {
    window.V81.renderShotProfileChart('shotChart', d);
    setTimeout(resizeAllCharts, 60);
  }).catch(e => renderV81Error('shotChart', '投篮数据加载失败', e.message));
  api('/players/' + playerId + '/career-defense').then(d => {
    window.V81.renderCareerDefenseSummary('careerDefCard', d);
  }).catch(e => renderV81Error('careerDefCard', '生涯防守数据加载失败', e.message));
  setTimeout(resizeAllCharts, 90);
}

function renderV81Error(containerId, title, msg) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">' + escapeHtml(title) + '</div></div><div class="v81-empty" style="color:var(--danger);">出错: ' + escapeHtml(msg) + '</div></div>';
}

// ── Intelligence Page (v8.2) ──
async function loadIntelligencePage() {
  const root = document.getElementById('intelRoot');
  if (!root) return;
  if (!window.Intelligence) {
    root.innerHTML = '<div class="card"><div class="v81-empty" style="color:var(--danger);">情报组件未加载，请刷新页面</div></div>';
    return;
  }

  let seasons = [2025, 2024, 2023];
  try {
    seasons = await api('/players/seasons');
    if (!Array.isArray(seasons)) seasons = [2025, 2024, 2023];
  } catch (e) {
    // fallback seasons
  }

  const opts = seasons.map(s => `<option value="${s}">${seasonLabel(s)}</option>`).join('');
  const defSeason = seasons.includes(2025) ? 2025 : seasons[0];

  root.innerHTML = `
    <div class="page-header">
      <h2>Player Intelligence · 球员情报</h2>
    </div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">查询球员情报</div>
      </div>
      <div class="form-row" style="align-items:flex-end;">
        <div style="flex:1; min-width:240px; position:relative;">
          <label class="label">球员名（模糊搜索）</label>
          <input class="input" id="intelNameSearch" type="text" placeholder="输入球员名，如 LeBron" oninput="IntelSearch.onSearch()" onblur="setTimeout(IntelSearch.hideDropdown,200)">
          <div class="dropdown" id="intelNameDropdown"></div>
        </div>
        <div style="min-width:160px;">
          <label class="label">赛季</label>
          <select class="select" id="intelSeasonSelect">${opts}</select>
        </div>
        <button class="btn btn-primary" id="intelLoadBtn" onclick="loadIntelResult()">加载情报</button>
      </div>
    </div>
    <div id="intelResult"></div>
  `;

  const sel = document.getElementById('intelSeasonSelect');
  if (defSeason) sel.value = defSeason;

  // Auto-load a default player by name (no hard-coded player_id required).
  const intelNameInput = document.getElementById('intelNameSearch');
  if (intelNameInput) {
    intelNameInput.value = 'LeBron James';
    IntelSearch.onSearch(true);
  }
}

async function loadIntelResult() {
  const pid = intelPid;
  const season = (document.getElementById('intelSeasonSelect') || {}).value;
  if (!pid) { toast('请选择球员', 'error'); return; }
  if (!window.Intelligence) return;
  await window.Intelligence.render('intelResult', pid.trim(), season);
}

// ── Player Intelligence name fuzzy-search helper (self-contained, mirrors AgeCurve) ──
let intelPid = '';

const IntelSearch = {
  _nameMap: {},
  onSearch: async function (autoSelectFirst) {
    const input = document.getElementById('intelNameSearch');
    const q = input ? input.value.trim() : '';
    if (q.length < 2) { IntelSearch.hideDropdown(); return; }
    try {
      const d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
      const dd = document.getElementById('intelNameDropdown');
      if (!dd) return;
      const list = (d && d.players) || [];
      IntelSearch._nameMap = {};
      if (list.length === 0) {
        dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">无匹配球员</div>';
      } else {
        dd.innerHTML = list.map(function (p) {
          const pid = p.player_id || '';
          const nm = p.full_name || p.player_name || pid;
          IntelSearch._nameMap[pid] = nm;
          const sub = [p.team_abbr || p.team, p.position].filter(Boolean).map(escapeHtml).join(' · ');
          return '<div class="dropdown-item" onmousedown="IntelSearch.onSelect(\'' + pid + '\')">' +
            '<div>' + escapeHtml(nm) + '</div>' +
            (sub ? '<div class="sub">' + sub + '</div>' : '') + '</div>';
        }).join('');
      }
      if (autoSelectFirst && list.length) {
        IntelSearch.onSelect(list[0].player_id);
      } else {
        IntelSearch.showDropdown();
      }
    } catch (e) {
      if (typeof toast === 'function') toast(e.message, 'error');
    }
  },
  onSelect: function (pid) {
    if (!pid) return;
    intelPid = pid;
    const input = document.getElementById('intelNameSearch');
    if (input) input.value = IntelSearch._nameMap[pid] || pid;
    IntelSearch.hideDropdown();
    loadIntelResult();
  },
  showDropdown: function () {
    const input = document.getElementById('intelNameSearch');
    const q = input ? input.value.trim() : '';
    if (q.length < 2) return;
    const dd = document.getElementById('intelNameDropdown');
    if (dd) dd.classList.add('show');
  },
  hideDropdown: function () {
    const dd = document.getElementById('intelNameDropdown');
    if (dd) dd.classList.remove('show');
  }
};

// ── DIY分析 Page (merged Workspace + Analytics Builder · v8.3) ──
async function loadWorkspacePage() {
  const root = document.getElementById('workspaceRoot');
  if (!root) return;
  if (!window.Workspace) {
    root.innerHTML = '<div class="card"><div class="v81-empty" style="color:var(--danger);">工作区组件未加载，请刷新页面</div></div>';
    return;
  }
  await window.Workspace.renderList('workspaceRoot');

  // Render the Analytics Builder block beneath the Workspace content.
  const abRoot = document.getElementById('analyticsBuilderRoot');
  if (abRoot && window.AnalyticsBuilder && typeof window.AnalyticsBuilder.render === 'function') {
    window.AnalyticsBuilder.render('analyticsBuilderRoot');
  }
}

// ── Init ──
async function init() {
  checkServerStatus();
  await initSeasonSelectors();
  await loadMetrics();
  setInterval(checkServerStatus, 30000);
}

document.addEventListener('DOMContentLoaded', init);

// Expose globals so component scripts can reuse shared config/helpers
window.THEME = THEME;
window.escapeHtml = escapeHtml;
