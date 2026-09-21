// mail-invoice-pipeline 公共模块：技能根目录 / 数据目录 / 账户加载 / 发票文件夹自动发现
// 被 mail-download-att.js / mail-scan-links.js / mail-download-links.js 引用
const path = require('path');
const fs = require('fs');
const yaml = require('js-yaml');

// 技能根目录（scripts/ 的上一级），config.yaml 与 node_modules 都在这里
const SKILL_ROOT = path.join(__dirname, '..');

// 数据工作目录：invoices/、outputs/、manual_links.json 都落在这里。
// 环境变量 INVOICE_WORKDIR 优先；未设置时用当前目录（process.cwd()）。
const DATA_DIR = process.env.INVOICE_WORKDIR || process.cwd();

// 读取技能根目录 config.yaml，选出要使用的邮箱账户。
// 选择顺序：环境变量 MAIL_ACCOUNT > config.defaultAccount > mailAccounts[0]
function loadAccount() {
  const cfgPath = path.join(SKILL_ROOT, 'config.yaml');
  if (!fs.existsSync(cfgPath)) {
    console.error(`未找到配置文件: ${cfgPath}`);
    console.error('请先复制 config.example.yaml 为 config.yaml 并填入邮箱地址与 IMAP 授权码。');
    process.exit(1);
  }
  const config = yaml.load(fs.readFileSync(cfgPath, 'utf8'));
  const accounts = (config && config.mailAccounts) || [];
  if (!accounts.length) {
    console.error('config.yaml 中没有任何邮箱账户（mailAccounts 为空）。');
    process.exit(1);
  }
  const want = process.env.MAIL_ACCOUNT || config.defaultAccount;
  const acc = (want && accounts.find(a => a.id === want)) || accounts[0];
  if (!acc || !acc.imap || !acc.auth || !acc.auth.username || !acc.auth.password) {
    console.error(`账户 "${want || accounts[0].id}" 配置不完整：需要 imap.host/imap.port/auth.username/auth.password。`);
    process.exit(1);
  }
  return { acc, config };
}

// 打开发票文件夹：首选 preferred；打不开时自动发现名称含 发票/invoice 的文件夹；再退回 INBOX。
// 返回 { folder, box }。三者都失败才抛错。
async function resolveInvoiceFolder(client, preferred) {
  const tryOpen = async (p) => {
    if (!p) return null;
    try { return await client.mailboxOpen(p); } catch (e) { return null; }
  };
  let box = await tryOpen(preferred);
  if (box) return { folder: preferred, box };

  const all = [];
  try {
    const tree = await client.listTree();
    (function walk(nodes) {
      for (const f of nodes || []) { all.push(f); walk(f.folders); }
    })(tree && tree.folders);
  } catch (e) { /* listTree 失败则跳过自动发现 */ }
  const hit = all.find(f =>
    /发票|invoice/i.test(`${f.path || ''} ${f.name || ''}`) &&
    !/已删除|deleted|trash/i.test(`${f.path || ''}`)
  );
  if (hit) {
    const p = hit.path || hit.name;
    box = await tryOpen(p);
    if (box) {
      console.log(`[FOLDER] "${preferred || '(未指定)'}" 打不开，自动发现: ${p}`);
      return { folder: p, box };
    }
  }
  box = await tryOpen('INBOX');
  if (box) {
    console.log('[FOLDER] 未找到发票文件夹，回退 INBOX');
    return { folder: 'INBOX', box };
  }
  throw new Error('找不到可用邮件文件夹（首选/自动发现/INBOX 均失败）');
}

module.exports = { SKILL_ROOT, DATA_DIR, loadAccount, resolveInvoiceFolder };
