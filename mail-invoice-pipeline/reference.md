# mail-invoice-pipeline 详细参考

SKILL.md 的配套参考：环境依赖要求、每个脚本、每个工具、每个配置项的详细说明。

## 1. 环境依赖要求

### 1.1 Node.js ≥ 18（必须）

链路里 4 个邮件/浏览器脚本都是 Node 脚本。必须 ≥ 18 的原因：

- 脚本内使用全局 `fetch`（Node 18 起内置，基于 undici），不额外装 axios/node-fetch。
- `puppeteer-core@25.x` 官方要求 Node ≥ 18。
- imapflow 依赖 Node 现代 API（如 `for await` 流消费）。

验证：`node --version`（本机实测 v22 可用）。建议用 nvm/nvm-windows 管理，避免动系统全局。

### 1.2 Python ≥ 3.8（必须）

`invoice_summary_build.py` 与 `baidu_ocr.py` 使用。本机实测 3.11 可用。验证：`python --version`。

### 1.3 npm 依赖（技能根目录 node_modules，由 setup 安装）

| 包 | 版本约束 | 用途 |
|---|---|---|
| imapflow | ^1.0.0 | IMAP 客户端：连接/搜索/fetch/下载 MIME 部件，支持 TLS |
| js-yaml | ^4.1.0 | 解析 config.yaml |
| puppeteer-core | ^25.6.0 | 经 CDP 驱动专用 Chrome（不自带 Chromium 下载，体积小） |

安装命令（setup 脚本已内置，国内镜像以**内联旗标**传入，不改全局 npm 配置）：
`npm install --registry=https://registry.npmmirror.com`

### 1.4 Python 依赖（requirements.txt）

| 包 | 用途 |
|---|---|
| pdfplumber | 提取发票 PDF 文本层 |
| openpyxl | 生成 xlsx 汇总表（样式/合并单元格/SUM 公式） |
| requests | 调百度 OCR HTTP 接口 |
| pypdfium2 | 扫描件渲染成 JPEG 供 OCR（160dpi，控制图大小 <4MB） |

安装：`python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
（同样内联镜像，不改全局 pip 配置）

### 1.5 Chrome/Chromium/Edge（浏览器阶段需要，其余阶段不需要）

SPA 平台（诺诺/百望等）下载需要一个可被 CDP 驱动的浏览器。chrome-auto-start 脚本按
以下顺序探测：Windows 的 `Program Files/Program Files (x86)/LocalAppData` 下的 Chrome →
Edge 兜底；macOS 的 `/Applications/Google Chrome.app`；Linux 的 `google-chrome/chromium` 等。
也可用环境变量 `CHROME_EXE` 直接指定可执行文件。浏览器以**隔离 profile**（技能目录下
`chrome-auto/`）启动，不携带用户主浏览器的登录态与 Cookie。

### 1.6 网络要求

- 到邮箱 IMAP 服务器 993/TCP（TLS）。
- 到各开票平台 443/HTTPS（下载发票直链/中间页）。
- 到百度云 OCR 接口 `aip.baidubce.com` 443/HTTPS（仅配置了 OCR 时）。
- 个别税务/开票平台证书链不规范时，脚本仅对当次请求降级 TLS 校验并在输出中以
  `[TLS verify disabled for this host]` 留痕，不做全局降级。

### 1.7 平台特定注意（Windows）

- Python 打印中文/¥ 前加 `PYTHONIOENCODING=utf-8`，否则 GBK 控制台 UnicodeEncodeError。
- Git Bash 里 Windows 路径优先用正斜杠；`robocopy` 等带 `/开关` 的命令会被 MSYS 误解析。
- PowerShell 5.1 下 `.ps1` 若含非 ASCII 需 UTF-8 with BOM，本技能的 setup/chrome 启动脚本
  均为纯 ASCII 以规避此坑。

## 2. 目录结构与数据流

```
<技能根目录>/                      # ~/.qoderwork/skills/mail-invoice-pipeline
├── SKILL.md / reference.md / troubleshooting.md
├── package.json / node_modules/   # imapflow js-yaml puppeteer-core
├── requirements.txt
├── config.example.yaml / config.yaml        # 邮箱账户（含凭据，勿分发）
├── ocr-config.example.json / ocr-config.json # 百度 OCR（含凭据，勿分发）
├── setup.ps1 / setup.sh           # 一次性依赖安装 + 模板拷贝
├── chrome-auto-start.ps1 / .sh    # 启动专用 Chrome（profile 落 chrome-auto/）
└── scripts/                       # 全部业务脚本
    ├── mail-util.js               # 公共：账户加载 / 发票文件夹自动发现
    ├── mail-scan-links.js         # 只读扫描
    ├── mail-download-att.js       # 附件下载
    ├── mail-download-links.js     # 链接探测下载
    ├── mail-download-browser.js   # SPA 浏览器下载
    ├── invoice_summary_build.py   # 提取+校验+去重+出表
    └── baidu_ocr.py               # OCR 模块 + CLI

