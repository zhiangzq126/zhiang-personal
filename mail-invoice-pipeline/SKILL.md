---
name: mail-invoice-pipeline
description: 从 IMAP 邮箱批量收取发票并生成报销汇总表的端到端链路：下载邮件附件票、自动提取并下载正文链接票（含 51 发票中间页解析）、用浏览器自动化下载诺诺/百望等 SPA 开票平台的发票、扫描件走百度 OCR 兜底、字段校验与号码去重后输出报销汇总表 xlsx。当用户提到邮件发票、邮箱取发票、发票报销汇总、开票平台链接下载、发票附件整理时使用。
---

# 邮箱发票链路（mail-invoice-pipeline）

从 IMAP 邮箱自动收取发票（附件票 + 正文链接票 + SPA 平台浏览器下载），扫描件百度 OCR 兜底，
字段提取校验去重后生成报销汇总表 xlsx。全程无人工（登录墙类链接除外）。

```
IMAP 连接 → 定位发票邮件 ── 有附件 → mail-download-att.js ──────────────┐
                             └─ 无附件 → mail-download-links.js          │
                                 ├─ 直链/重定向/中间页 → 下载 PDF         ├→ invoices/
                                 └─ SPA 平台 → manual_links.json         │
                                     → mail-download-browser.js ─────────┤
                                        ↓
invoice_summary_build.py：文本提取(不全走百度OCR) → 校验 → 号码去重 → 报销汇总表.xlsx
```

## 前置检查（开跑前逐项确认）

正式运行前，Agent 应逐项核对下列条件，任一不满足先补齐再继续：

- [ ] **Node 版本**：`node -v` ≥ 18。
- [ ] **Python 版本**：`python --version` ≥ 3.8（含 pip）。
- [ ] **依赖已装**：已跑过 `setup.ps1` / `setup.sh`，`node_modules/` 存在且 `pip show pdfplumber openpyxl >/dev/null` 无报错。
- [ ] **邮箱配置就位**：`config.yaml` 已由 `config.example.yaml` 复制，填了 `auth.username` 与 `auth.password`（IMAP 授权码，非登录密码）。
- [ ] **OCR 配置（可选）**：需要扫描件兜底时 `ocr-config.json` 已由模板复制并填入百度 api_key/secret_key；不需要则可跳过，OCR 自动关闭。
- [ ] **凭据安全**：`config.yaml`、`ocr-config.json`、`scripts/.ocr-token-cache.json` 均未提交版本库（`.gitignore` 已覆盖）。
- [ ] **浏览器（仅 SPA 阶段）**：需要时本机已装 Chrome/Chromium/Edge，且已用 `chrome-auto-start` 起了专用实例。
- [ ] **数据目录**：已确认 `INVOICE_WORKDIR`（未设则为当前目录），产出会落在此。
- [ ] **干跑预演**：`node scripts/mail-download-links.js --dry <UID>` 只探测不写盘，可先验证连通与命中。

## 一次性配置（新环境首次使用）

1. 确认环境：Node.js ≥ 18、Python ≥ 3.8（含 pip）、装好 Chrome/Chromium/Edge（浏览器阶段需要）。
   详细版本要求与各工具用途见 [reference.md](reference.md) 第一节。
2. 安装依赖并生成配置模板（镜像旗标内置于脚本，不改全局配置）：
   - Windows: `powershell -ExecutionPolicy Bypass -File setup.ps1`
   - macOS/Linux/Git Bash: `bash setup.sh`
3. 编辑技能根目录 `config.yaml`：填入邮箱地址与 IMAP 授权码（应用专用密码，不是登录密码）。
   QQ 邮箱授权码在 mail.qq.com → 设置 → 账户 → IMAP/SMTP 服务处生成。
4. （可选）编辑 `ocr-config.json`：填入百度云「增值税发票识别」的 API Key/Secret Key，
   用于扫描件兜底；不配置则 OCR 自动关闭，链路仍可跑。

