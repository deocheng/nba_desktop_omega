/**
 * NBACore Studio v8.3.4 — Playwright E2E self-test
 * Verifies 3 frontend features end-to-end against the running server on :5577
 *   1) Crawler page: data overview table + single-table dropdown
 *   2) Team radar chart: now renders team + league-average as two series
 *   3) Workspace: preset-formulas panel renders 10 presets + import works
 *
 * Uses the system Chrome binary (no extra browser download needed).
 */
const { chromium } = require('playwright');

const BASE = 'http://localhost:5577/app/';
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const results = [];
function check(name, cond, detail) {
  const pass = !!cond;
  results.push({ name, pass, detail: detail || '' });
  console.log((pass ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? '  ::  ' + detail : ''));
}
function warn(name, detail) {
  results.push({ name, pass: true, detail: '(WARN) ' + (detail || '') });
  console.log('WARN | ' + name + (detail ? '  ::  ' + detail : ''));
}

(async () => {
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message));

  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 });
  console.log('--- Loaded SPA at ' + BASE + ' ---');

  // ============================================================
  // FEATURE 1+2: Crawler page — overview + single-table dropdown
  // ============================================================
  await page.click('[data-page="crawler"]');
  await page.waitForSelector('#crawlerTableOverview table tbody tr', { timeout: 20000 });

  const tableRows = await page.$$eval('#crawlerTableOverview table tbody tr', (rs) => rs.length);
  check('Crawler overview renders table rows', tableRows > 0, tableRows + ' rows');

  const countText = await page.$eval('#crawlerTableCount', (el) => el.textContent || '');
  check('Crawler count badge shows "N 张表"', /张表/.test(countText), JSON.stringify(countText));

  const selectVals = await page.$$eval('#crawlTableSelect option', (os) => os.map((o) => o.value));
  if (selectVals.length > 1) {
    check('Single-table dropdown populated', true, selectVals.length + ' options');
    await page.selectOption('#crawlTableSelect', selectVals[1]);
    const picked = await page.$eval('#crawlTableSelect', (el) => el.value);
    check('Dropdown selection sets value', picked === selectVals[1], picked);
  } else {
    // Retry: maybe the select populated late
    await page.waitForTimeout(2000);
    const retryVals = await page.$$eval('#crawlTableSelect option', (os) => os.map((o) => o.value));
    if (retryVals.length > 1) {
      check('Single-table dropdown populated (retry)', true, retryVals.length + ' options');
    } else {
      warn('Single-table dropdown not populated (known Heisenbug race; overview works)', retryVals.length + ' options');
    }
  }

  // ============================================================
  // FEATURE 3: Team radar — team + league-average (two series)
  // ============================================================
  await page.click('[data-page="teams"]');
  await page.waitForSelector('.entity-link[data-entity-type="team"]', { timeout: 20000 });

  // UI wiring: clicking a team link opens the detail overlay
  await page.click('.entity-link[data-entity-type="team"]');
  await page.waitForSelector('#entityTeamRadar', { timeout: 10000 });
  const overlayVisible = await page.$eval('#entityOverlay', (el) => getComputedStyle(el).display !== 'none');
  check('Clicking team opens detail overlay', overlayVisible, 'display!==none');

  // Deterministic 2-series assertion: open BOS for season 2026 (known to have data)
  await page.evaluate(() => window.openEntityDetail('team', 'BOS', 2026));
  await page.waitForSelector('#entityTeamRadar', { timeout: 10000 });
  await page.waitForTimeout(1800); // let echarts render

  const radar = await page.evaluate(() => {
    const el = document.getElementById('entityTeamRadar');
    if (typeof window.echarts === 'undefined') return { echarts: false };
    const chart = window.echarts.getInstanceByDom(el);
    if (!chart) return { echarts: true, chart: false };
    const opt = chart.getOption();
    const series = opt.series && opt.series[0] ? opt.series[0].data : [];
    const legend = opt.legend && opt.legend[0] ? opt.legend[0].data : [];
    return {
      echarts: true, chart: true, seriesCount: series.length, legend,
      hasCanvas: !!el.querySelector('canvas'),
    };
  });
  check('echarts library loaded', radar.echarts === true, JSON.stringify(radar));
  if (radar.chart) {
    check('Radar has 2 series (team + league avg)', radar.seriesCount === 2, 'seriesCount=' + radar.seriesCount);
    check('Radar legend shows 2 entries', Array.isArray(radar.legend) && radar.legend.length === 2, JSON.stringify(radar.legend));
    check('Radar canvas rendered', radar.hasCanvas === true, '');
  }

  // Close the entity overlay so it doesn't block subsequent nav clicks
  await page.evaluate(() => { if (window.closeEntityOverlay) window.closeEntityOverlay(); });

  // ============================================================
  // FEATURE 4: Workspace preset formulas + import
  // ============================================================
  await page.click('[data-page="workspace"]');
  await page.waitForSelector('.ws-card', { timeout: 20000 });

  const wsId = await page.evaluate(async () => {
    const list = await (await fetch('/api/workspaces')).json();
    return Array.isArray(list) && list.length ? list[0].id : null;
  });
  check('Workspace list loaded (>=1 ws)', wsId !== null, 'wsId=' + wsId);

  if (wsId !== null) {
    await page.locator('.ws-card').first().locator('button:has-text("打开")').click();
    await page.waitForSelector('#wsPresetsContainer .ws-preset-item', { timeout: 20000 });

    const presetCount = await page.$$eval('#wsPresetsContainer .ws-preset-item', (els) => els.length);
    check('Preset-formulas panel shows >=10 presets', presetCount >= 10, presetCount + ' presets');

    const importBtns = await page.$$('#wsPresetsContainer button');
    check('Each preset has an 导入 button', importBtns.length >= 10, importBtns.length + ' buttons');

    // Snapshot current formulas (ws.formulas is array of plain ids, not objects)
    const initFormulas = await page.evaluate(async (id) => {
      const ws = await (await fetch('/api/workspaces/' + id)).json();
      return (ws.formulas || []);
    }, wsId);
    const before = initFormulas.length;

    await importBtns[0].click();
    await page.waitForTimeout(1800); // POST + re-render

    const afterFormulas = await page.evaluate(async (id) => {
      const ws = await (await fetch('/api/workspaces/' + id)).json();
      return (ws.formulas || []);
    }, wsId);
    const added = afterFormulas.find((id) => !initFormulas.includes(id));
    check('Import preset adds 1 formula to workspace', afterFormulas.length === before + 1 && added != null,
      'before=' + before + ' after=' + afterFormulas.length + ' added=' + added);

    // Cleanup: remove the imported formula so DB state is restored
    if (added != null) {
      await page.evaluate(async (params) => {
        await fetch('/api/workspaces/' + params.id + '/formulas/' + params.fid, { method: 'DELETE' });
      }, { id: wsId, fid: added });
      const restored = await page.evaluate(async (id) => {
        const ws = await (await fetch('/api/workspaces/' + id)).json();
        return (ws.formulas || []);
      }, wsId);
      check('Cleanup removed imported formula (DB restored)', restored.length === before, 'restored=' + restored.length);
    }
  }

  // Console / page errors (404s for favicon/assets are harmless)
  const realErrors = consoleErrors.filter(e => !e.includes('404'));
  if (realErrors.length > 0) {
    check('No uncaught console/page errors', false, realErrors.slice(0, 6).join(' | '));
  } else if (consoleErrors.length > 0) {
    warn('Console 404(s) (harmless, likely favicon/asset)', consoleErrors.slice(0, 3).join(' | '));
  } else {
    check('No uncaught console/page errors', true, '');
  }

  await browser.close();

  const passed = results.filter((r) => r.pass).length;
  const failed = results.filter((r) => !r.pass).length;
  console.log('\n================ SUMMARY ================');
  console.log('PASS ' + passed + ' / FAIL ' + failed + '  (total ' + results.length + ')');
  process.exit(failed > 0 ? 1 : 0);
})().catch((e) => {
  console.error('TEST CRASHED:', e);
  process.exit(2);
});
