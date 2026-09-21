# mail-invoice-collector · 邮箱发票收集器

[English](README.md) | **简体中文**

一条命令扫描 IMAP 邮箱指定文件夹，下载 PDF 附件与正文链接里的电子发票（诺诺/百望 SPA、51 发票中间页、税局直下链接），解析发票号/金额/购销方/日期，按发票号去重后追加进一张汇总 Excel。增量运行，重复票自动跳过。

这是一个 **Agent 技能（Skill）**，也可作为普通 Python 命令行工具直接使用。技能主流程与内部实现分别见 [SKILL.md](SKILL.md) 与 [reference.md](reference.md)；本 README 面向"第一次上手"的用户，讲清楚怎么装、怎么配、怎么跑。

## 它能做什么

- 扫一个邮箱文件夹里的报销邮件，把发票统一收进本地
- 附件票（PDF/OFD，含 ZIP 自动解包）+ 正文链接票都能取
- 解析字段并入表，按发票号去重，累加不覆盖
- 取不到的链接、缺字段的票会被单独列出，不会静默丢失

## 环境要求

- **Python 3.10+**（开发验证于 3.11）
- 已装 **Chrome**（或 Edge）——用于处理需要浏览器的链接票；本机没有时才需 `python -m playwright install chromium`
- pip 依赖见 `scripts/requirements.txt`：`imap-tools` `pdfplumber` `openpyxl` `requests` `beautifulsoup4` `PyYAML` `playwright`

## 快速开始

```bash
# 1. 装依赖
pip install -r scripts/requirements.txt

# 2. 准备一个工作目录（产出的 data/ 会落在这里）
mkdir ~/invoice-work && cd ~/invoice-work

# 3. 放配置：从模板复制后修改
cp /path/to/mail-invoice-collector/config.example.yaml config.yaml
cp /path/to/mail-invoice-collector/.env.example .env
#   - 编辑 config.yaml：填邮箱地址、provider、文件夹名
#   - 编辑 .env：填 IMAP 授权码（IMAP_PASSWORD=...）

# 4. 查邮箱真实文件夹名，回填 config.yaml 的 folder 字段
python /path/to/mail-invoice-collector/scripts/run.py folders --config ./config.yaml

# 5. 干跑确认命中，再正式跑
python .../scripts/run.py run --dry-run --config ./config.yaml
python .../scripts/run.py run           --config ./config.yaml
```

`--config` 不传时默认取 `scripts/config.yaml`；工作目录在别处就显式传路径，或直接 `cd scripts` 后运行。

## 配置说明

| 文件 | 作用 | 是否含密钥 |
|---|---|---|
| `config.yaml` | 邮箱地址、文件夹、链接过滤、浏览器/OCR 开关 | 否（密码不写这里） |
| `.env` | `IMAP_PASSWORD=` 邮箱授权码 | **是，等同邮箱密码** |

关键字段（详见 `config.example.yaml` 内注释）：

- `mailboxes[].provider`：`qq` / `163` / `126` / `gmail` / `outlook` / `custom`
- `mailboxes[].folder`：报销邮件所在文件夹，先用 `run.py folders` 查真实名（QQ 会把「我的文件夹」显示为「其他文件夹」）
- `fetch.browser_channel`：默认 `auto`（优先本机 Chrome→Edge→内置 Chromium）
- `ocr.enabled`：扫描件兜底，默认关闭；开启需指向 `mail-invoice-pipeline` 技能的 `baidu_ocr.py` 目录，本技能不存放 OCR 密钥

### 授权码怎么拿

| 邮箱 | 路径 |
|---|---|
| QQ | 设置 → 账号 → 开启 IMAP/SMTP → 生成授权码 |
| 163 / 126 | 设置 → POP3/SMTP/IMAP → 开启 → 新增授权密码 |
| Gmail | 开两步验证 → 应用专用密码 |

## 常用命令

```bash
python run.py folders                # 列邮箱真实文件夹名
python run.py run --dry-run          # 只看命中哪些邮件，不下载不写表
python run.py run --limit 30         # 只处理最新 30 封（首次分批）
python run.py run --max-browser 5    # 本轮最多用浏览器取 5 个链接
python run.py run                    # 全流程
python run.py parse-dir data/pdf     # 只解析本地已有 PDF，用于校准正则
```

## 产出物

- `data/invoices.xlsx` — 汇总表（累加去重，文件列可点开原件）
- `data/pdf/年-月/` — 发票原件，命名 `日期_销方_金额_发票号`
- `data/pending-links.txt` — 需手工点开的链接
- `data/state.json` — 已处理邮件 UID（增量依据）
- `data/logs/` — 运行日志

## 安全

- `.env` 里的授权码等同邮箱密码，**切勿**写进 `config.yaml` 或提交到版本库；`.gitignore` 已忽略 `.env` 与 `data/`
- 若授权码曾在聊天/日志里暴露，请到邮箱后台重置
- 本仓库只包含 `*.example` 模板，不含任何真实凭据

## 与 mail-invoice-pipeline 的区别

本技能是**纯 Python、单命令、增量**的轻量收集器，适合日常一键归集。`mail-invoice-pipeline` 是 Node+Python 混合的**分步流水线**，SPA 平台下载与百度 OCR 兜底更强，适合批量/疑难场景。两者可独立使用；本技能的 OCR 兜底可复用 pipeline 的 `baidu_ocr` 模块。
