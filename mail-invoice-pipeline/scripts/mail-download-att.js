// 下载指定 IMAP 邮件的全部附件（发票 PDF/OFD/XML 等）到 <数据目录>/invoices/
// 用法:
//   node mail-download-att.js <UID> [文件夹]
//   文件夹缺省 = config.yaml 的 invoiceFolder（打不开则自动发现/INBOX）
// 环境变量:
//   INVOICE_WORKDIR  数据目录（invoices/ 所在处），缺省 = 当前目录
//   MAIL_ACCOUNT     指定 config.yaml 中的账户 id
const path = require('path');
const fs = require('fs');
const { ImapFlow } = require('imapflow');
const { DATA_DIR, loadAccount, resolveInvoiceFolder } = require('./mail-util');

const uid = Number(process.argv[2] || 0);
const { acc, config } = loadAccount();
const folderArg = process.argv[3] || config.invoiceFolder || 'INBOX';
const outDir = path.join(DATA_DIR, 'invoices');
if (!uid) {
  console.log('用法: node mail-download-att.js <UID> [文件夹]');
  console.log('（UID 可先用 mail-scan-links.js 查看；环境变量 INVOICE_WORKDIR 控制数据目录）');
  process.exit(1);
}

function normDisp(node) {
  const d = node.disposition;
  return typeof d === 'string' ? d.toLowerCase() : String((d && d.type) || '').toLowerCase();
}
function normName(node) {
  return (node.dispositionParameters && node.dispositionParameters.filename) || (node.parameters && node.parameters.name) || '';
}
function walk(node, prefix, leaves) {
  if (node.childNodes && node.childNodes.length) {
    node.childNodes.forEach((c, i) => walk(c, prefix ? `${prefix}.${i + 1}` : String(i + 1), leaves));
  } else {
    node._part = node.part || prefix;
    leaves.push(node);
  }
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const client = new ImapFlow({
    host: acc.imap.host, port: acc.imap.port, secure: acc.imap.useTLS,
    auth: { user: acc.auth.username, pass: acc.auth.password },
    logger: false,
  });
  await client.connect();
  const { folder } = await resolveInvoiceFolder(client, folderArg);
  const m = await client.fetchOne(uid, { envelope: true, bodyStructure: true }, { uid: true });
  console.log('FOLDER:', folder);
  console.log('SUBJECT:', m.envelope && m.envelope.subject);
  const leaves = [];
  walk(m.bodyStructure, '', leaves);
  const atts = leaves.filter(l => normDisp(l) === 'attachment' || /\.(pdf|ofd|xml)$/i.test(normName(l)));
  console.log('LEAVES:', leaves.map(l => `${l._part}:${l.type || ''}:${normDisp(l) || '-'}`).join(' | '));
  if (!atts.length) { console.error('NO ATTACHMENT FOUND'); console.error(JSON.stringify(m.bodyStructure, null, 2)); process.exit(2); }
  for (const a of atts) {
    let fname = normName(a) || `part-${a._part}`;
    fname = path.basename(fname).replace(/[\\/:*?"<>|]/g, '_');
    const dl = await client.download(uid, a._part, { uid: true });
    const dest = path.join(outDir, fname);
    await new Promise((resolve, reject) => {
      const ws = fs.createWriteStream(dest);
      dl.content.on('error', reject);
      ws.on('error', reject);
      ws.on('finish', resolve);
      dl.content.pipe(ws);
    });
    const st = fs.statSync(dest);
    console.log('SAVED:', dest, st.size, 'bytes');
  }
  await client.logout();
})().catch(e => { console.error('ERR:', e.message || e); process.exit(1); });
