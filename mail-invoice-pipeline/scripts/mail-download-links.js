// 从"无附件、正文带下载链接"的发票邮件中提取链接并自动下载发票文件到 <数据目录>/invoices/
// 用法:
//   node mail-download-links.js <UID> [文件夹]     下载指定邮件的链接
//   node mail-download-links.js --all [文件夹]     批量处理文件夹内所有无附件邮件
//   node mail-download-links.js --dry ...          只探测不写文件
//   文件夹缺省 = config.yaml 的 invoiceFolder（打不开则自动发现/INBOX）
// 行为: 跟随重定向；最终响应是 PDF/OFD/XML 或 Content-Disposition: attachment 才保存；
//       返回 HTML 页面（SPA/需登录）的链接累积到 <数据目录>/manual_links.json，交由 mail-download-browser.js 处理。
// 环境变量:
//   INVOICE_WORKDIR  数据目录（invoices/ 与 manual_links.json 所在处），缺省 = 当前目录
//   MAIL_ACCOUNT     指定 config.yaml 中的账户 id
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { ImapFlow } = require('imapflow');
const { DATA_DIR, loadAccount, resolveInvoiceFolder } = require('./mail-util');

const args = process.argv.slice(2);
const dry = args.includes('--dry');
const all = args.includes('--all');
const positional = args.filter(a => !a.startsWith('--'));
const { acc, config } = loadAccount();
const folder = positional.find(a => !/^\d+$/.test(a)) || config.invoiceFolder || '';
const uids = positional.filter(a => /^\d+$/.test(a)).map(Number);
if (!all && !uids.length) {
  console.log('用法: node mail-download-links.js <UID> [文件夹] | --all [文件夹] | 可加 --dry');
  process.exit(1);
}

const OUT_DIR = path.join(DATA_DIR, 'invoices');
const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36', 'Accept': '*/*' };

// ---------- MIME 工具（与 mail-scan-links.js 一致） ----------
function normDisp(node) {
  const d = node.disposition;
  return typeof d === 'string' ? d.toLowerCase() : String((d && d.type) || '').toLowerCase();
}
function typeOf(node) {
  const t = String(node.type || '').toLowerCase();
  return t.includes('/') ? t.split('/')[0] : t;
}
function subtypeOf(node) {
  const t = String(node.type || '').toLowerCase();
  if (t.includes('/')) return t.split('/')[1];
  return String(node.subtype || '').toLowerCase();
}
function normName(node) {
  return (node.dispositionParameters && node.dispositionParameters.filename) || (node.parameters && node.parameters.name) || '';
}
function walk(node, prefix, leaves) {
  if (node.childNodes && node.childNodes.length) {
    node.childNodes.forEach((c, i) => walk(c, prefix ? `${prefix}.${i + 1}` : String(i + 1), leaves));
  } else {
    node._part = node.part || prefix || '1';
    leaves.push(node);
  }
}
function decodePart(buf, encoding) {
  const enc = String(encoding || '').toLowerCase();
  if (enc === 'base64') {
    const s = buf.toString('ascii');
    if (/^[A-Za-z0-9+/\r\n\s]+=*\s*$/.test(s) && s.replace(/\s/g, '').length > 0) {
      return Buffer.from(s.replace(/\s/g, ''), 'base64');
    }
  }
  if (enc === 'quoted-printable') {
    const s = buf.toString('binary');
    if (/=\r?\n/.test(s) || /=[0-9A-Fa-f]{2}/.test(s)) {
      const joined = s.replace(/=\r?\n/g, '');
      const bytes = [];
      for (let i = 0; i < joined.length; i++) {
        if (joined[i] === '=' && /[0-9A-Fa-f]{2}/.test(joined.substr(i + 1, 2))) {
          bytes.push(parseInt(joined.substr(i + 1, 2), 16));
          i += 2;
        } else {
          bytes.push(joined.charCodeAt(i) & 0xff);
        }
      }
      return Buffer.from(bytes);
    }
  }
  return buf;
}
function decodeSmart(buf) {
  let s = new TextDecoder('utf-8').decode(buf);
  if (s.includes('\uFFFD')) {
    try { s = new TextDecoder('gb18030').decode(buf); } catch (e) { /* keep utf8 */ }
  }
  return s;
}

