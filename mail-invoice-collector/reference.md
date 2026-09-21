# 邮箱发票收集器 — 详细参考

SKILL.md 讲主流程，本文件讲实现细节、解析规则、平台处理与扩展方法。改代码前先读对应小节。

## 模块职责

| 文件 | 职责 | 关键点 |
|---|---|---|
| `invoice_bot/config.py` | 读 `config.yaml` + `.env`，构造 `Config` | 邮箱预设 host/port；163/126 标记 `needs_imap_id`；`mailboxes` 懒加载（parse-dir 不需要授权码）；`ocr_dir` 仅在 enabled 且目录存在时非空 |
| `invoice_bot/mailbox.py` | IMAP 收件、附件展开、正文链接提取与筛选 | `expand()` ZIP 解包；`prefer_pdf()`/`prefer_pdf_links()` 同票去 OFD/XML；`score_url()` 打分；`JUNK_LINK_RE`/`TRACKING_RE` 黑名单；`_prefer_pdf_url()` 归一税局三格式链接 |
| `invoice_bot/fetcher.py` | 链接取票：直连 + 浏览器 | `fetch_direct()` 含中间页/证书降级/文件名修复；`fetch_with_browser()` 复用单标签页；`_capture_spa_url()` 劫持 window.open |
| `invoice_bot/parser.py` | PDF 抽文本 + 字段提取 | `_normalize()` NFKC+部首修正；`fill_from_text()` 主正则；`_fallback_scan()` 无标签兜底；`_read_qr()` 二维码；`_ocr_fill()` OCR 兜底 |
| `invoice_bot/excel.py` | 汇总表读写去重 | 按发票号（无号用 SHA1）去重；追加、冻结表头、金额格式、文件超链接 |
| `run.py` | 编排 + CLI | `run`/`folders`/`parse-dir`；`process_payload()` 统一处理下载内容；`commit()` 落盘去重（改名失败退化为复制） |

## 配置项详解（config.yaml）

```yaml
mailboxes:                    # 支持多个账号，一次运行全扫
  - name: 显示名
    provider: qq              # qq|163|126|gmail|outlook 有预设 host；custom 需自填 host
    email: xxx@qq.com
    password_env: IMAP_PASSWORD   # 指向 .env 里的变量名，不写明文密码
    folder: 其他文件夹/发票    # IMAP 层级用 /；先 folders 命令查真实名
    host: null                # provider=custom 时填
    port: 993
output:
  excel: data/invoices.xlsx   # 相对路径基于 config.yaml 所在目录
  pdf_dir: data/pdf
fetch:
  link_keywords: [...]        # 链接文本或 URL 命中其一才作候选
  link_exclude: [...]         # 命中即丢弃（退订、图片、ofd_read 等）
  http_timeout: 30
  browser_timeout: 60         # 单个链接等浏览器的秒数
  use_browser: true           # false 则链接类全进 pending，不开浏览器
  browser_channel: auto       # auto|chrome|msedge|chromium
ocr:
  enabled: false
  scripts_dir: <baidu_ocr.py 目录>
```

固定生成的其它路径：`data/state.json`、`data/logs/`、`data/browser-profile/`。

## 发票字段解析规则（parser.py）

**文本预处理**：`pdfplumber` 逐页 `extract_text()` 拼接 → `_normalize()` 做 NFKC 归一化（把 `⽉⽇金` 等 CJK 兼容字符还原）+ 部首修正（`⻔→门`、`⻝→食`、`⻆→角`）。

**主提取**（`fill_from_text`，对空格压缩后的 compact 文本跑正则）：

| 字段 | 规则 |
|---|---|
| 发票号码 | `发票号码[:：]?\s*([0-9A-Z]{8,25})` |
| 发票代码 | `发票代码[:：]?\s*([0-9]{10,14})`（老版才有） |
| 开票日期 | `YYYY年MM月DD日` 或 `YYYY-MM-DD`，统一成 ISO |
| 购/销名称 | 按每个「名称：」前缀标签判断归属（含销/售→销方，购/买→购方），跳过「货物/项目/服务名称」，无标签按先购后销兜底，去掉尾部竖排栏位字 |
| 购/销税号 | `统一社会信用代码/纳税人识别号` 后 15–20 位，先购后销 |
| 金额/税额 | `合计 ¥不含税 ¥税额` 一行两值 |
| 价税合计 | 优先「(小写)¥…」，其次「价税合计…¥…」；缺项用 金额±税额 互算 |
| 发票类型 | 关键词匹配：数电普票/专票、增值税电子普通/专用、铁路电子客票、机票行程单等 |

**兜底顺序**（主提取后仍缺号码/日期/合计时）：
1. `_fallback_scan()` — 标签与取值分离的版式：扫 20 位数电号、任意位置年月日、18 位统一社会信用代码、同一行两个公司名。
2. `_read_qr()` — 发票左上角二维码（需 `PyMuPDF`+`zxing-cpp`，未装则跳过），只补号码/代码/日期，不用其金额（二维码金额是不含税额）。
3. `_ocr_fill()` — 见下。

**状态**：发票号/开票日期/价税合计三者齐全为 `OK`，否则 `NEEDS_REVIEW` 并在备注列写明缺哪项。非 PDF（OFD 等）直接 `NEEDS_REVIEW`（仅存原件不解析）。

## 疑难平台的根因与解法（fetcher.py）

这几类都表现为「浏览器打开了却拿不到文件、白等超时」，但根因不同，勿用同一招硬试。

