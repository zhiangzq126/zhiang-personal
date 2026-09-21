# mail-invoice-pipeline · Email Invoice Pipeline

**English** | [简体中文](readme-zh.md)

A **step-by-step workflow** that collects invoices from IMAP email in batches and produces an Excel reimbursement summary. It downloads attachments, retrieves invoices linked in email bodies (including 51 Invoice intermediary pages), automates downloads from Nuonuo/Baiwang and other single-page applications, and falls back to Baidu OCR for scanned invoices. Field validation and invoice-number deduplication produce `发票报销汇总表.xlsx` (invoice reimbursement summary).

This is an **agent skill**, but it can also be used directly as a command-line tool. See [SKILL.md](SKILL.md) for the agent workflow, [reference.md](reference.md) for script and configuration details, and [troubleshooting.md](troubleshooting.md) for troubleshooting (these documents are in Chinese). This README is intended for first-time users.

## Workflow Overview

```text
IMAP → Find invoice emails
       ├─ Attachments → mail-download-att.js ──────────────────┐
       └─ No attachments → mail-download-links.js              │
           ├─ Direct links / redirects / intermediary pages ──┤→ invoices/
           └─ SPA platforms → manual_links.json               │
               → mail-download-browser.js ────────────────────┘
                                   ↓
invoice_summary_build.py: extract text (Baidu OCR if incomplete)
                         → validate → deduplicate by invoice number
                         → 发票报销汇总表.xlsx
```

## Requirements

- **Node.js ≥ 18** for attachment, link, and browser download scripts.
- **Python ≥ 3.8**, including pip, for workbook generation and OCR.
- **Chrome / Chromium / Edge** installed (needed only for SPA browser downloads).
- Node dependencies in `package.json`: `imapflow`, `js-yaml`, and `puppeteer-core`. Python dependencies in `requirements.txt`: `pdfplumber`, `openpyxl`, `requests`, and `pypdfium2`.

## Quick Start

```bash
# 1. Install dependencies and generate configuration templates
#    Mirror flags are built into the scripts; global settings are not changed
#    Windows:
powershell -ExecutionPolicy Bypass -File setup.ps1
#    macOS / Linux / Git Bash:
bash setup.sh

# 2. Copy the mailbox configuration template and edit it
cp config.example.yaml config.yaml
#    Set auth.username (email address) and auth.password (IMAP authorization code)

# 3. Optional: configure Baidu OCR for scanned invoices
#    OCR is automatically disabled if not configured
cp ocr-config.example.json ocr-config.json
#    Set api_key / secret_key for Baidu Cloud's VAT Invoice Recognition service

# 4. Follow the daily workflow below
```

## Configuration

| File | Purpose | Contains secrets? |
|---|---|---|
| `config.yaml` | Email address, IMAP authorization code, and invoice folder | **Yes** |
| `ocr-config.json` | Baidu OCR api_key / secret_key (optional) | **Yes** |

- Mailbox authorization code: in QQ Mail at mail.qq.com, go to Settings → Account → IMAP/SMTP Service. Use the authorization code/app password, not your login password.
- `invoiceFolder`: defaults to `其他文件夹/发票`. If the folder cannot be opened, the scripts discover folders containing “发票” or “invoice”, then fall back to INBOX.
- Baidu OCR: the documented allowance for identity-verified personal accounts is 1,000 free calls per month. Without OCR configuration, the workflow can still use the PDF text layer.

## Daily Workflow

```bash
# 1. Scan: identify attachment-based and link-based invoice emails
node scripts/mail-scan-links.js
# 2. Download attachments, one message at a time (UID comes from the scan)
node scripts/mail-download-att.js <UID>
# 3. Download invoices from links
node scripts/mail-download-links.js --all
# 4. SPA fallback (only when manual_links.json is nonempty): start dedicated Chrome first
#    Windows: powershell -File chrome-auto-start.ps1  |  Other systems: bash chrome-auto-start.sh
node scripts/mail-download-browser.js
# 5. Generate the workbook
PYTHONIOENCODING=utf-8 python scripts/invoice_summary_build.py
# 6. Check EXTRACTED / REVIEW / PY-CHECK and outputs/发票报销汇总表.xlsx
```

Notes:

- The **data directory** is set by `INVOICE_WORKDIR`, or defaults to the current directory. `invoices/`, `outputs/`, and `manual_links.json` are written there.
- On Windows, set `PYTHONIOENCODING=utf-8` when running Python to avoid `UnicodeEncodeError` when printing ¥ or Chinese text.
- Step 3 deduplicates by content hash; step 5 also deduplicates by invoice number. Tax platforms may regenerate PDFs on each download, so hashes alone are insufficient.

## Limitations

- The scripts do not automate authentication for links behind a login wall, such as bank statements. These remain marked MANUAL, with URLs listed for manual handling.
- The SPA browser stage requires a dedicated Chrome instance to be running.
- Baidu OCR recognizes VAT invoice formats only. Unrecognized invoices go to REVIEW; missing data is not fabricated.

## Security

- `config.yaml`, `ocr-config.json`, and `scripts/.ocr-token-cache.json` contain credentials and are excluded by `.gitignore`. **Never commit them or include them in a distributed skill package.**
- This repository includes only `*.example` configuration templates, not real credentials.
- If credentials have been exposed, reset them in your mailbox settings or the Baidu Cloud console.

## Comparison with mail-invoice-collector

This skill combines Node.js and Python in a **step-by-step workflow**, with more comprehensive SPA downloads and Baidu OCR fallback for bulk or difficult cases. `mail-invoice-collector` is a lightweight, **pure-Python, single-command, incremental** collector for routine invoice collection.