// ---------- 链接提取与筛选 ----------
const TRACKING = /(linktrace|sendcloud|opens|click\.|\/open\.do|getEwmImg|\.png|\.jpe?g|\.gif|\.ico|\.svg|weixin\.qq\.com\/cgi-bin|mail\.qq\.com)/i;
// 首页/页脚导航/登录墙类链接：不可能直接给出发票文件
const HOMEJUNK = /^(https?:\/\/)?((www|web|fp|pay|ntf|bmjc|baoxiao|nst)\.(nuonuo|baiwang|51fapiao)\.com|www\.nuonuo\.com|[^/]+\.nuonuo\.com)\/?([#?]|$)|\.nuonuo\.com\/|nuonuo\.com\/nuonuo\/web\/about|tydl-login|ebill\.spdbccc\.com\.cn|aboutone\/index/i;
function extractUrls(text) {
  const urls = new Set();
  let m;
  const reHref = /href\s*=\s*["']([^"']+)["']/gi;
  while ((m = reHref.exec(text))) urls.add(m[1]);
  const reBare = /https?:\/\/[^\s"'<>()\u4e00-\u9fff]+/gi;
  while ((m = reBare.exec(text))) urls.add(m[0].replace(/[.,;]+$/, ''));
  return [...urls].filter(u => /^https?:\/\//i.test(u) && !TRACKING.test(u) && !HOMEJUNK.test(u));
}
function scoreUrl(u) {
  let s = 0;
  if (/\.pdf(\?|$)/i.test(u)) s += 10;
  if (/\/(dlj|download|DownLoad|dzfp|fp)\/?/i.test(u)) s += 4;
  if (/(fapiao|invoice|nnfp|baiwang|wosaimg|chinatax|jcsk100|ekaikai|51fapiao)/i.test(u)) s += 3;
  if (/^https:\/\/(u|s)\.[a-z0-9]+\.[a-z]+\//i.test(u)) s += 1; // 短链兜底
  return s;
}
function pickCandidates(urls) {
  return urls.map(u => ({ u, s: scoreUrl(u) }))
    .sort((a, b) => b.s - a.s)
    .map(x => x.u)
    .slice(0, 3);
}

// ---------- HTTP 探测 + 下载 ----------
function fixMojibake(f) {
  // 部分平台把 UTF-8 原始字节直接塞进 Content-Disposition（无 RFC5987 编码），
  // fetch 按 latin1 暴露 header 值，需转回字节再按 UTF-8 解码
  if (/[\u0080-\u00ff]/.test(f)) {
    try {
      const fixed = Buffer.from(f, 'latin1').toString('utf8');
      if (!fixed.includes('\uFFFD')) return fixed;
    } catch (e) { /* keep original */ }
  }
  return f;
}
function dispositionFilename(cd) {
  if (!cd) return null;
  let m = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(cd);
  if (m) { try { return fixMojibake(decodeURIComponent(m[1].trim())); } catch (e) { /* fall */ } }
  m = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
  if (m) {
    let f = fixMojibake(m[1].trim());
    // RFC2047 或裸 URL 编码
    try { if (/%[0-9A-Fa-f]{2}/.test(f)) f = fixMojibake(decodeURIComponent(f)); } catch (e) { /* keep */ }
    return f;
  }
  return null;
}
function safeName(name) {
  return path.basename(String(name)).replace(/[\\/:*?"<>|]/g, '_').slice(0, 120);
}
function uniquePath(dir, name) {
  let p = path.join(dir, name), i = 1;
  const ext = path.extname(name), stem = name.slice(0, name.length - ext.length);
  while (fs.existsSync(p)) { p = path.join(dir, `${stem}(${i++})${ext}`); }
  return p;
}
function deriveName(subject, ext) {
  const m = /\u53d1\u7968\u53f7\u7801[:：]?\s*([0-9]{6,25})/.exec(subject || ''); // 发票号码
  if (m) return `\u53d1\u7968_${m[1]}${ext}`; // 发票_<号码>
  return null;
}

// ---------- 中间页（HTML 下载跳转页）解析 ----------
// 51fapiao 等平台的分享页本身是 HTML，真实 PDF 靠页面内隐藏字段签名后二次请求拿到
function resolveInterstitial(html, pageUrl) {
  // 模式1: 51发票 dlj 分享页  hidden: id="dlj" / id="rkfs" / id="signatureString"
  if (/\/dlj\/v\d+\//.test(pageUrl)) {
    const sig = (html.match(/id="signatureString"\s+value="([^"]+)"/i) || [])[1];
    const dlj = (html.match(/id="dlj"\s+value="([^"]+)"/i) || [])[1];
    if (sig && dlj) {
      const base = new URL(pageUrl).origin;
      return `${base}/dlj/v7/downloadFile/${dlj}?signatureString=${encodeURIComponent(sig)}`;
    }
  }
  // 模式2: meta refresh
  const mr = /<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]+url=([^"'>\s]+)/i.exec(html);
  if (mr) {
    try { return new URL(mr[1], pageUrl).href; } catch (e) { /* fallthrough */ }
  }
  return null;
}

async function probeAndDownload(url, uid, subject, outDir, depth) {
  depth = depth || 0;
  if (depth > 3) return { url, verdict: 'MANUAL', reason: '中间页跳转层数过深' };
  let cur = url, hops = 0, resp = null, insecureNote = '';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    while (true) {
      try {
        resp = await fetch(cur, { redirect: 'manual', headers: UA, signal: controller.signal });
      } catch (e) {
        if (/certificate|ssl|tls/i.test(String(e.message)) && process.env.NODE_TLS_REJECT_UNAUTHORIZED !== '0') {
          // 个别税务/开票平台证书链不规范：仅对该请求降级重试验证
          insecureNote = ' [TLS verify disabled for this host]';
          process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
          continue;
        }
        throw e;
      }
      const loc = resp.headers.get('location');
      if ([301, 302, 303, 307, 308].includes(resp.status) && loc && hops < 8) {
        const next = new URL(loc, cur).href;
        try { await resp.body.cancel(); } catch (e) { /* noop */ }
        cur = next; hops++; resp = null;
        continue;
      }
      break;
    }
  } finally { clearTimeout(timer); }

  const status = resp.status;
  const ct = String(resp.headers.get('content-type') || '');
  const cd = String(resp.headers.get('content-disposition') || '');
  let kind = null, ext = null;
  const fname = dispositionFilename(cd);
  if (/application\/pdf/i.test(ct) || /\.pdf$/i.test(cur) || (fname && /\.pdf$/i.test(fname))) { kind = 'pdf'; ext = '.pdf'; }
  else if (/application\/ofd/i.test(ct) || /\.ofd$/i.test(cur) || (fname && /\.ofd$/i.test(fname))) { kind = 'ofd'; ext = '.ofd'; }
  else if (/(application|text)\/xml/i.test(ct) || /\.xml$/i.test(cur) || (fname && /\.xml$/i.test(fname))) { kind = 'xml'; ext = '.xml'; }
  else if (/application\/(zip|x-zip-compressed)/i.test(ct) || (fname && /\.zip$/i.test(fname))) { kind = 'zip'; ext = '.zip'; }
  else if (/text\/html/i.test(ct)) { kind = 'html'; }

  const result = { url, finalUrl: cur, status, contentType: ct, kind, filename: null, saved: null, note: insecureNote };

  if (kind === 'html') {
    const html = (await resp.text()).slice(0, 512 * 1024);
    const next = resolveInterstitial(html, cur);
    try { await resp.body.cancel(); } catch (e) { /* noop */ }
    if (next) {
      const r2 = await probeAndDownload(next, uid, subject, outDir, depth + 1);
      r2.url = url; // 保留原始邮件链接作为溯源
      return r2;
    }
    result.verdict = 'MANUAL';
    result.reason = '返回 HTML 页面（SPA/需登录/需点击下载按钮）';
    return result;
  }
  if (!kind) {
    try { await resp.body.cancel(); } catch (e) { /* noop */ }
    if (/^image\//i.test(ct)) {
      result.verdict = 'FAIL';
      result.reason = `重定向到图片（失效链接/广告）`;
      return result;
    }
    result.verdict = 'MANUAL';
    result.reason = `未知类型 ${ct || '(无 Content-Type)'}`;
    return result;
  }
  if (status !== 200) {
    try { await resp.body.cancel(); } catch (e) { /* noop */ }
    result.verdict = 'FAIL';
    result.reason = `HTTP ${status}`;
    return result;
  }
  let name = fname ? safeName(fname) : null;
  if (!name) name = deriveName(subject, ext) || `uid${uid}_link${ext}`;
  if (!path.extname(name)) name += ext;
  if (dry) {
    try { await resp.body.cancel(); } catch (e) { /* noop */ }
    result.verdict = 'DRY-OK';
    result.filename = name;
    return result;
  }
  const dest = uniquePath(outDir, name);
  const buf = Buffer.from(await resp.arrayBuffer());
  // 内容哈希去重：同一张发票被重复下载时只保留第一份，避免汇总表重复计数
  const hash = crypto.createHash('sha1').update(buf).digest('hex');
  for (const f of fs.readdirSync(outDir)) {
    const fp = path.join(outDir, f);
    const st = fs.statSync(fp);
    if (!st.isFile() || st.size === 0) continue;
    const h = crypto.createHash('sha1').update(fs.readFileSync(fp)).digest('hex');
    if (h === hash) {
      result.verdict = 'DUP';
      result.reason = `与已有文件相同: ${f}`;
      result.filename = f;
      return result;
    }
  }
  fs.writeFileSync(dest, buf);
  result.verdict = 'SAVED';
  result.filename = path.basename(dest);
  result.saved = dest;
  result.size = fs.statSync(dest).size;
  return result;
}

// ---------- 邮件遍历 ----------
async function collectBody(client, uid) {
  const m = await client.fetchOne(uid, { envelope: true, bodyStructure: true }, { uid: true });
  if (!m || !m.bodyStructure) return null;
  const leaves = [];
  walk(m.bodyStructure, '', leaves);
  const atts = leaves.filter(l => normDisp(l) === 'attachment' || /\.(pdf|ofd|xml)$/i.test(normName(l)));
  const subject = (m.envelope && m.envelope.subject) || '';
  const date = m.envelope && m.envelope.date ? m.envelope.date.toISOString().slice(0, 10) : '';
  if (atts.length) return { hasAtt: true, subject, date };
  const textParts = leaves.filter(l => typeOf(l) === 'text' && ['html', 'plain'].includes(subtypeOf(l)));
  let body = '';
  for (const tp of textParts) {
    try {
      const dl = await client.download(uid, tp._part, { uid: true });
      const chunks = [];
      for await (const c of dl.content) chunks.push(c);
      const s = decodeSmart(Buffer.concat(chunks));
      if (s.length > body.length) body = s;
    } catch (e) { /* part failed */ }
  }
  return { hasAtt: false, subject, date, body };
}

(async () => {
  if (!dry) fs.mkdirSync(OUT_DIR, { recursive: true });
  const client = new ImapFlow({
    host: acc.imap.host, port: acc.imap.port, secure: acc.imap.useTLS,
    auth: { user: acc.auth.username, pass: acc.auth.password },
    logger: false,
  });
  await client.connect();
  let box, resolvedFolder;
  ({ box, folder: resolvedFolder } = await resolveInvoiceFolder(client, folder || undefined));
  console.log(`[FOLDER] using: ${resolvedFolder}`);

  let targets = uids;
  if (all) {
    targets = [];
    const allUids = await client.search({ all: true });
    for (const uid of allUids) {
      try {
        const info = await collectBody(client, uid);
        if (info && !info.hasAtt && info.body && extractUrls(info.body).length) targets.push(uid);
      } catch (e) { /* skip */ }
    }
    console.log(`[SCAN] ${resolvedFolder}: ${box.exists} messages, ${targets.length} attachment-less emails with links`);
  }

  const summary = { saved: [], manual: [], failed: [] };
  for (const uid of targets) {
    const info = await collectBody(client, uid);
    if (!info) { console.log(`UID ${uid}: SKIP (no bodyStructure)`); continue; }
    if (info.hasAtt) { console.log(`UID ${uid}: SKIP (已有附件，用 mail-download-att.js)`); continue; }
    const urls = extractUrls(info.body || '');
    const cands = pickCandidates(urls);
    console.log(`\nUID ${uid} | ${info.date} | ${info.subject}`);
    if (!cands.length) { console.log('    无可用下载链接'); summary.manual.push({ uid, subject: info.subject, reason: 'no-link' }); continue; }
    let done = false;
    for (const u of cands) {
      let r;
      try { r = await probeAndDownload(u, uid, info.subject, OUT_DIR); }
      catch (e) { console.log(`    ERR  ${u} -> ${e.message}`); summary.failed.push({ uid, url: u, reason: e.message }); continue; }
      if (r.verdict === 'SAVED' || r.verdict === 'DRY-OK') {
        console.log(`    ${r.verdict} ${r.filename} (${r.size || '?'} bytes) <- ${r.finalUrl}${r.note}`);
        summary.saved.push({ uid, file: r.filename });
        done = true;
        break; // 一封邮件通常一张发票，首个成功即止
      }
      if (r.verdict === 'DUP') {
        console.log(`    DUP  ${r.reason}`);
        summary.saved.push({ uid, file: r.filename, dup: true });
        done = true;
        break;
      }
      if (r.verdict === 'MANUAL') {
        console.log(`    MANUAL ${r.finalUrl} (${r.reason})`);
        if (!done) summary.manual.push({ uid, subject: info.subject, url: r.finalUrl, reason: r.reason });
      } else {
        console.log(`    FAIL ${r.finalUrl} (${r.reason})`);
        summary.failed.push({ uid, url: r.finalUrl, reason: r.reason });
      }
    }
    if (dry) break; // --dry 只演示第一封的探测过程
  }

  await client.logout();

  // MANUAL 链接落盘，供浏览器阶段 mail-download-browser.js 消费
  const ML = path.join(DATA_DIR, 'manual_links.json');
  let prev = [];
  try { prev = JSON.parse(fs.readFileSync(ML, 'utf8')); } catch (e) { /* fresh */ }
  const seen = new Set(prev.map(x => `${x.uid}|${x.url}`));
  for (const m of summary.manual) {
    if (!m.url || seen.has(`${m.uid}|${m.url}`)) continue;
    seen.add(`${m.uid}|${m.url}`);
    prev.push({ uid: m.uid, subject: m.subject, url: m.url });
  }
  fs.writeFileSync(ML, JSON.stringify(prev, null, 2));
  console.log(`\nMANUAL 链接已累积到 manual_links.json（共 ${prev.length} 条），浏览器阶段: node mail-download-browser.js`);

  console.log('\n===== SUMMARY =====');
  console.log(`SAVED : ${summary.saved.length}`);
  summary.saved.forEach(x => console.log(`  UID ${x.uid} -> invoices/${x.file}`));
  console.log(`MANUAL: ${summary.manual.length}`);
  summary.manual.forEach(x => console.log(`  UID ${x.uid} ${x.subject || ''} | ${x.url || ''} | ${x.reason}`));
  console.log(`FAIL  : ${summary.failed.length}`);
})().catch(e => { console.error('ERR:', e.message || e); process.exit(1); });
