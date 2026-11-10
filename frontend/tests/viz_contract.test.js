'use strict';
// 前端静态契约测试：不依赖 DOM、不依赖任何 npm 包，仅从磁盘读文件做断言。
// 运行：node --test frontend/tests/viz_contract.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 以测试文件自身位置推导仓库根，避免硬编码机器绝对路径
const FRONTEND = path.resolve(__dirname, '..');
const REPO = path.resolve(FRONTEND, '..');
const INDEX_HTML = path.join(FRONTEND, 'index.html');
const STYLE_CSS = path.join(FRONTEND, 'css', 'style.css');
const APP_JS = path.join(FRONTEND, 'js', 'app.js');
const ECHARTS_VENDOR = path.join(FRONTEND, 'vendor', 'echarts.min.js');
const SIZE_CHECKER = path.join(REPO, 'tools', 'check_report_size.py');
const VIZ_THEME = path.join(REPO, 'viz', 'theme.py');
const THEME_TOKENS = path.join(REPO, 'viz', 'theme_tokens.json');

function read(p) {
  return fs.readFileSync(p, 'utf8');
}
function exists(p) {
  return fs.existsSync(p);
}
function size(p) {
  return fs.statSync(p).size;
}

// 以 index.html 是否已引用本地 vendor 判定「去 CDN 改造」是否完成。
// 不用「vendor 文件是否落地」作判据：两者存在合法的并行中间态
// （vendor 已放置、但 index.html 尚未改），用 vendor 判据会造成假失败。
const indexHtml = exists(INDEX_HTML) ? read(INDEX_HTML) : '';
const usesVendor = /vendor\/echarts\.min\.js/.test(indexHtml);

test(
  usesVendor
    ? 'index.html 不含 https://cdn. 且引用 vendor/echarts.min.js'
    : 'index.html CDN 引用数 <=1 [TODO: 去 CDN 完成后收紧为「零 CDN + 本地 vendor」]',
  () => {
    const cdnCount = (indexHtml.match(/https:\/\/cdn\./g) || []).length;
    if (usesVendor) {
      assert.equal(cdnCount, 0, 'index.html 仍存在 CDN 引用');
      assert.match(indexHtml, /vendor\/echarts\.min\.js/, 'index.html 未引用本地 vendor/echarts.min.js');
    } else {
      assert.ok(
        cdnCount <= 1,
        `index.html 存在 ${cdnCount} 个 CDN 引用（去 CDN 未完成时允许 <=1）`
      );
    }
  }
);

test('css/style.css 含 :root 与至少一个 @media', () => {
  const css = read(STYLE_CSS);
  assert.match(css, /:root\s*\{/, '缺少 :root 变量定义');
  assert.match(css, /@media\b/, '缺少 @media 响应式规则');
});

test('js/app.js 含 echarts.init 且含 fetch(', () => {
  const js = read(APP_JS);
  assert.match(js, /echarts\.init\s*\(/, '缺少 echarts.init 调用');
  assert.match(js, /fetch\s*\(/, '缺少 fetch( 调用');
});

test('frontend/vendor/echarts.min.js 存在且 >100KB', (t) => {
  if (!exists(ECHARTS_VENDOR)) {
    t.skip('frontend/vendor/echarts.min.js 尚未落地（由 vendor 放置任务处理），跳过体积断言');
    return;
  }
  assert.ok(
    size(ECHARTS_VENDOR) > 100 * 1024,
    `echarts.min.js 体积 ${size(ECHARTS_VENDOR)} 字节，未达 100KB`
  );
});

test('tools/check_report_size.py 存在且可执行', () => {
  assert.ok(exists(SIZE_CHECKER), 'tools/check_report_size.py 不存在');
  let hasX = false;
  try {
    fs.accessSync(SIZE_CHECKER, fs.constants.X_OK);
    hasX = true;
  } catch {
    hasX = false;
  }
  const hasShebang = read(SIZE_CHECKER).startsWith('#!');
  assert.ok(hasX || hasShebang, 'check_report_size.py 既无可执行权限也无 shebang');
});

test('viz/theme.py 定义 CSS_VARS_DARK 与 FINANCE', (t) => {
  if (!exists(VIZ_THEME)) {
    t.skip('viz/theme.py 尚未创建（由其它 worker 负责），跳过');
    return;
  }
  const src = read(VIZ_THEME);
  assert.match(src, /CSS_VARS_DARK\s*=/, '缺少 CSS_VARS_DARK 定义');
  assert.match(src, /FINANCE\s*=/, '缺少 FINANCE 定义');
});

// theme_tokens.json 由 viz 内核生成，读 JSON 比解析 theme.py 源码更稳定；
// 作为生成物 CI 里可能未提交，缺失时跳过，不硬失败。
test('viz/theme_tokens.json 主题令牌契约（暗色变量 / 涨红跌绿 / 30 队配色）', (t) => {
  if (!exists(THEME_TOKENS)) {
    t.skip('viz/theme_tokens.json 尚未生成（生成物，CI 可缺失），跳过');
    return;
  }
  const tokens = JSON.parse(read(THEME_TOKENS));
  assert.ok(Array.isArray(tokens.css_vars_dark_keys), 'css_vars_dark_keys 应为数组');
  assert.ok(tokens.css_vars_dark_keys.includes('--bg'), '暗色主题缺少 --bg');
  assert.equal(tokens.css_vars_dark['--bg'], '#0b1220', '暗色 --bg 值变更');
  assert.equal(tokens.finance.up, '#dc2626', '涨应为红');
  assert.equal(tokens.finance.down, '#16a34a', '跌应为绿');
  assert.equal(tokens.team_colors_count, 30, '球队配色数量应为 30');
  assert.equal(Object.keys(tokens.team_colors).length, 30, 'team_colors 条目数应为 30');
});
