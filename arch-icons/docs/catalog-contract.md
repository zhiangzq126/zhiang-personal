# 索引与入库约定

## 产品、变体、资产

`catalog/index.json` 为数据入口，`schema_version: 1`。

- 产品条目 `products[]`：稳定 `id`（如 `aliyun/ecs`）、`provider`、展示 `name`、`category`、语义 `kind`、中英文 `aliases`、`status`、`identity_basis`、`notes`、`default_variant`。
- 图标变体 `variants[]`：稳定 `id`、所属 `product_id`、`style`、可用 `status`、`asset`、完整 `origins[]`、默认排序 `priority`、`theme` 和 `optical_scale`。
- `asset`：`path`、`sha256`、`format: svg`、`representation: vector`、`bytes`、`viewBox`。相同规范化文件可以跨语义条目复用同一个 path。
- 来源 `origins[]`：项目内原始文件 `path`、原始 `entry` 和转换前图标字节 `original_sha256`。对于 DrawIO 库，path 指向原始库，entry 指明库中位置与名称。
- `catalog/sources.json`：原始输入位置与所有归档文件的 SHA-256、大小。原始库不作就地修改。
- `catalog/preferences.json`：用户选择覆盖默认值，`defaults` 是产品 ID 到变体 ID 的映射。查看和自动引用使用同一份配置。

SVG 中的固定宽高统一为 64，保留原始 viewBox 与比例。展示端默认以 56 px 图标框呈现；当前没有自动裁剪路径留白，以避免裁掉轮廓。`optical_scale` 为后续逐项光学校准保留，现阶段为 1.0。

## 状态与身份

- `ready`：根据已审阅来源完成本地身份归类且资产可用，可以按明确身份自动选择。
- `pending`：技术上可预览，但语义身份或变体归属需确认；默认查询不显示，解析不返回可引用资产。

此状态不是官方认证、品牌最新版或授权声明。语义种类包含 product、brand、component、container-symbol、status。边界标识不得替代图表中 VPC/可用区等包含关系。

## SVG 规范化

保留原始颜色、路径、描边、透明度、比例。移除无用导出标记、空样式与元信息；丢弃无内部子集的标准外部 DTD 声明，不加载 DTD。校验并重命名内部 ID 引用，避免图标内联时 ID 冲突。

活跃脚本、事件属性、外链、内嵌图片、foreignObject、非空样式表或其他尚未支持的特性，不作为可用素材静默导入。原件仍保留，导入报告给出原因。只支持明确可处理的 SVG 子集，而非任意 SVG 渲染器。

## 去重

1. 原始输入保持不变。
2. 规范化后字节一致的资产，只保留一个内容寻址文件。
3. 同一产品、同一 style、同一规范化资产的变体合并来源记录。KMS 的两处原始出处已如此保留。
4. 同产品不同颜色/样式保留为变体；不同产品即使共用图形也保留独立身份。
5. 不依据感知相似度或同名自动合并产品。视觉近似候选需要人工确认。

## 查询约定

Agent/技能调用的版本、命令、返回状态、临时变体选择和消费要求统一维护在 [agent-contract.md](agent-contract.md)；本文负责索引与入库模型。

`search` 用于发现候选；`resolve` 用于确定引用。精确 ID 最可靠。名称与别名有歧义时返回候选；模糊搜索命中不能直接升级为唯一产品身份。尚未建立的别名可以补充，不应靠删除候选来制造唯一命中。

`resolve.status == resolved` 才可使用返回的 `asset_path`。其余状态一律给出 card 回退。未注明厂商的组件优先匹配独立条目；没有独立条目时可按 `catalog/component-mappings.json` 复用指定阿里云 SVG，并明确返回来源和组件展示名，不改变部署语义。

普通使用不读取 sources，也不遍历 assets 猜测产品。只读取本次选中的 SVG；生成的图表应该内嵌素材，不依赖本项目的本地绝对路径。

数据结构检查由无依赖的校验器执行，覆盖本项目 schema 使用的有限 JSON Schema 关键字；它不是通用 JSON Schema 引擎。扩展 schema 使用尚未支持的关键字时会显式失败，需同步扩展校验器。
