from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.development_reset import (
    build_development_reset_manifest,
    execute_development_reset,
    load_development_reset_manifest,
    write_development_reset_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or execute the New Core full development reset."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".tmp/codex/new_core_development_reset.json"),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--reset-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.project_root.resolve()
    manifest_path = (
        args.manifest
        if args.manifest.is_absolute()
        else (root / args.manifest).resolve()
    )
    if args.preview:
        manifest = build_development_reset_manifest(
            root, generated_at=datetime.now().astimezone()
        )
        write_development_reset_manifest(manifest, manifest_path)
        print(f"RESET_ID={manifest.reset_id}")
        print(f"DELETE_COUNT={len(manifest.delete)}")
        for item in manifest.delete:
            print(f"DELETE {item.classification} {item.path}")
        return 0

    if not args.reset_id:
        raise SystemExit("--apply requires --reset-id from the matching preview")
    manifest = load_development_reset_manifest(manifest_path)
    if args.reset_id != manifest.reset_id:
        raise SystemExit("--reset-id does not match the reviewed manifest")
    deleted = execute_development_reset(root, manifest)
    print(f"RESET_ID={manifest.reset_id}")
    print(f"DELETED_COUNT={len(deleted)}")
    print("NEW_CORE_STORAGE_INITIALIZED=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