## 日常工作流

复制此清单跟踪进度：

```
- [ ] 1. 扫描：node scripts/mail-scan-links.js          （确认哪些邮件有附件、哪些是链接票）
- [ ] 2. 附件票：node scripts/mail-download-att.js <UID> （逐个；UID 来自扫描输出）
- [ ] 3. 链接票：node scripts/mail-download-links.js --all
- [ ] 4. SPA 兜底（仅当 manual_links.json 非空）：
        先起专用 Chrome（chrome-auto-start.ps1 / chrome-auto-start.sh）
        再 node scripts/mail-download-browser.js
- [ ] 5. 出表：PYTHONIOENCODING=utf-8 python scripts/invoice_summary_build.py
- [ ] 6. 核对输出：EXTRACTED/REVIEW/PY-CHECK 三段与 outputs/发票报销汇总表.xlsx
```

要点：

- 所有脚本的**数据目录** = 环境变量 `INVOICE_WORKDIR`，未设置时为当前目录。
  `invoices/`、`outputs/`、`manual_links.json` 都落在数据目录。建议在 QoderWork 工作目录下运行，
  让成果落在用户可见处。
- 文件夹无需手动指定：默认读 `config.yaml` 的 `invoiceFolder`，打不开会自动发现名称含
  「发票/invoice」的文件夹，再退 INBOX（QQ 邮箱的发票邮件在「其他文件夹/发票」，不在 INBOX）。
- 第 3 步会按内容哈希去重；第 5 步再按发票号码去重（税务平台每次下载重生成 PDF，哈希去重不够）。
- Windows 下跑 Python 记得 `PYTHONIOENCODING=utf-8`，否则控制台打印 ¥/中文会 UnicodeEncodeError。

## 脚本速查

| 脚本（均在 scripts/） | 作用 | 典型用法 |
|---|---|---|
| mail-scan-links.js | 只读扫描：列出邮件、标记有无附件、提取正文链接与提取码 | `node scripts/mail-scan-links.js` |
| mail-download-att.js | 下载某封邮件的全部附件 | `node scripts/mail-download-att.js <UID>` |
| mail-download-links.js | 无附件邮件的链接探测与下载（直链/重定向/51 发票中间页），SPA 落 manual_links.json | `--all` / `<UID>` / `--dry` |
| mail-download-browser.js | SPA 平台浏览器下载（钩 window.open 捕获签名 URL） | 先起专用 Chrome 再运行 |
| invoice_summary_build.py | 提取+校验+号码去重+生成汇总表 | `python scripts/invoice_summary_build.py` |
| baidu_ocr.py | 百度增值税发票识别（模块 + 单张 CLI 测试） | `python scripts/baidu_ocr.py <票.pdf>` |

每个脚本的完整参数、输出解读、退出码，以及每个依赖工具/每个配置项的详细说明见
[reference.md](reference.md)。报错与踩坑速查见 [troubleshooting.md](troubleshooting.md)。

## 边界（必须告知用户的情形）

- 登录墙链接（如银行账单）不模拟登录，保持 MANUAL 标记并列出 URL 供人工处理。
- SPA 浏览器阶段需要专用 Chrome 正在运行；未运行会提示先跑 chrome-auto-start 脚本。
- 百度 OCR 只认增值税类票面且每月免费 1000 次（成功失败都计数）；识别不出的票进 REVIEW 列表，不编造数据。
- 汇总表合计行是 Excel 公式；脚本输出的 `PY-CHECK totals` 是独立的 Python 交叉验证值，两者应一致。

## 验证

- `mail-download-links.js --dry <UID>` 只探测不写盘，可安全预演。
- 构建输出末尾 `PY-CHECK totals: 金额 税额 价税合计` 与 `EXTRACTED` 行数、REVIEW 条目即为健康指标。
- 单张 OCR 自检：`python scripts/baidu_ocr.py <发票PDF>` 应输出结构化 JSON 字段。
