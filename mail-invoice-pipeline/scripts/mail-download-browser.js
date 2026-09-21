// 浏览器阶段：处理 SPA 平台（诺诺/百望等）的 MANUAL 发票链接
// 前置：先启动专用 Chrome（独立 profile，不碰主 Chrome）：
//   Windows: powershell -ExecutionPolicy Bypass -File chrome-auto-start.ps1
//   其他:    bash chrome-auto-start.sh
// 用法:
//   node mail-download-browser.js            处理 <数据目录>/manual_links.json 中 SPA 平台链接
//   node mail-download-browser.js <url>...   直接处理指定链接
// 原理: 打开 SPA 页 → 钩住 window.open → 点击「下载PDF文件」→ 捕获带签名的下载 URL
//       → 普通 HTTP GET 取回 PDF（已验证无需 cookie）→ 存 invoices/（哈希去重）
// 环境变量:
//   INVOICE_WORKDIR  数据目录（invoices/ 与 manual_links.json 所在处），缺省 = 当前目录
//   INVOICE_CDP_URL  专用 Chrome 的 CDP 地址，缺省 http://127.0.0.1:9222
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');
const { DATA_DIR } = require('./mail-util');

const OUT_DIR = path.join(DATA_DIR, 'invoices');
const ML = path.join(DATA_DIR, 'manual_links.json');
const CDP = process.env.INVOICE_CDP_URL || 'http://127.0.0.1:9222';
const SPA_HOSTS = /(nnfp|fp)\.jss\.com\.cn|(bwfp|u|pis|web)\.baiwang\.com|yun\.ekaikai\.cn/i;

const args = process.argv.slice(2);
let entries;
if (args.length) {
  entries = args.map((u, i) => ({ uid: `arg${i}`, subject: '', url: u }));
} else {
  try { entries = JSON.parse(fs.readFileSync(ML, 'utf8')); }
  catch (e) { console.log('manual_links.json 不存在或为空；先跑 mail-download-links.js'); process.exit(0); }
}
const targets = entries.filter(e => SPA_HOSTS.test(e.url));
if (!targets.length) { console.log('manual_links.json 中没有 SPA 平台链接，无需浏览器阶段'); process.exit(0); }

function deriveName(subject, uid) {
  const m = /发票号码[:：]?\s*([0-9]{6,25})/.exec(subject || '');
  if (m) return `发票_${m[1]}.pdf`;
  return `uid${uid}_browser.pdf`;
}
function uniquePath(dir, name) {
  let p = path.join(dir, name), i = 1;
  const ext = path.extname(name), stem = name.slice(0, name.length - ext.length);
  while (fs.existsSync(p)) { p = path.join(dir, `${stem}(${i++})${ext}`); }
  return p;
}

async function captureDownloadUrl(browser, url) {
  const page = await browser.newPage();
  try {
    await page.evaluateOnNewDocument(() => {
      window.__opens = [];
      window.open = (u) => { window.__opens.push(String(u)); return { closed: false, close() {}, focus() {} }; };
    });
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 3000));
    // 依次尝试：精确"下载PDF文件" → 含"下载PDF" → 含 PDF 的短文本按钮
    for (const pick of [
      () => { const el = [...document.querySelectorAll('a,button,div,span')].find(x => (x.innerText || '').trim() === '下载PDF文件'); if (el) { el.click(); return (el.innerText || '').trim(); } return null; },
      () => { const el = [...document.querySelectorAll('a,button,div,span')].find(x => /下载PDF/.test(x.innerText || '') && (x.innerText || '').length < 12); if (el) { el.click(); return (el.innerText || '').trim(); } return null; },
      () => { const el = [...document.querySelectorAll('a,button')].find(x => /PDF/.test(x.innerText || '') && /下载|download/i.test(x.innerText || '')); if (el) { el.click(); return (el.innerText || '').trim(); } return null; },
    ]) {
      const clickedTxt = await page.evaluate(pick);
      if (clickedTxt) {
        await new Promise(r => setTimeout(r, 2500));
        const opens = await page.evaluate(() => window.__opens || []);
        if (opens.length) return { url: opens[0], clicked: clickedTxt };
      }
    }
    return { url: null };
  } finally {
    await page.close().catch(() => {});
  }
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  let browser;
  try {
    browser = await puppeteer.connect({ browserURL: CDP });
  } catch (e) {
    console.log(`连不上 CDP（${CDP}）：先运行 chrome-auto-start.ps1 / chrome-auto-start.sh 启动专用 Chrome`);
    process.exit(1);
  }

  const done = [], remain = [];
  for (const e of targets) {
    console.log(`\nUID ${e.uid} | ${e.subject || ''}\n    page: ${e.url}`);
    let cap;
    try { cap = await captureDownloadUrl(browser, e.url); }
    catch (err) { console.log(`    ERR open: ${err.message}`); remain.push(e); continue; }
    if (!cap.url) { console.log('    STILL-MANUAL: 页面上没点到下载按钮'); remain.push(e); continue; }
    console.log(`    clicked「${cap.clicked}」-> ${cap.url.slice(0, 120)}`);
    const resp = await fetch(cap.url, { redirect: 'follow', headers: { 'User-Agent': 'Mozilla/5.0' } });
    const buf = Buffer.from(await resp.arrayBuffer());
    if (resp.status !== 200 || buf.slice(0, 5).toString('latin1') !== '%PDF-') {
      console.log(`    STILL-MANUAL: 捕获URL未返回PDF (HTTP ${resp.status}, head=${buf.slice(0, 8).toString('latin1')})`);
      remain.push(e);
      continue;
    }
    // 哈希去重
    const hash = crypto.createHash('sha1').update(buf).digest('hex');
    let dup = null;
    for (const f of fs.readdirSync(OUT_DIR)) {
      const fp = path.join(OUT_DIR, f);
      const st = fs.statSync(fp);
      if (!st.isFile() || st.size === 0) continue;
      if (crypto.createHash('sha1').update(fs.readFileSync(fp)).digest('hex') === hash) { dup = f; break; }
    }
    if (dup) { console.log(`    DUP  与已有文件相同: ${dup}`); done.push(e); continue; }
    const dest = uniquePath(OUT_DIR, deriveName(e.subject, e.uid));
    fs.writeFileSync(dest, buf);
    console.log(`    SAVED ${path.basename(dest)} (${buf.length} bytes)`);
    done.push(e);
  }
  browser.disconnect();

  // 成功的从 manual_links.json 移除，失败的保留
  if (!args.length) {
    const doneKeys = new Set(done.map(e => `${e.uid}|${e.url}`));
    const all = JSON.parse(fs.readFileSync(ML, 'utf8'));
    fs.writeFileSync(ML, JSON.stringify(all.filter(x => !doneKeys.has(`${x.uid}|${x.url}`)), null, 2));
  }
  console.log(`\n===== BROWSER STAGE =====  SAVED/DUP: ${done.length}  STILL-MANUAL: ${remain.length}`);
  remain.forEach(r => console.log(`  UID ${r.uid} | ${r.url}`));
})().catch(e => { console.error('ERR:', e.message || e); process.exit(1); });
