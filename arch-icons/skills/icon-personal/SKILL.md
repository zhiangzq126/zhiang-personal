---
name: icon-personal
description: 兼容旧名称 icon-personal 的图标查询入口。现项目和技能已更名为 arch-icons，收到旧技能名称或旧调用路径时转到 arch-icons 规范执行。
---

# icon-personal 兼容入口

项目与公共技能已更名为 **Arch Icons / arch-icons**。

读取相邻的 [arch-icons 技能](../arch-icons/SKILL.md)，按照该技能及图标库 `docs/agent-contract.md` 执行。
旧命令 `scripts/icon_query.py` 仍指向同一实现。优先使用 `ARCH_ICONS_ROOT`，兼容 `ICON_PERSONAL_ROOT`；两者同时设置时新变量优先。不要维护第二份图标或选择规则。
