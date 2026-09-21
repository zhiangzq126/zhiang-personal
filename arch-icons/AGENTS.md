# Working with this icon library

- For Agent/skill consumption, read `docs/agent-contract.md`. The portable entry skill is `skills/arch-icons/SKILL.md`; response schemas and the read-only consumer example are linked from the contract.

- Start with `python3 scripts/iconlib.py search "<product>" --json` and `resolve`; do not infer product identity from filenames or visual resemblance.
- `resolve` selects only ready products and ready vector variants. If ambiguous or pending, report that status and let the diagram use its card fallback. Unqualified components resolve to independent entries first, then explicitly mapped Alibaba Cloud SVGs when no independent entry exists. Preserve display_name/requested_component; source provider does not imply deployment provider. Report diagnostic reasons instead of saying every fallback means no icon.
- Use the returned `asset_path` under assets/. Do not use sources/ during ordinary drawing. Keep product labels and diagram semantics independent from icon appearance.
- Preserve originals under sources/ and their provenance. Do not delete variants based only on title or visual similarity. Exact normalized files may share an asset; semantic products remain separate.
- User preferences live in catalog/preferences.json and apply to both CLI and the local viewer. Use `prefer` or the viewer's local API to change them. Do not modify generated previews/data.js directly.
- For future imports: `iconlib.py import <file-or-directory> --provider <provider> --source-name <name>`. New independent SVGs or mxlibrary SVGs enter pending review unless mapped explicitly. PNG is archived but does not enter assets/ as fake vector.
- After edits, run `python3 scripts/iconlib.py validate` and appropriate tests. `python3 scripts/build_preview.py` rebuilds static viewer data. No network or global installation is needed for daily use.
- Keep drawing renderer integration separate from this library. The shared arch-icons entry skill can be installed independently; archify and ai-drawio have not been adapted yet.

- Existing pending items can be reviewed in the browser via “待确认审核”. Review only explicitly selected pending variants; a ready product can still have pending variants. Use `review_queue` to find all review work. Preserve origins and existing target defaults during association. Browser decisions are recorded in reports/web-reviews/ with before-state and ID mappings.

- Browser review action `delete` requires explicit selection of pending variants, a reason and confirmation of the impact plan. Remove only those variants and unused product entries. Recycle only now-unreferenced assets under trash/review-deletions/; preserve shared assets and original source archives. Never bulk-delete source libraries as part of this action.
