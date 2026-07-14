// NBACore v8.1 §7/§10.2 — ShotProfileChart (pure render, no computation).
// Consumes GET /players/{id}/shooting-profile (zones = {zone, fg_pct, fga_rate}).
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { accent: '#00b88a', purple: '#8b5cf6', textDim: '#7f8c9b', border: '#e1e8f0' };
  const sl = (s) => { if (!s) return '—'; const st = s - 1, en = s % 100; return st + '-' + (en < 10 ? '0' + en : en); };
  const initChart = (el) => { const i = (typeof echarts !== 'undefined' && echarts.getInstanceByDom(el)); if (i) i.dispose(); return echarts.init(el); };
  const track = (key, inst) => { if (typeof charts !== 'undefined') charts[key] = inst; };

  const ZONE_CN = {
    restricted_area: '禁区', paint: '油漆区', mid_range: '中距离',
    long_two: '长两分', three_point: '三分线外',
  };

  V81.renderShotProfileChart = function (containerId, profile) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const seasons = (profile && profile.seasons) || [];
    let latest = null;
    for (let i = seasons.length - 1; i >= 0; i--) {
      if (seasons[i].zones && seasons[i].zones.length) { latest = seasons[i]; break; }
    }
    if (!latest) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">投篮热区 <span class="v81-sub">Shot Profile</span></div></div><div class="v81-empty">暂无投篮数据</div></div>';
      return;
    }
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">投篮热区 <span class="v81-sub">Shot Profile</span></div>
          <div class="card-badge">${sl(latest.season)}</div>
        </div>
        <div id="${containerId}-canvas" class="v81-chart" style="height:320px;"></div>
      </div>`;
    const canvas = document.getElementById(containerId + '-canvas');
    if (typeof echarts === 'undefined' || !canvas) return;
    const inst = initChart(canvas);
    track(containerId, inst);
    const zones = latest.zones;
    const cats = zones.map(z => ZONE_CN[z.zone] || esc(z.zone));
    const fg = zones.map(z => z.fg_pct == null ? null : Math.round(Number(z.fg_pct) * 1000) / 10);
    const fga = zones.map(z => z.fga_rate == null ? null : Math.round(Number(z.fga_rate) * 1000) / 10);
    inst.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: ['命中率%', '出手占比%'], textStyle: { color: TH.textDim } },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: cats, axisLabel: { color: TH.textDim, fontSize: 11 }, axisLine: { lineStyle: { color: TH.border } } },
      yAxis: { type: 'value', max: 100, axisLabel: { color: TH.textDim, formatter: '{value}%' }, splitLine: { lineStyle: { color: TH.border } } },
      series: [
        { name: '命中率%', type: 'bar', data: fg, itemStyle: { color: TH.accent, borderRadius: [4, 4, 0, 0] }, barWidth: '32%' },
        { name: '出手占比%', type: 'bar', data: fga, itemStyle: { color: TH.purple, borderRadius: [4, 4, 0, 0] }, barWidth: '32%' },
      ],
    });
  };
})();
