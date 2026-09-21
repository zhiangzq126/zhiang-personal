#!/usr/bin/env python3
"""Read-only consumer example: resolve, verify bytes, return an embedding payload."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def consume(root, query, provider=None, variant=None, node_id="example-node"):
    root = Path(root).expanduser().resolve()
    sys.path.insert(0, str(root / "scripts"))
    from library import check_schema

    args = [sys.executable, str(root / "scripts/iconlib.py"), "resolve", query, "--json"]
    if provider:
        args += ["--provider", provider]
    if variant:
        args += ["--variant", variant]
    process = subprocess.run(args, env={**os.environ, "ARCH_ICONS_ROOT": str(root)},
                             capture_output=True, text=True, timeout=30)
    # CLI argument errors and failures before command dispatch may have no JSON.
    result = json.loads(process.stdout)
    if result.get("contract_version") != 2:
        raise ValueError("Unsupported icon contract version")
    schema = json.loads((root / "docs/schemas/agent-response.schema.json").read_text())
    errors = check_schema(result, schema)
    if errors:
        raise ValueError("Invalid response: " + "; ".join(errors))
    if process.returncode == 2 and result.get("fallback") == "card":
        return 2, result
    if process.returncode != 0 or result.get("status") != "resolved":
        raise ValueError(result.get("error", "Unexpected resolve result/exit code"))

    relative = Path(result["asset_relative_path"])
    path = (root / relative).resolve()
    if not path.is_relative_to((root / "assets").resolve()):
        raise ValueError("Asset is outside assets")
    if Path(result["asset_path"]).resolve() != path:
        raise ValueError("Asset paths disagree")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != result["sha256"]:
        raise ValueError("Asset changed after resolution")
    record = {key: result[key] for key in
              ("product_id", "variant_id", "sha256", "asset_relative_path", "selection", "display_name", "match_type")}
    if "requested_component" in result:
        record["requested_component"] = result["requested_component"]
    lock = {"contract_version": 2, "icons": [{"node_id": node_id, **record}]}
    # This is a consumer payload, not an archify spec or a DrawIO XML style.
    return 0, {"status": "resolved", "resolved": result, "icons_lock": lock,
               "svg_data_uri": "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--provider")
    parser.add_argument("--variant")
    parser.add_argument("--node-id", default="example-node")
    parser.add_argument("--root", default=os.environ.get("ARCH_ICONS_ROOT") or os.environ.get("ICON_PERSONAL_ROOT") or str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    try:
        code, payload = consume(args.root, args.query, args.provider, args.variant, args.node_id)
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as error:
        code, payload = 1, {"error": str(error), "fallback": "card"}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
