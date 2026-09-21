// 扫描指定 IMAP 文件夹：找出无发票附件、正文带下载链接的邮件，提取链接与提取码（只读，不写盘）
// 用法: node mail-scan-links.js [文件夹1] [文件夹2] ...
//   缺省 = config.yaml 的 invoiceFolder（打不开则自动发现名称含 发票/invoice 的文件夹，再退 INBOX）
// 环境变量: MAIL_ACCOUNT 指定 config.yaml 中的账户 id
const path = require('path');
const fs = require('fs');
const { ImapFlow } = require('imapflow');
const { loadAccount, resolveInvoiceFolder } = require('./mail-util');

const { acc, config } = loadAccount();
const folders = process.argv.slice(2).length
  ? process.argv.slice(2)
  : [config.invoiceFolder || '']; // 缺省交给 resolveInvoiceFolder 自动发现

function normDisp(node) {
  const d = node.disposition;
  return typeof d === 'string' ? d.toLowerCase() : String((d && d.type) || '').toLowerCase();
}
// imapflow 的叶子节点把 MIME 整体放在 type（如 "text/html"），subtype 常缺失
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
    node._part = node.part || prefix || '1'; // 单 part 邮件兜底为 '1'，否则 download 返回未解码原文
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
  return buf; // 已解码或无需解码
}
function decodeSmart(buf) {
  let s = new TextDecoder('utf-8').decode(buf);
  if (s.includes('\uFFFD')) {
    try { s = new TextDecoder('gb18030').decode(buf); } catch (e) { /* keep utf8 */ }
  }
  return s;
}
function extractUrls(text) {
  const urls = new Set();
  let m;
  const reHref = /href\s*=\s*["']([^"']+)["']/gi;
  while ((m = reHref.exec(text))) urls.add(m[1]);
  const reBare = /https?:\/\/[^\s"'<>()\u4e00-\u9fff]+/gi;
  while ((m = reBare.exec(text))) urls.add(m[0].replace(/[.,;]+$/, ''));
  return [...urls].filter(u =>
    /^https?:\/\//i.test(u) &&
    !/\.(png|jpe?g|gif|webp|ico|svg)(\?|$)/i.test(u) // 跳过图片/像素跟踪
  );
}
function extractCodes(text) {
  const codes = [];
  const plain = text.replace(/<[^>]+>/g, ' ');
  const re = /(\u63d0\u53d6\u7801|\u9a8c\u8bc1\u7801|\u6388\u6743\u7801|\u53e3\u4ee4)[::\uff1a]?\s*([A-Za-z0-9]{4,12})/g; // 提取码/验证码/授权码/口令
  let m;
  while ((m = re.exec(plain))) codes.push(`${m[1]}: ${m[2]}`);
  return codes;
}

(async () => {
  const client = new ImapFlow({
    host: acc.imap.host, port: acc.imap.port, secure: acc.imap.useTLS,
    auth: { user: acc.auth.username, pass: acc.auth.password },
    logger: false,
  });
  await client.connect();

  for (const want of folders) {
    let box, folder;
    try { ({ box, folder } = await resolveInvoiceFolder(client, want || undefined)); }
    catch (e) { console.log(`[SKIP] ${want || '(自动发现)'}: ${e.message}`); continue; }
    console.log(`\n===== FOLDER: ${folder} (${box.exists} messages) =====`);
    const uids = await client.search({ all: true });
    for (const uid of uids) {
      const m = await client.fetchOne(uid, { envelope: true, bodyStructure: true }, { uid: true });
      if (!m || !m.bodyStructure) { console.log(`UID ${uid} | (no bodyStructure, skipped)`); continue; }
      const leaves = [];
      walk(m.bodyStructure, '', leaves);
      const atts = leaves.filter(l =>
        normDisp(l) === 'attachment' || /\.(pdf|ofd|xml)$/i.test(normName(l))
      );
      const subject = (m.envelope && m.envelope.subject) || '';
      const from = (m.envelope && m.envelope.from && m.envelope.from[0] && m.envelope.from[0].address) || '';
      const date = m.envelope && m.envelope.date ? m.envelope.date.toISOString().slice(0, 10) : '';
      if (atts.length) {
        console.log(`UID ${uid} | ${date} | [has ${atts.length} att] | ${subject}`);
        continue;
      }
      // 无附件：抓正文文本找链接
      const textParts = leaves.filter(l =>
        typeOf(l) === 'text' &&
        ['html', 'plain'].includes(subtypeOf(l))
      ).sort((a, b) => (subtypeOf(a) === 'html' ? -1 : 1) - (subtypeOf(b) === 'html' ? -1 : 1));
      let body = '';
      for (const tp of textParts) {
        try {
          const dl = await client.download(uid, tp._part, { uid: true });
          const chunks = [];
          for await (const c of dl.content) chunks.push(c);
          const s = decodeSmart(Buffer.concat(chunks));
          if (s.length > body.length) body = s;
        } catch (e) { /* part failed, try next */ }
      }
      const urls = extractUrls(body);
      const codes = extractCodes(body);
      console.log(`UID ${uid} | ${date} | [NO ATT] | ${subject} | from:${from}`);
      if (urls.length) urls.forEach((u, i) => console.log(`    LINK${i + 1}: ${u}`));
      else console.log('    (no http links found)');
      if (codes.length) codes.forEach(c => console.log(`    CODE: ${c}`));
    }
  }
  await client.logout();
})().catch(e => { console.error('ERR:', e.message || e); process.exit(1); });
