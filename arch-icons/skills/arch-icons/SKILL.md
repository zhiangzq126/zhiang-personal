---
name: arch-icons
description: 为架构图、流程图和技术文档查询个人图标库，按产品身份、审核状态和个人偏好选取可用 SVG。需要产品或组件图标、指定图标变体，或为绘图技能接入共享图标时使用。
---

# Personal icon lookup

本技能选择图标并提供 SVG，绘图和导出由调用方完成。普通绘图使用只读入口，不修改图标库或全局偏好。

## 定位与调用

`SKILL_DIR` 表示本 SKILL.md 所在目录。运行 `python3 "$SKILL_DIR/scripts/icon_query.py" ...`，支持 `search`、`resolve`、`show`，参数与图标库 CLI 相同。

- 设置了 `ARCH_ICONS_ROOT` 时使用指定图标库。
- 兼容旧环境变量 `ICON_PERSONAL_ROOT`，新变量优先。旧技能 icon-personal 仅转到本技能，不维护独立数据或规则。
- 技能位于项目 `skills/arch-icons` 下（或通过符号链接安装）时，入口自动找到项目根目录。
- 单独复制技能到其他 Agent 后，需要配置 `ARCH_ICONS_ROOT`。不要搜索整个用户目录猜测位置。未配置或不可访问时说明原因并使用卡片。

接入或处理返回字段前，读取图标库的 `docs/agent-contract.md`；返回结构在 `docs/schemas/agent-response.schema.json`，运行示例在 `examples/agent/consume_icon.py`。这些资源由共享库维护，无需复制到每个绘图技能。

```bash
python3 "$SKILL_DIR/scripts/icon_query.py" search "对象存储" --provider tencent --json
python3 "$SKILL_DIR/scripts/icon_query.py" resolve "tencent/cos" --json
python3 "$SKILL_DIR/scripts/icon_query.py" show "tencent/cos" --json
```

## 选择与交付

- `search` 只发现候选；依据产品 ID、厂商和上下文确定身份后调用 `resolve`。不从文件名、外观或搜索排名推断身份，未注明厂商时让 resolver 优先选择独立组件，缺少独立组件时按明确映射复用阿里云 SVG；保留组件名称，不把节点表述成阿里云服务。此时传原组件名，不要自行把厂商候选 ID 当作用户选择。
- 本次明确指定的变体使用 `resolve <product-id> --variant <variant-id>`，不会保存偏好。其他情况由 resolver 应用共享偏好和默认值。
- 只有退出码 0、`contract_version: 2` 且 `status: resolved` 才能使用素材。其他状态按规范回退，待审核素材不可绕过 resolver 使用。
- 使用 `display_name` 或保留用户标签；`product_id/name/provider` 表示素材来源。`match_type: vendor_svg_reuse` 时说明借用阿里云 SVG，不推断部署厂商。按 `diagnostic.message/action` 区分没有素材、只有厂商版本、歧义和待审核，勿统一说“没找到”。
- 读取返回的 `assets` 路径，核对 SHA-256；不读取 `sources`。保留原色和比例，产品图标建议 56px、名称在下方，按 `theme.dark_backdrop` 处理深色背景。
- 通过绘图工具支持的方式嵌入 SVG，保留节点语义与连接点；重复内联时处理实例间 ID 冲突。记录使用的产品、变体和哈希，交付文件不依赖本机路径或浏览服务。
- 本技能不代表绘图工具已接入：archify 的本地 SVG schema/渲染适配和 ai-drawio 的具体嵌入、导出适配仍需实现。不要将本技能输出直接写进不支持的字段，也不要跳过绘图技能的校验流程。
