# zhiang-personal

个人工具与项目合集 / Personal tools and projects.

## Arch Icons

[Arch Icons](arch-icons/) 是面向架构图的 SVG 图标管理工具，提供浏览、搜索、导入、审核、偏好设置和 Agent 查询接口。

```bash
git clone https://github.com/zhiangzq126/zhiang-personal.git
cd zhiang-personal/arch-icons
python3 scripts/iconlib.py serve --open
```

Python 3.9+，日常使用无需额外 Python 包。详细说明见 [项目文档](arch-icons/README.md)，Agent 接入见 [统一调用规范](arch-icons/docs/agent-contract.md)。

## RedisShake Migration

[RedisShake Migration](redis-shake-migration/) 是一个端到端管理 RedisShake 数据迁移任务的 Agent 技能：从 Excel 表格、文本描述或逐项问答中提取迁移信息，生成 `shake.toml` 配置，并在本地或通过 SSH 远程部署、启动、停止、监控迁移任务。

适用于 Redis 迁移/同步任务的配置与运维；不涉及 MongoDB/MySQL/ES 等非 Redis 迁移，也不做迁移后数据一致性校验（建议配合 redis-full-check）。需在已部署 redis-shake 二进制的 Linux 服务器上运行，Agent 端需支持 Bash/Shell 工具。

详细说明见 [SKILL.md](redis-shake-migration/SKILL.md)。

## Mail Invoice Collector

[Mail Invoice Collector](mail-invoice-collector/) 是从邮箱自动收集报销发票并汇总到 Excel 的 Agent 技能（纯 Python）：扫描 IMAP 指定文件夹，下载 PDF 附件票与正文链接票（含诺诺/百望 SPA、51 发票中间页、税局直下链接），解析发票号/金额/购销方/日期，按发票号去重后增量追加进一张汇总表。全流程一条命令，OCR 兜底可选。

使用前将 `.env.example`、`config.example.yaml` 复制为本地 `.env` / `config.yaml` 并填入邮箱授权码（不会被提交）。详细说明见 [SKILL.md](mail-invoice-collector/SKILL.md)。

## Mail Invoice Pipeline

[Mail Invoice Pipeline](mail-invoice-pipeline/) 是邮箱取票的端到端链路（Node.js + Python）：下载邮件附件票、提取并下载正文链接票（含 51 发票中间页解析）、用浏览器自动化下载诺诺/百望等 SPA 开票平台发票、扫描件走百度 OCR 兜底，字段校验与号码去重后输出报销汇总表 xlsx。功能更全，分步脚本执行。

使用前将 `config.example.yaml`、`ocr-config.example.json` 复制为本地 `config.yaml` / `ocr-config.json` 并填入凭据（已在 `.gitignore` 中，不会被提交）；OCR 不配置则自动关闭。详细说明见 [SKILL.md](mail-invoice-pipeline/SKILL.md)。

## 许可

各项目独立声明许可，见 [LICENSES.md](LICENSES.md)。Arch Icons 原创工具代码采用 MIT；第三方图标、商标与上游材料不因代码许可证而获得额外授权。
