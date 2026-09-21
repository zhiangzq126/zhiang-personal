# Arch Icons

**English** | [简体中文](readme-zh.md)

An SVG icon management tool for architecture diagrams, supporting assets from multiple vendors, visual browsing and import review, shared icon preferences, and a deterministic query interface for Agents.

## Quick Start

Requires Python 3.9+; no third-party Python packages are needed for everyday use.

```bash
git clone https://github.com/zhiangzq126/zhiang-personal.git
cd zhiang-personal/arch-icons
python3 scripts/iconlib.py serve --open
```

The service listens only on the local address `127.0.0.1` and prints its actual URL in the terminal; press Ctrl+C to stop it. On macOS, you can also double-click `打开图标库.command` (Open Icon Library). Open `previews/index.html` directly for offline browsing and downloads; importing, reviewing, and saving preferences require the local service. Run CLI commands copied from the offline page in this project's root directory.

## Included in This Release

The complete active index contains **1,969 semantic entries, 2,414 variants, and 2,404 unique SVGs**, covering Alibaba Cloud, AWS, Tencent Cloud, Huawei Cloud, and open-source/general-purpose components. These counts include products, resources, brands, and generic symbols, and do not represent the number of distinct cloud products.

Original sources are traceable, and items pending review retain their status and are not selected automatically. See [Third-Party Notices](THIRD_PARTY_NOTICES.md) for asset sources and licensing details, and the [manifest](catalog/release-manifest.json) for the release scope.

## Agent Queries

```bash
python3 scripts/iconlib.py search "对象存储" --json
python3 scripts/iconlib.py resolve "MySQL" --json
python3 scripts/iconlib.py resolve "ES" --json
python3 scripts/iconlib.py show "aliyun/ecs" --json
```

The CLI contract version is 2. `search` discovers candidates, while `resolve` selects the final asset; use an SVG only when the exit code is 0 and `status: resolved`. Cases such as no available asset, vendor-only variants, ambiguity, or pending review return their respective reasons and `fallback: card`. Asset availability depends on the entries actually included and reviewed in the current catalog.

When no vendor is specified, independent components take priority. If no independent component exists, an Alibaba Cloud SVG may be reused through an explicitly configured association in `catalog/component-mappings.json`. Use `display_name` or the user's original label; do not treat the asset's source vendor as the deployment vendor. An explicit vendor or exact product ID takes precedence over this reuse rule.

Variants are selected in this order: `--variant` for the current invocation, shared personal preferences, then the index default. A temporary selection does not modify global preferences.

```bash
python3 scripts/iconlib.py resolve <product-id> --variant <variant-id> --json
python3 scripts/iconlib.py prefer <product-id> <variant-id>
python3 scripts/iconlib.py prefer <product-id> --reset
```

See the [Agent contract](docs/agent-contract.md), [response schema](docs/schemas/agent-response.schema.json), and [SVG consumption example](examples/agent/consume_icon.py) for the full interface. Generated diagrams should embed SVGs rather than depend on paths or services on the original machine.

## Skill Integration

The shared skill is in [skills/arch-icons](skills/arch-icons/SKILL.md). Add it to your Agent's skill directory and set:

```bash
export ARCH_ICONS_ROOT="/absolute/path/to/zhiang-personal/arch-icons"
```

If this variable is not set, the skill within the project automatically locates the root directory. `ICON_PERSONAL_ROOT` and the old skill name `icon-personal` remain compatibility entry points; the new variable takes precedence. Ordinary diagram generation accesses the icon library in read-only mode.

This project provides asset selection and a consumption contract. Tools such as archify and ai-drawio still need their own adaptations for layout, embedding, and export; installing this skill does not automatically give them new rendering capabilities.

## Import and Review

Click “导入 SVG” (Import SVG) in the browser viewer to enter names, vendors, aliases, and sources in bulk. The system checks for identical SVGs and name conflicts; you can associate an asset with an existing product, keep it as a separate entry, or skip it. Defaults change only when explicitly selected.

Click “待确认审核” (Review Pending Items) to review assets in one place, edit metadata, enable selected variants, or move incorrect variants to the recycle bin. Original assets and source records are preserved, and cleanup does not remove SVGs shared by other entries.

The command line also supports standalone SVGs and DrawIO mxlibrary files containing embedded SVGs:

```bash
python3 scripts/iconlib.py import /path/to/icons --provider example --source-name my-pack --json
python3 scripts/iconlib.py search "name" --include-pending --json
python3 scripts/iconlib.py review <product-id> --status ready --name "Verified name" --note "Identity verified"
```

CLI `review` applies to an entire product and its variants; use the browser viewer for item-by-item review. Raster images can be archived, but are not wrapped in SVG to pass them off as vectors. Import only assets you have the right to use; a `ready` review status means the identity has been confirmed locally, not that the asset is the latest official version or that its authorization has been certified.

## Directory Structure

- `assets/`: SVGs stored by SHA-256; the asset source for everyday consumption.
- `catalog/`: Products, variants, aliases, component mappings, preferences, and data schemas.
- `sources/`: Original assets and source evidence; do not modify or delete them arbitrarily.
- `scripts/`: Queries, import and review, the local service, and preview building.
- `previews/`: The static browser viewer.
- `skills/`: The current skill and the compatibility entry point under its old name.
- `docs/`, `examples/`, `tests/`: Integration specifications, usage examples, and validation.

The release copy does not include the maintainer's personal preferences, old recycle-bin contents, historical reports, or one-off local initialization scripts. Runtime-generated reports/trash are ignored by Git.

## Validation and Development

```bash
python3 scripts/iconlib.py validate --json
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/build_preview.py
```

Optional browser tests use Playwright. Set `PLAYWRIGHT_MODULE` to its module path, `CHROME_PATH` to a local browser path if desired, and `ICON_PREVIEW_URL` to the running service URL. When no browser path is provided, Playwright's Chromium is used.

## License

Original tool code, tests, skill instructions, and original documentation are licensed under [MIT](LICENSE). Third-party icons, upstream assets, and trademarks are not covered by this project's MIT license; asset copies and embedded data remain subject to their original licenses. See [Third-Party Notices](THIRD_PARTY_NOTICES.md).
