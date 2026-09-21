# zhiang-personal

**English** | [简体中文](readme-zh.md)

A collection of personal tools and projects.

## Arch Icons

[Arch Icons](arch-icons/) is an SVG icon management tool for architecture diagrams. It provides browsing, search, import, review, preferences, and a query interface for AI agents.

```bash
git clone https://github.com/zhiangzq126/zhiang-personal.git
cd zhiang-personal/arch-icons
python3 scripts/iconlib.py serve --open
```

Requires Python 3.9+. No additional Python packages are needed for everyday use. See the [project documentation](arch-icons/README.md) for details and the [agent contract](arch-icons/docs/agent-contract.md) (Chinese) for agent integration.

## RedisShake Migration

[RedisShake Migration](redis-shake-migration/) is an agent skill for end-to-end management of RedisShake migration tasks. It extracts migration details from Excel spreadsheets, text descriptions, or guided questions, generates `shake.toml` configuration files, and deploys, starts, stops, and monitors tasks locally or remotely over SSH.

It covers configuration and operations for Redis migration and synchronization, not migrations involving MongoDB, MySQL, Elasticsearch, or other non-Redis databases. It does not validate post-migration data consistency; use redis-full-check for that purpose. Tasks run on Linux servers where the redis-shake binary is already installed, and the agent platform must support Bash/shell tools.

See [SKILL.md](redis-shake-migration/SKILL.md) for details.

## Mail Invoice Collector

[Mail Invoice Collector](mail-invoice-collector/) is a pure-Python agent skill that collects reimbursement invoices from email and summarizes them in Excel. It scans a configured IMAP folder, downloads PDF attachments and invoices linked in email bodies—including Nuonuo/Baiwang single-page applications, 51 Invoice intermediary pages, and direct tax-authority download links—and extracts invoice numbers, amounts, buyers, sellers, and dates. Results are appended incrementally to one summary workbook, deduplicated by invoice number. The full workflow runs with one command; OCR fallback is optional.

Before use, copy `.env.example` and `config.example.yaml` to local `.env` and `config.yaml` files and supply the mailbox authorization code in `.env`, which is excluded from Git. See [SKILL.md](mail-invoice-collector/SKILL.md) (Chinese) for details.

## Mail Invoice Pipeline

[Mail Invoice Pipeline](mail-invoice-pipeline/) is an end-to-end email invoice workflow built with Node.js and Python. It downloads attachments, retrieves invoices from links in email bodies (including 51 Invoice intermediary pages), automates browser downloads from Nuonuo/Baiwang and similar single-page applications, and uses Baidu OCR as a fallback for scanned invoices. Field validation and invoice-number deduplication produce an XLSX reimbursement summary. It offers a more comprehensive, step-by-step workflow through separate scripts.

Before use, copy `config.example.yaml` and `ocr-config.example.json` to local `config.yaml` and `ocr-config.json` files and fill in your credentials. These local files are excluded by `.gitignore` and must not be committed. OCR is automatically disabled when it is not configured. See [SKILL.md](mail-invoice-pipeline/SKILL.md) (Chinese) for details.

## Licensing

Licenses are declared separately for each project; see [LICENSES.md](LICENSES.md). Original Arch Icons tool code is MIT-licensed. The code license does not grant additional rights to third-party icons, trademarks, or upstream materials.
