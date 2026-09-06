from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a backup archive without mutating production")
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    root = args.backup.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("manifest.json 不存在")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise SystemExit("备份清单格式无效")
    missing = [name for name in files if not (root / str(name)).is_file()]
    if missing:
        raise SystemExit(f"备份文件缺失: {', '.join(missing)}")
    print(json.dumps({"status": "READY", "backup": str(root), "files": files}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
