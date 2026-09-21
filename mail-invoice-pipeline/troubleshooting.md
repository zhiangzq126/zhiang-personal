# mail-invoice-pipeline 排障与踩坑速查

## 常见报错速查

| 现象 | 原因 | 解法 |
|---|---|---|
| npm 安装报 ENOTFOUND / "Exit handler never called" | package-lock.json 里写死了不可达的镜像 | 删掉 lock 文件重装：`npm install --registry=https://registry.npmmirror.com` |
| pip 解析 requirements.txt 报 `UnicodeDecodeError: 'gbk'` | 中文 Windows 上 requirements.txt 含非 ASCII 注释 | requirements.txt 保持纯 ASCII（本技能已如此） |
| Python 打印报 `UnicodeEncodeError` | GBK 控制台打不出 ¥/部分中文 | 命令前加 `PYTHONIOENCODING=utf-8` |
| IMAP 登录失败 / "Mails not exist" | 授权码错，或 fetch 没带 `{uid:true}` 把 UID 当序列号 | 邮箱后台重新生成授权码；本技能脚本已正确使用 UID |
| 收件箱搜不到发票邮件 | QQ 把发票邮件自动归到「其他文件夹/发票」 | 无需处理：脚本默认读 config.invoiceFolder，失败自动发现含"发票"的文件夹，再退 INBOX |
| 正文链接取回乱码/失效（`Jymt98`、`Fphm%31...`） | 对 imapflow `download()` 的结果再次解码 QP/base64（二次解码） | 本技能已修复：正文只做 utf-8→gb18030 字符集判断，勿再解传输编码 |
| `resp.body.on is not a function` | undici 的 body 是 Web Stream 不是 Node Stream | 用 `await resp.arrayBuffer()` 后写盘 |
| 下载文件名乱码 `ä¸æµ·...` | 平台把裸 UTF-8 字节塞进 Content-Disposition | 脚本内 `fixMojibake`：按 latin1 取回字节再 toString('utf8') |
| 同一张票重复入表 | 税务平台每次下载重新生成 PDF（内嵌时间戳），哈希去重失效 | invoice_summary_build.py 按**发票号码**二次去重 |
| 51 发票链接 GET 回来是 HTML | 分享页是中间页，真实文件要签名二次请求 | 已内置：解析隐藏 `signatureString`/`dlj` → `/dlj/v7/downloadFile/` |
| 诺诺/百望按钮点了没反应/抓不到 URL | SPA 的下载是点击时 `window.open` 触发，CDP 下载行为钩不到 | 已内置：`evaluateOnNewDocument` 钩 `window.open` 收集 URL |
| 诺诺/百望下载 URL 探测 405/403 | 用了 HEAD 请求 | 用 GET（200，无需 cookie） |
| puppeteer 报 `fn is not a function` | `page.evaluate` 的 args 里塞了函数 | 点击选择器函数要作为 pageFunction 本体传入 |
| `连不上 CDP（http://127.0.0.1:9222）` | 专用 Chrome 没启动 | 先跑 chrome-auto-start.ps1 / chrome-auto-start.sh |
| OCR 报 `error_code=282103` | 图片不是增值税发票票面（模板不匹配） | 预期行为：该文件进 REVIEW 列表供人工 |
| OCR 报 `216202 image size error` | 图片 base64 超 4MB | 已内置：160dpi + JPEG q90 + 长边 2600px |
| OCR 中文乱码 `??` | 百度响应头无 charset，默认解码错 | 必须 `resp.content.decode('utf-8')`（脚本已如此） |
| 汇总表字段缺 销售方/号码 | 扫描件无文本层且 OCR 未配置/失败 | 配置 ocr-config.json 后重跑；仍不行进 REVIEW |
| Windows 下脚本路径报 ENOENT 且路径反斜杠丢失 | heredoc/JSON 转义吃了反斜杠 | 脚本与命令中一律用正斜杠路径 |
| Git Bash 里 `/开关` 被解析成路径 | MSYS 路径转换 | `MSYS_NO_PATHCONV=1` 前缀，或改用 PowerShell |

## 平台实测矩阵（2026-08-12，QQ 邮箱真实票）

| 平台/发件域名 | 链接形态 | 处理方式 |
|---|---|---|
| 51 发票 `dlj.51fapiao.cn/dlj/v7/...` | 中间页+签名二次请求 | links 脚本中间页解析 |
| 税务数字账户 `dppt.*.chinatax.gov.cn:8443` | 直链 PDF（URL 含校验参数，证书链偶异常） | links 脚本直链 + 单次 TLS 降级留痕 |
| 萨莉亚/开票百云 `rocgw.jcsk100.com` | 直链 PDF（同页另有 _ofd/_xml） | links 脚本直链 |
| 达美乐 `images.wosaimg.com`、拼多多 `files.pdd-fapiao.com` | 直链 PDF | links 脚本直链 |
| 百望 `www.fapiao.com/DownLoad/...` | 直链 PDF | links 脚本直链 |
| 诺诺 `nnfp.jss.com.cn`、百望 `bwfp.baiwang.com` 短链 | 纯前端 SPA，点下载才发签名 URL | browser 脚本（window.open 捕获） |
| 浦发账单 `ebill.spdbccc.com.cn` | 登录墙（且非发票） | 直接过滤，不探测 |

未实测但已列规则：`yun.ekaikai.cn`（易开票）。新平台接入步骤见 reference.md 第 5 节。

## 回滚与停用

- 停 OCR：删除技能根 `ocr-config.json`（链路自动退回纯文本层）。
- 停浏览器阶段：关专用 Chrome 窗口即可；彻底回退删 `chrome-auto/` 目录，SPA 票退回人工。
- 换邮箱：改 `config.yaml`；授权码随时可在邮箱后台重置作废。
- 数据目录的票如需剔除：按文件名移走即可，号码去重保证不会半残入账。
