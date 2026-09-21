# Arch Icons

[English](README.md) | **简体中文**

面向架构图的 SVG 图标管理工具，支持多厂商素材、可视化浏览与导入审核、共享图标偏好，以及供 Agent 使用的确定性查询接口。

## 快速开始

需要 Python 3.9+；日常运行不需要第三方 Python 包。

```bash
git clone https://github.com/zhiangzq126/zhiang-personal.git
cd zhiang-personal/arch-icons
python3 scripts/iconlib.py serve --open
```

服务仅监听本机 `127.0.0.1`，终端会打印实际地址；Ctrl+C 停止。macOS 也可双击 `打开图标库.command`。直接打开 `previews/index.html` 可以离线浏览和下载；导入、审核与保存偏好需要本地服务。离线页复制的 CLI 命令应在本项目根目录执行。

## 本次发布收录

包含完整的活动索引：**1,969 个语义条目、2,414 个变体、2,404 份唯一 SVG**，覆盖阿里云、AWS、腾讯云、华为云及开源/通用组件。数量包括产品、资源、品牌和通用符号，不等于独立云产品数量。

原始来源可追溯，待审核项保留其状态且不会自动选择。素材来源与许可说明见 [第三方声明](THIRD_PARTY_NOTICES.md)，发布范围见 [清单](catalog/release-manifest.json)。

## Agent 查询

```bash
python3 scripts/iconlib.py search "对象存储" --json
python3 scripts/iconlib.py resolve "MySQL" --json
python3 scripts/iconlib.py resolve "ES" --json
python3 scripts/iconlib.py show "aliyun/ecs" --json
```

CLI 契约版本为 2。`search` 发现候选，`resolve` 决定最终素材；只有退出码 0 且 `status: resolved` 时可使用 SVG。没有素材、只有厂商版本、歧义、待审核等情况分别返回原因和 `fallback: card`。素材是否可用取决于当前目录中实际收录和审核的条目。

未注明厂商时优先独立组件；独立组件不存在时，可依据 `catalog/component-mappings.json` 明确配置的关联复用阿里云 SVG。使用 `display_name` 或用户原标签，不能把素材来源厂商当作部署厂商。显式厂商或精确产品 ID 优先于该复用规则。

变体选择顺序为本次 `--variant`、共享个人偏好、索引默认值。临时选择不修改全局偏好。

```bash
python3 scripts/iconlib.py resolve <product-id> --variant <variant-id> --json
python3 scripts/iconlib.py prefer <product-id> <variant-id>
python3 scripts/iconlib.py prefer <product-id> --reset
```

完整接口见 [调用规范](docs/agent-contract.md)、[响应 schema](docs/schemas/agent-response.schema.json)、[SVG 消费示例](examples/agent/consume_icon.py)。生成的图表应嵌入 SVG，不依赖原机器的路径或服务。

## 技能接入

公共技能在 [skills/arch-icons](skills/arch-icons/SKILL.md)。将其加入 Agent 的技能目录，并设置：

```bash
export ARCH_ICONS_ROOT="/absolute/path/to/zhiang-personal/arch-icons"
```

未设置时，项目内技能会自动定位根目录。`ICON_PERSONAL_ROOT` 和旧技能名 `icon-personal` 为兼容入口，新变量优先。普通绘图只读图标库。

本项目提供素材选择和消费契约；archify、ai-drawio 等工具仍需各自适配布局、嵌入和导出，不会因为安装本技能而自动获得新的渲染能力。

## 导入与审核

在浏览页点击“导入 SVG”，可批量填写名称、厂商、别名和来源。系统检查完全相同的 SVG 以及名称冲突，可关联已有产品、保留独立条目或跳过。默认值只在明确选择时修改。

点击“待确认审核”可集中查看素材、修改元信息、启用选定变体或将有误变体移入回收站。原始素材及来源记录保留，清理不会移除被其他条目共用的 SVG。

命令行也支持独立 SVG 和含内嵌 SVG 的 DrawIO mxlibrary：

```bash
python3 scripts/iconlib.py import /path/to/icons --provider example --source-name my-pack --json
python3 scripts/iconlib.py search "name" --include-pending --json
python3 scripts/iconlib.py review <product-id> --status ready --name "Verified name" --note "Identity verified"
```

CLI `review` 面向整个产品及其变体；逐项审核使用浏览页。位图可归档，但不会包装成 SVG 冒充矢量。仅导入有权使用的素材；审核 ready 代表本地身份确认，不代表官方最新版本或授权认证。

## 目录

- `assets/`：按 SHA-256 存储的 SVG；日常消费的素材出口。
- `catalog/`：产品、变体、别名、组件映射、偏好与数据 schema。
- `sources/`：素材原件及来源证据；不能随意修改或删除。
- `scripts/`：查询、导入审核、本地服务和预览构建。
- `previews/`：静态浏览页。
- `skills/`：当前技能与旧名称兼容入口。
- `docs/`、`examples/`、`tests/`：接入规范、调用示例及验证。

发布副本不包含维护者个人偏好、旧回收站、历史报告或一次性的本机初始化脚本。运行产生的 reports/trash 由 Git 忽略。

## 验证与开发

```bash
python3 scripts/iconlib.py validate --json
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/build_preview.py
```

可选浏览器测试使用 Playwright。通过 `PLAYWRIGHT_MODULE` 指定其模块路径，`CHROME_PATH` 可指定本机浏览器，`ICON_PREVIEW_URL` 指定运行中的服务地址；未提供浏览器路径时使用 Playwright 的 Chromium。

## 许可

原创工具代码、测试、技能说明及原创文档采用 [MIT](LICENSE)。第三方图标、上游素材和商标不受本项目 MIT 授权覆盖；素材副本及嵌入数据同样遵循原许可。见 [第三方声明](THIRD_PARTY_NOTICES.md)。
