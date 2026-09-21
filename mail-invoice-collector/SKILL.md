---
name: mail-invoice-collector
description: 自动从邮箱收集报销发票并汇总到 Excel。扫描 IMAP 邮箱指定文件夹，下载 PDF 附件与正文链接里的电子发票（含诺诺/百望 SPA、51发票中间页、税局直下链接），解析发票号/金额/购销方/日期等字段，按发票号去重追加进一张汇总表。当用户提到报销、发票、邮箱收发票、发票下载、发票整理、invoice、fapiao、把发票汇总到 Excel 时使用。
---

# 邮箱发票收集器

扫邮箱指定文件夹 → 下载发票（PDF 附件 + 正文链接）→ 解析字段 → 追加进一张汇总 Excel。全流程一条命令，增量运行，重复票按发票号去重。

代码已随本 skill 附带在 `scripts/`，无需从零编写。你的职责是：帮用户装依赖、填配置、按需运行，并在遇到新平台/新版式时按 [reference.md](reference.md) 扩展规则。

## 目录结构

```
mail-invoice-collector/
├── SKILL.md              # 本文件：主流程与命令
├── reference.md          # 详细：模块职责、解析规则、平台处理、排障、扩展指南
├── config.example.yaml   # 配置模板
├── .env.example          # 授权码模板
└── scripts/
    ├── run.py            # 入口：run / folders / parse-dir 三个子命令
    ├── requirements.txt
    ├── invoice_bot/      # config / mailbox / fetcher / parser / excel 五个模块
    └── tests/            # test_parse.py（离线解析） / test_browser_fetch.py（取票链路）
```

## 前置检查（开跑前逐项确认）

正式运行前，Agent 应逐项核对下列条件，任一不满足先补齐再继续，避免中途失败：

- [ ] **Python 版本**：`python --version` ≥ 3.10；命令为 `python3` 的环境相应替换。
- [ ] **依赖已装**：`pip show imap-tools pdfplumber openpyxl >/dev/null` 无报错；缺则 `pip install -r scripts/requirements.txt`。
- [ ] **浏览器可用**：本机已装 Chrome 或 Edge（处理链接票需要）；都没有再 `python -m playwright install chromium`。
- [ ] **配置就位**：工作目录存在 `config.yaml`（由 `config.example.yaml` 复制）与 `.env`（由 `.env.example` 复制并填了 `IMAP_PASSWORD`）。
- [ ] **凭据安全**：授权码只在 `.env`，未写进 `config.yaml`，未被提交版本库。
- [ ] **文件夹名正确**：已用 `python run.py folders` 查到真实文件夹名并回填 `config.yaml` 的 `folder`。
- [ ] **干跑命中**：`python run.py run --dry-run` 能列出预期邮件，再正式运行。

## 环境依赖

- **Python 3.10+**（开发验证于 3.11）
- **必装 pip 包**（`scripts/requirements.txt`）：`imap-tools` `pdfplumber` `openpyxl` `requests` `beautifulsoup4` `PyYAML` `playwright`
- **浏览器**：默认 `browser_channel: auto`，直接驱动本机已装的 **Chrome**（无则 Edge），**不必**下载 Playwright 内置 Chromium。仅当本机没有 Chrome/Edge 时才需 `python -m playwright install chromium`（国内 CDN 慢，可能需重试）。
- **可选 OCR**：扫描件/字段残缺时兜底，复用 `mail-invoice-pipeline` 技能的 `baidu_ocr` 模块与其密钥（需另装 `pypdfium2`、`Pillow`）。默认关闭。

## 首次配置（copy this checklist）

```
- [ ] 1. 装依赖：pip install -r scripts/requirements.txt
- [ ] 2. 邮箱后台开 IMAP，生成「授权码」（不是登录密码）
- [ ] 3. 邮箱里建文件夹，把要报销的邮件拖进去
- [ ] 4. 建工作目录，放 config.yaml + .env（见下）
- [ ] 5. python run.py folders 查真实文件夹名，回填 config.yaml
- [ ] 6. python run.py run --dry-run 确认命中
```

**授权码获取**：QQ = 设置→账号→开启 IMAP/SMTP→生成授权码；163/126 = 设置→POP3/SMTP/IMAP→开启→新增授权密码；Gmail = 应用专用密码。