<数据目录>/                        # = $INVOICE_WORKDIR 或当前目录
├── invoices/                      # 所有下载到的发票文件
├── manual_links.json              # SPA/待人工链接清单（links 与 browser 脚本间的交接件）
└── outputs/发票报销汇总表.xlsx
```

代码（技能目录）与数据（数据目录）分离：同一技能可服务多个数据目录，历史批次不被覆盖。

## 3. 脚本逐个说明

### 3.1 scripts/mail-util.js（公共模块，不直接运行）

导出：

- `SKILL_ROOT`：技能根目录（config.yaml / node_modules 所在）。
- `DATA_DIR`：数据目录 = `INVOICE_WORKDIR` 环境变量，缺省 `process.cwd()`。
- `loadAccount()`：读 `config.yaml`，按 `MAIL_ACCOUNT` 环境变量 → `defaultAccount` →
  第一个账户的顺序选账户；缺配置时打印指引并退出码 1。
- `resolveInvoiceFolder(client, preferred)`：打开首选文件夹；失败则 `listTree()` 自动发现
  名称含 发票/invoice（且非已删除）的文件夹；再失败回退 INBOX；全失败抛错。

### 3.2 scripts/mail-scan-links.js（只读扫描）

作用：列出文件夹内每封邮件——有附件的标 `[has N att]`；无附件的提取正文 http(s) 链接
（`LINK1/2/3`）与疑似提取码（`CODE: 提取码: xxxx`）。**不写任何文件**，用于先侦察。

用法：`node scripts/mail-scan-links.js [文件夹1] [文件夹2] ...`（缺省走自动发现）。

输出示例：
`UID 531 | 2026-08-05 | [has 3 att] | 发票开具成功...`、
`UID 470 | 2026-08-07 | [NO ATT] | ...| from:...` 下挂 `LINK1: https://...`。

解读：`[has att]` → 用 mail-download-att.js；`[NO ATT]` 且带 LINK → 用 mail-download-links.js。
正文解码只做 utf-8 → gb18030 兜底判断，**不再解 quoted-printable/base64**（imapflow 的
`download()` 已解码，二次解码会破坏链接）。

### 3.3 scripts/mail-download-att.js（附件下载）

作用：下载某封邮件的全部附件（`disposition=attachment` 或文件名以 pdf/ofd/xml 结尾的部件，
递归遍历嵌套 multipart）到 `<数据目录>/invoices/`。

用法：`node scripts/mail-download-att.js <UID> [文件夹]`。UID 来自扫描输出；文件夹缺省 =
config 的 invoiceFolder + 自动发现。无附件时退出码 2 并打印 bodyStructure 供排查。

解读：每个附件一行 `SAVED: <路径> <字节数>`。数电票邮件通常一次给 PDF+OFD+XML 三件套，
全部保存；汇总表只消费 PDF。

### 3.4 scripts/mail-download-links.js（链接探测下载）

作用：对无附件邮件正文里的候选链接逐个探测并下载发票文件。三层能力：

1. **直链/重定向**：手动跟随 30x（≤8 跳），最终响应是 PDF/OFD/XML/ZIP 或带
   `Content-Disposition: attachment` 才保存；45 秒超时。
2. **中间页解析**：返回 HTML 时尝试 51fapiao 分享页模式（隐藏字段 `dlj`+`signatureString`
   → 拼 `/dlj/v7/downloadFile/<dlj>?signatureString=...` 二次请求）与 meta refresh。
3. **交给浏览器**：仍不行的记入 `<数据目录>/manual_links.json`（按 `uid|url` 去重合并）。

候选链接打分排序取前 3：URL 含 `.pdf` +10、含 dlj/download/dzfp 等路径 +4、含
fapiao/invoice/诺诺/百望等域 +3、短链 +1。跟踪像素/图片/首页页脚/登录墙链接被
`TRACKING`/`HOMEJUNK` 规则过滤。

用法：

- `node scripts/mail-download-links.js --all [文件夹]`　批量
- `node scripts/mail-download-links.js <UID> [文件夹]`　单封
- 追加 `--dry`　只探测不写盘（批量时仅演示第一封）

解读：每条链接一行裁决 `SAVED / DRY-OK / DUP（与已有文件哈希相同）/ MANUAL（落入
manual_links.json）/ FAIL`；结尾 `===== SUMMARY =====` 汇总三类计数。文件名优先取
Content-Disposition（含裸 UTF-8 字节乱码修复），否则取邮件主题里的发票号码命名
`发票_<号码>.pdf`。

