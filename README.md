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

## 许可

各项目独立声明许可，见 [LICENSES.md](LICENSES.md)。Arch Icons 原创工具代码采用 MIT；第三方图标、商标与上游材料不因代码许可证而获得额外授权。