**工作目录**：在任意空目录放一份 `config.yaml`（照抄 `config.example.yaml` 改）和 `.env`（照抄 `.env.example` 填授权码）。产出的 `data/` 会生成在此目录。运行时用 `--config <该目录>/config.yaml` 指定，或直接 `cd` 进去跑。

**安全**：`.env` 里的授权码等同邮箱密码，切勿写进 config.yaml 或提交到版本库；聊天里暴露过的授权码应在邮箱后台重置。

## 日常命令

```bash
cd scripts    # 或全程用 --config 指向工作目录

python run.py folders                    # 列出邮箱真实文件夹名（QQ 会把「我的文件夹」映射成「其他文件夹」）
python run.py run --dry-run              # 只看命中哪些邮件，不下载不写表
python run.py run --limit 30             # 只处理最新 30 封（邮件多时首次分批用）
python run.py run --max-browser 5        # 本轮最多用浏览器取 5 个链接，其余下次继续
python run.py run                        # 全流程
python run.py parse-dir data/pdf         # 只解析本地已有 PDF，用于校准解析规则
```

`--config` 默认取 `scripts/config.yaml`；用户的工作目录在别处时显式传 `--config /path/to/config.yaml`。

## 端到端流程（run 做了什么）

1. **收件** `mailbox.py`：IMAP SSL 登录（163/126 自动发 `IMAP ID` 规避「不安全登录」拒绝）→ 选中配置的文件夹 → 按 `state.json` 里的已处理 UID 做增量 → 取出 PDF/OFD 附件（ZIP 自动解包）与正文候选链接。
2. **筛链接**：黑名单剔除登录墙/首页/追踪像素 → 同票 PDF/OFD/XML 归一去重 → 按 URL 特征打分，每封只留前 3 个候选。
3. **取票** `fetcher.py`：先纯 HTTP 直连（含 51发票中间页签名二次请求、meta refresh 跳转、税局直下链接、文件名乱码修复）；直连拿不到才开本机 Chrome，处理诺诺/百望 SPA（劫持 `window.open` 捕获签名地址）与需登录/验证码的页面（弹窗让用户手动过，登录态存 `data/browser-profile/` 复用）。
4. **解析** `parser.py`：`pdfplumber` 抽文本 → NFKC 规范化（修 CJK 兼容字） → 正则提取发票号/日期/购销方+税号/金额/税额/价税合计/发票类型 → 标签取不到时走无标签兜底扫描 → 仍缺则二维码 / OCR 兜底。
5. **入表** `excel.py`：按发票号（无号用文件 SHA1）去重后追加进 `invoices.xlsx`，冻结表头、金额数字格式、文件列超链接可点开原件。
6. **收尾** `run.py`：更新 `state.json`；取不到的链接写 `data/pending-links.txt` 且对应邮件不标已处理（下次重试）；缺字段的票状态标 `NEEDS_REVIEW` 并在日志与备注列说明。

## 产出物

- `data/invoices.xlsx` — 汇总表，累加去重，文件列超链接
- `data/pdf/年-月/` — 发票原件，命名 `日期_销方_金额_发票号`
- `data/pending-links.txt` — 需手工点开的链接清单
- `data/state.json` — 已处理邮件 UID（增量依据）
- `data/logs/` — 运行日志

## 验证

改动解析或取票逻辑后务必先跑离线测试（不连网、不连邮箱）：

```bash
cd scripts
python tests/test_parse.py          # 发票字段正则：数电票/老版增普票/铁路客票/双栏粘连等
python tests/test_browser_fetch.py  # 取票链路：直连/中间页签名/meta refresh/SPA 捕获/点按钮下载
```

两个测试全绿再跑真实邮箱。用真实票校准时：把票放进 `data/pdf/` 跑 `parse-dir` 看提取结果，再据此改 `invoice_bot/parser.py` 的正则。

## 常见处置

- **连不上/选不中文件夹**：先 `python run.py folders`，报错会列出真实文件夹名。
- **链接取不到票**：先判断平台类型（登录墙/中间页/SPA/直下），对应扩展规则见 [reference.md](reference.md) 的「疑难平台」与「接入新平台」两节。
- **字段缺失（NEEDS_REVIEW）**：扫描件无文本层 → 开 OCR；版式怪异 → 用 `parse-dir` 看文本后补正则。
- **中文日志乱码**：Git Bash/GBK 控制台前加 `PYTHONIOENCODING=utf-8`。

模块内部实现、解析正则清单、平台处理细节、扩展步骤，全部见 [reference.md](reference.md)。