### 3.5 scripts/mail-download-browser.js（SPA 浏览器下载）

前置：专用 Chrome 已启动（`chrome-auto-start.ps1` / `.sh`，CDP 默认 9222，可用
`INVOICE_CDP_URL` 覆盖）。

作用：处理 `manual_links.json` 中命中 `SPA_HOSTS`（诺诺 `nnfp/fp.jss.com.cn`、百望
`bwfp/u/pis/web.baiwang.com`、易开票 `yun.ekaikai.cn`）的链接。流程：puppeteer 打开页面 →
`evaluateOnNewDocument` 钩住 `window.open` → 依次尝试三个点击选择器（精确「下载PDF文件」→
含「下载PDF」的短文本 → 含 PDF+下载字样的 a/button）→ 捕获 `window.__opens` 里带签名的
下载 URL → 普通 HTTP GET（**用 GET 不用 HEAD**，HEAD 会被 405/403 拒绝；无需 cookie）→
校验 `%PDF-` 魔数 → sha1 哈希去重 → 保存 `发票_<号码>.pdf`。成功条目从 manual_links.json
移除，失败保留（`STILL-MANUAL`）。

用法：`node scripts/mail-download-browser.js`（消费清单）或 `node scripts/mail-download-browser.js <url>...`（直接指定链接）。

解读：每张票一段 `clicked「下载PDF文件」-> <签名URL>` + `SAVED ...bytes`；结尾
`===== BROWSER STAGE ===== SAVED/DUP: N STILL-MANUAL: M`。

注意：puppeteer 的 `page.evaluate` 参数不能传函数，点击选择器是作为 pageFunction 直接传入的；
扩展新平台选择器时保持这一写法。

### 3.6 scripts/invoice_summary_build.py（提取+校验+去重+出表）

作用：遍历 `<数据目录>/invoices/*.pdf`：pdfplumber 提取文本（先 NFKC 归一化处理 CJK 兼容
字符）→ 正则取 发票号码/开票日期/销售方(第二个"名称")/项目(*分类*名)/金额/税额/价税合计
→ 文本层不全时自动调 `baidu_ocr.extract_ocr` 兜底 → 校验 `金额+税额=价税合计`（允差 0.01）
→ **按发票号码去重**（税务平台每次下载重生成 PDF，哈希去重不够）→ 按日期升序生成
`<数据目录>/outputs/发票报销汇总表.xlsx`（表头灰底、边框、金额两位小数、合计行 SUM 公式）。

用法：`PYTHONIOENCODING=utf-8 python scripts/invoice_summary_build.py`（数据目录 =
`INVOICE_WORKDIR` 或当前目录）。

解读：`EXTRACTED N invoices`（每行 `[text]/[ocr]` 标记提取途径）→ `REVIEW:`（需人工复核：
提取不全或金额校验失败，**绝不编造**）→ `PY-CHECK totals: 金额 税额 价税合计`（独立交叉
验证，应与 Excel 合计一致）→ `SAVED <xlsx 路径>`。

### 3.7 scripts/baidu_ocr.py（OCR 模块 + CLI）

作用：百度云「增值税发票识别」。token 自动获取并缓存 30 天（`scripts/.ocr-token-cache.json`）；
PDF 先渲染成 160dpi JPEG(q90、长边 ≤2600px) 再 base64 上传（规避 4MB 图限制）；
`parse_fields()` 把百度返回的**英文键名**（`InvoiceNum`/`InvoiceDate`/`SellerName`/
`TotalAmount`/`TotalTax`/`AmountInFiguers`/`CommodityName[]`）映射成标准字段，中文键兜底。

用法：`python scripts/baidu_ocr.py <发票PDF或图片> [页码]` 输出 JSON；模块方式
`from baidu_ocr import ocr_invoice_file, parse_fields`。

解读：正常输出结构化字段 JSON；非发票图会得百度 `error_code=282103`（模板不匹配）属预期；
响应必须 `resp.content.decode('utf-8')` 显式解码（响应头无 charset）。

### 3.8 setup.ps1 / setup.sh

一次性安装：检查 node/npm/python → `npm install --registry=npmmirror` → `pip install -r
requirements.txt -i 清华源` → 从 example 拷贝 config.yaml/ocr-config.json（已存在则跳过）→
打印下一步。镜像均为内联旗标，不改全局配置。

### 3.9 chrome-auto-start.ps1 / chrome-auto-start.sh

