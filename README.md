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

## 许可

各项目独立声明许可，见 [LICENSES.md](LICENSES.md)。Arch Icons 原创工具代码采用 MIT；第三方图标、商标与上游材料不因代码许可证而获得额外授权。
