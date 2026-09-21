# mail-invoice-pipeline · 邮箱发票链路

[English](README.md) | **简体中文**

从 IMAP 邮箱批量收取发票并生成报销汇总表的**分步流水线**：下载附件票 + 提取正文链接票（含 51 发票中间页解析）+ 浏览器自动化下载诺诺/百望等 SPA 平台票，扫描件走百度 OCR 兜底，字段校验与号码去重后输出 `发票报销汇总表.xlsx`。

这是一个 **Agent 技能（Skill）**，也可作为普通命令行工具直接使用。技能主流程见 [SKILL.md](SKILL.md)，每个脚本/配置项的详解见 [reference.md](reference.md)，报错速查见 [troubleshooting.md](troubleshooting.md)。本 README 面向"第一次上手"的用户。

## 流程概览

```
IMAP → 定位发票邮件 ─ 有附件 → mail-download-att.js ─────────────┐
                     └ 无附件 → mail-download-links.js           │
                         ├ 直链/重定向/中间页 → 下载 PDF          ├→ invoices/
                         └ SPA 平台 → manual_links.json          │
                             → mail-download-browser.js ─────────┘
                                     ↓
invoice_summary_build.py：文本提取(缺则百度OCR) → 校验 → 号码去重 → 汇总表.xlsx
```

## 环境要求

- **Node.js ≥ 18**（附件/链接/浏览器下载脚本）
- **Python ≥ 3.8**（含 pip，出表与 OCR）
- 已装 **Chrome / Chromium / Edge**（仅 SPA 浏览器下载阶段需要）
- Node 依赖见 `package.json`（`imapflow` `js-yaml` `puppeteer-core`）；Python 依赖见 `requirements.txt`（`pdfplumber` `openpyxl` `requests` `pypdfium2`）

## 快速开始

```bash
# 1. 安装依赖 + 生成配置模板（镜像旗标内置于脚本，不改全局配置）
#    Windows:
powershell -ExecutionPolicy Bypass -File setup.ps1
#    macOS / Linux / Git Bash:
bash setup.sh

# 2. 填邮箱配置：复制模板后编辑
cp config.example.yaml config.yaml
#    编辑 config.yaml：填 auth.username（邮箱）与 auth.password（IMAP 授权码）

# 3. （可选）填百度 OCR：扫描件兜底，不配则 OCR 自动关闭
cp ocr-config.example.json ocr-config.json
#    编辑 ocr-config.json：填百度云「增值税发票识别」的 api_key / secret_key

# 4. 按日常工作流逐步运行（见下）
```

## 配置说明

| 文件 | 作用 | 是否含密钥 |
|---|---|---|
| `config.yaml` | 邮箱地址 + IMAP 授权码 + 发票文件夹 | **是** |
| `ocr-config.json` | 百度 OCR api_key / secret_key（可选） | **是** |

- 邮箱授权码：QQ 在 mail.qq.com → 设置 → 账户 → IMAP/SMTP 服务处生成（是「授权码/应用专用密码」，不是登录密码）
- `invoiceFolder`：默认 `其他文件夹/发票`；打不开会自动发现含「发票/invoice」的文件夹，再退 INBOX
- 百度 OCR：个人实名每月 1000 次免费；不配置时链路仍可只靠 PDF 文本层运行

## 日常工作流

```bash
# 1. 扫描：确认哪些邮件有附件、哪些是链接票
node scripts/mail-scan-links.js
# 2. 附件票（逐个，UID 来自扫描输出）
node scripts/mail-download-att.js <UID>
# 3. 链接票
node scripts/mail-download-links.js --all
# 4. SPA 兜底（仅当 manual_links.json 非空）：先起专用 Chrome 再下载
#    Windows: powershell -File chrome-auto-start.ps1  |  其它: bash chrome-auto-start.sh
node scripts/mail-download-browser.js
# 5. 出表
PYTHONIOENCODING=utf-8 python scripts/invoice_summary_build.py
# 6. 核对 EXTRACTED / REVIEW / PY-CHECK 三段与 outputs/发票报销汇总表.xlsx
```

要点：

- **数据目录** = 环境变量 `INVOICE_WORKDIR`，未设置时为当前目录；`invoices/`、`outputs/`、`manual_links.json` 都落在此
- Windows 跑 Python 记得 `PYTHONIOENCODING=utf-8`，否则打印 ¥/中文会 `UnicodeEncodeError`
- 第 3 步按内容哈希去重，第 5 步再按发票号码去重（税务平台每次下载重生成 PDF，哈希去重不够）

## 边界

- 登录墙链接（如银行账单）不模拟登录，保持 MANUAL 标记，列 URL 供人工处理
- SPA 浏览器阶段需专用 Chrome 正在运行
- 百度 OCR 只认增值税类票面；识别不出的进 REVIEW，不编造数据

## 安全

- `config.yaml`、`ocr-config.json`、`scripts/.ocr-token-cache.json` 均含真实凭据，已被 `.gitignore` 忽略，**切勿提交或随技能包分发**
- 本仓库只包含 `*.example` 模板，不含任何真实凭据
- 凭据若曾暴露，请到邮箱后台 / 百度云控制台重置

## 与 mail-invoice-collector 的区别

本技能是 Node+Python 混合的**分步流水线**，SPA 平台下载与百度 OCR 兜底更完整，适合批量/疑难场景。`mail-invoice-collector` 是**纯 Python、单命令、增量**的轻量收集器，适合日常一键归集。