先探 9222 端口，已在监听直接返回；否则探测 Chrome/Edge 可执行文件（或 `CHROME_EXE`），
以 `--remote-debugging-port=9222 --user-data-dir=<技能目录>/chrome-auto --no-first-run`
启动。关掉窗口即停止；profile 目录可随时整个删除回滚。

## 4. 配置项逐个说明

### 4.1 config.yaml（技能根目录，含凭据，勿随包分发）

| 键 | 必填 | 说明 |
|---|---|---|
| `invoiceFolder` | 否 | 发票邮件所在文件夹路径（QQ 为「其他文件夹/发票」）。打开失败触发自动发现 → INBOX |
| `defaultAccount` | 否 | 默认账户 id；环境变量 `MAIL_ACCOUNT` 优先 |
| `mailAccounts[].id` | 是 | 账户唯一标识（选择账户用） |
| `mailAccounts[].displayName` | 否 | 展示名 |
| `mailAccounts[].imap.host` | 是 | IMAP 服务器（QQ: imap.qq.com；163: imap.163.com；Gmail: imap.gmail.com…） |
| `mailAccounts[].imap.port` | 是 | 通常 993（TLS） |
| `mailAccounts[].imap.useTLS` | 是 | 993 端口必须 true |
| `mailAccounts[].smtp.*` | 否 | 预留字段，本链路不使用 |
| `mailAccounts[].auth.username` | 是 | 邮箱地址 |
| `mailAccounts[].auth.password` | 是 | **授权码**（应用专用密码）。QQ: mail.qq.com→设置→账户→IMAP/SMTP 服务；163: 设置→POP3/SMTP/IMAP；Gmail 需两步验证+应用密码。可随时在邮箱后台重置作废 |

### 4.2 ocr-config.json（技能根目录，可选，含凭据）

| 键 | 说明 |
|---|---|
| `api_key` / `secret_key` | 百度智能云应用凭据（控制台「文本识别 OCR → 增值税发票识别」创建应用获得）；个人实名每月 1000 次免费，成功失败都计数 |
| `token_url` | 固定 `https://aip.baidubce.com/oauth/2.0/token` |
| `vat_invoice_url` | 固定 `https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice` |
| `provider` / `note` | 描述性字段，不参与逻辑 |

不存在该文件（或字段为空）时 OCR 路径静默关闭，链路退化为纯文本层。
凭据查找顺序：`INVOICE_OCR_CONFIG` 环境变量 → 本技能 `ocr-config.json` →
`~/.qoderwork/skills/invoice-summary/ocr-config.json`（兼容旧位置）。

### 4.3 环境变量一览

| 变量 | 作用 | 缺省 |
|---|---|---|
| `INVOICE_WORKDIR` | 数据目录（invoices/ outputs/ manual_links.json） | 当前目录 |
| `MAIL_ACCOUNT` | 选择 config.yaml 中的账户 id | defaultAccount → 第一个 |
| `INVOICE_OCR_CONFIG` | 指定 OCR 凭据文件路径 | 按 4.2 顺序查找 |
| `INVOICE_CDP_URL` | 专用 Chrome CDP 地址 | http://127.0.0.1:9222 |
| `CHROME_EXE` | chrome-auto-start 的浏览器可执行文件 | 自动探测 |
| `PYTHONIOENCODING` | Windows 下须 `utf-8` | — |

## 5. 平台规则与扩展

- `SPA_HOSTS`（mail-download-browser.js）：决定哪些 manual 链接走浏览器。新平台在此加域名。
- 点击选择器三连（同文件 `captureDownloadUrl`）：新平台按「按钮文字精确 → 模糊 → 泛化」追加。
- `HOMEJUNK` / `TRACKING`（mail-download-links.js）：过滤无效链接的正则；某平台首页/登录墙
  链接混入候选时在此加规则。
- `resolveInterstitial`：中间页模式库，现有 51fapiao 与 meta refresh 两种；新中间页按同构
  思路追加解析分支。
- 接入新平台的安全底线：只打开邮件正文里出现过的 https 链接；不提交凭据、不模拟登录；
  拿不到就退回 MANUAL 列 URL 给人工。

## 6. 安全说明

- 凭据仅存于技能根目录 config.yaml / ocr-config.json，脚本不打日志；授权码与百度 Key 均可
  在各自控制台随时作废重建。**分发技能包（.skill/zip）前必须删除这两个文件、node_modules、
  chrome-auto/、以及任何 invoices/ 真实票据。**
- 浏览器阶段使用隔离 profile，不携带主浏览器登录态；只打开本身公开的发票分享页。
- TLS 降级仅限单次请求且输出留痕；不全局关闭证书校验（除非外部显式设置
  `NODE_TLS_REJECT_UNAUTHORIZED=0`，勿主动这么做）。