### 诺诺 nnfp.jss.com.cn（百望、易开票同理）
- **根因**：纯前端 SPA，点「下载PDF文件」走 `window.open(签名URL)`，不产生 download 事件，`expect_download` 永远等不到。
- **解法**：进页面前注入脚本把 `window.open` 换成收集器，点完读出地址再 GET 取回（该地址无需 cookie）。
- **代码**：`_capture_spa_url()`；域名白名单 `SPA_HOST_RE`；点击策略 `SPA_CLICK_STRATEGIES`。
- **注意**：探测该地址必须用 GET，HEAD 会 405/403。

### 51发票
- `www.51fapiao.cn/tydl-login/...` = 登录墙，无票 → 进 `JUNK_LINK_RE`（mailbox.py）过滤。
- `dlj.51fapiao.cn/dlj/v7/<id>` = 中间页，GET 回 HTML，真实 PDF 在隐藏字段：取 `id="dlj"` 与 `id="signatureString"` 拼成 `{origin}/dlj/v7/downloadFile/{dlj}?signatureString=...`，**纯 HTTP 搞定**。代码 `_resolve_interstitial()`。

### 税局直下 dppt.*.chinatax.gov.cn
- **根因**：URL 导航本身即下载，`page.goto` 抛 `Download is starting`，易被误判为打不开。
- **解法**：先挂 `download` 监听，再把该异常当正常接住。
- **证书**：该平台证书链偶尔不规范，遇 SSL 错误**仅对 `*.chinatax.gov.cn` 白名单**降级 `verify=False` 并在备注留痕；其他主机证书失败一律直接失败，不放开（防中间人）。代码 `TLS_RELAX_HOST_RE`。

### 其它已内置
- meta refresh 中间页跳转（最多 3 层）。
- `Content-Disposition` 文件名裸 UTF-8 乱码：latin1→utf8 还原（`_fix_mojibake`）。
- 同票 PDF/OFD/XML 三链接归一到 PDF 后去重（`_prefer_pdf_url` + `prefer_pdf_links`）。

## 接入新平台的排查顺序

1. `python run.py run --dry-run` 确认链接被提取到、没被黑名单误杀。
2. `requests` 直接 GET，看 `Content-Type`：
   - `application/pdf` → 本该直连成功，检查是否被 `link_exclude` 或打分挤掉。
   - `text/html` → 看源码找隐藏字段或 meta refresh，能拼出地址就加进 `_resolve_interstitial()`，**优先纯 HTTP**。
   - 报 `Download is starting` → 导航即下载，已支持。
3. 源码无线索 = SPA：真实浏览器点一次下载看 Network，是 `window.open` 就把域名加进 `SPA_HOST_RE`；按钮文案特殊则补 `SPA_CLICK_STRATEGIES`。
4. 登录墙/平台首页 → 加进 `JUNK_LINK_RE`，别留着白等超时。

## OCR 兜底（可选）

无文本层扫描件、或标签与取值分离取不全时调用，备注列标「OCR 识别」。

- **复用** `mail-invoice-pipeline` 技能的 `baidu_ocr.py` 及其 `ocr-config.json`（百度云增值税发票识别），**本 skill 不存密钥**。
- **开启**：config.yaml 里 `ocr.enabled: true` + `scripts_dir` 指向 `baidu_ocr.py` 目录；另装 `pip install pypdfium2 Pillow`。
- **实现要点**（parser.py `_ocr_fill` / `_render_first_page`）：自己用 pypdfium2 渲染首页为 JPEG（160dpi、长边≤2600、q90，控制 base64 <4MB）并**显式关闭文档句柄**（外部模块不关会锁住文件，Windows 上导致后续改名失败），再调 `baidu_ocr.ocr_image_bytes()`。任何失败只记日志、不影响主流程。

## 排障速查

| 现象 | 原因 | 处置 |
|---|---|---|
| 选不中文件夹 | QQ 把「我的文件夹」映射成「其他文件夹/子名」 | `python run.py folders` 看真实名回填 |
| 163/126 登录后 SELECT 被拒 | 未上报客户端标识 | 已内置 `_send_imap_id`，无需处理 |
| 中文日志乱码 | GBK 控制台 | 命令前加 `PYTHONIOENCODING=utf-8` |
| 链接白等 60s 后失败 | 登录墙/首页 | 加进 `JUNK_LINK_RE` |
| 销方变成货物名 | 老版只有销方标签+货物行 | 已按标签判断，若新版式失效补 `_extract_names` |
| 购方名带尾巴「…销/售」 | 竖排栏位字粘连 | 已由 `COLUMN_TAIL` 去除 |
| 名字含 `⻔⻝⻆` / 日期取不到 | CJK 兼容字符 | 已由 `_normalize` 处理 |
| 一张票多行 | 平台给 PDF/OFD/XML 多链接 | 已归一去重 |
| Playwright 内置 Chromium 下不动 | 国内 CDN 慢 | 用 `browser_channel: auto` 走本机 Chrome，不必下载 |
| `Failed to open a new tab` | 每链接新建标签页 | 已改为复用单标签页 |
| 文件改名 PermissionError | 句柄未释放（多为 OCR） | 已显式关句柄 + 复制兜底 |
| OCR error_code=282103 | 图片非发票票面 | 预期，该票进 REVIEW 人工 |

## 设计约束（勿回退）

- 取票失败的链接对应邮件**不标已处理**，下次自动重试；成功的写入 `state.json`。
- 一封邮件首个链接取成功即止，并撤掉该邮件已排入浏览器队列的备用链接（同票只下一次）。
- 浏览器阶段异常被隔离，保证已下载的票一定写进 Excel、`state.json` 一定保存。
- `--max-browser` 限本轮浏览器取票数，超出的推迟到下次（避免几百链接一次跑太久）。
