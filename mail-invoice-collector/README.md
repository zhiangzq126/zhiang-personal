# mail-invoice-collector · Email Invoice Collector

**English** | [简体中文](readme-zh.md)

Scan a configured IMAP folder with a single command, download PDF attachments and invoices linked in email bodies—including Nuonuo/Baiwang single-page applications, 51 Invoice intermediary pages, and direct tax-authority download links—and extract invoice numbers, amounts, buyers, sellers, and dates. Results are deduplicated by invoice number and appended to one Excel summary. Runs are incremental, and duplicate invoices are skipped automatically.

This is an **agent skill**, but it can also be used directly as a Python command-line tool. See [SKILL.md](SKILL.md) for the agent workflow and [reference.md](reference.md) for implementation details (both in Chinese). This README is a first-time user's guide to installation, configuration, and operation.

## What It Does

- Collect reimbursement invoices from a mailbox folder into local storage.
- Retrieve attachments (PDF/OFD, including automatic ZIP extraction) and invoices linked in email bodies.
- Parse invoice fields and append them to a workbook, deduplicating by invoice number without overwriting existing records.
- List failed downloads and invoices with missing fields separately rather than silently dropping them.

## Requirements

- **Python 3.10+** (developed and tested with 3.11).
- **Chrome** or **Edge** installed for links that require a browser. Only run `python -m playwright install chromium` if neither is available locally.
- Python packages listed in `scripts/requirements.txt`: `imap-tools`, `pdfplumber`, `openpyxl`, `requests`, `beautifulsoup4`, `PyYAML`, and `playwright`.

## Quick Start

```bash
# 1. Install dependencies
pip install -r scripts/requirements.txt

# 2. Prepare a working directory (generated data/ goes here)
mkdir ~/invoice-work && cd ~/invoice-work

# 3. Copy the configuration templates, then edit them
cp /path/to/mail-invoice-collector/config.example.yaml config.yaml
cp /path/to/mail-invoice-collector/.env.example .env
#   - Edit config.yaml: set the email address, provider, and folder
#   - Edit .env: enter the IMAP authorization code (IMAP_PASSWORD=...)

# 4. List actual mailbox folder names and update folder in config.yaml
python /path/to/mail-invoice-collector/scripts/run.py folders --config ./config.yaml

# 5. Preview matching messages, then run the full workflow
python .../scripts/run.py run --dry-run --config ./config.yaml
python .../scripts/run.py run           --config ./config.yaml
```

Without `--config`, the default is `scripts/config.yaml`. If your working directory is elsewhere, pass its configuration path explicitly; otherwise, you can run from `scripts`.

## Configuration

| File | Purpose | Contains secrets? |
|---|---|---|
| `config.yaml` | Email address, folder, link filters, and browser/OCR settings | No—do not put passwords here |
| `.env` | Mailbox authorization code in `IMAP_PASSWORD=` | **Yes; treat it like your mailbox password** |

Key fields (see the comments in `config.example.yaml` for details):

- `mailboxes[].provider`: `qq` / `163` / `126` / `gmail` / `outlook` / `custom`.
- `mailboxes[].folder`: the folder containing reimbursement emails. Run `run.py folders` to find its actual name. QQ exposes “我的文件夹” (My Folders) as “其他文件夹” (Other Folders) over IMAP.
- `fetch.browser_channel`: defaults to `auto`, trying local Chrome, then Edge, then Playwright's bundled Chromium.
- `ocr.enabled`: optional fallback for scanned invoices, disabled by default. To enable it, point to the directory containing `baidu_ocr.py` in the `mail-invoice-pipeline` skill. This skill does not store OCR credentials.

### Getting an Authorization Code

| Provider | Steps |
|---|---|
| QQ | Settings → Account → Enable IMAP/SMTP → Generate authorization code |
| 163 / 126 | Settings → POP3/SMTP/IMAP → Enable → Add authorization password |
| Gmail | Enable two-step verification → Create an app password |

## Common Commands

```bash
python run.py folders                # List actual mailbox folder names
python run.py run --dry-run          # Preview matches without downloading or writing the workbook
python run.py run --limit 30         # Process only the latest 30 messages (useful for an initial batch)
python run.py run --max-browser 5    # Retrieve at most 5 links with the browser in this run
python run.py run                    # Run the full workflow
python run.py parse-dir data/pdf     # Parse existing local PDFs to refine extraction patterns
```

## Outputs

- `data/invoices.xlsx` — cumulative, deduplicated summary with links to original files.
- `data/pdf/YYYY-MM/` — original invoices, named `date_seller_amount_invoice-number`.
- `data/pending-links.txt` — links that require manual handling.
- `data/state.json` — processed email UIDs used for incremental runs.
- `data/logs/` — execution logs.

## Security

- Treat the authorization code in `.env` like your mailbox password. **Never** put it in `config.yaml` or commit it to version control. `.gitignore` excludes `.env` and `data/`.
- If an authorization code has appeared in chat or logs, reset it in your mailbox settings.
- This repository includes only `*.example` configuration templates, not real credentials.

## Comparison with mail-invoice-pipeline

This skill is a lightweight, **pure-Python, single-command, incremental** collector for routine invoice collection. `mail-invoice-pipeline` combines Node.js and Python in a **step-by-step workflow**, with more extensive SPA downloads and Baidu OCR fallback for bulk or difficult cases. Either skill can be used independently; this collector can reuse the pipeline's `baidu_ocr` module for OCR fallback.
