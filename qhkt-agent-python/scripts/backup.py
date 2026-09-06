from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings


def _mysql_backup(settings: Settings, target: Path) -> None:
    if settings.database_url.startswith("sqlite"):
        source = Path(settings.database_url.rsplit("///", 1)[-1])
        if source.exists():
            target.write_bytes(source.read_bytes())
        return
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url)
    command = ["mysqldump", "--single-transaction", "--routines", "--triggers", "-h", str(url.host or "localhost"), "-P", str(url.port or 3306), "-u", str(url.username or ""), str(url.database or "")]
    env = os.environ.copy()
    if url.password:
        env["MYSQL_PWD"] = url.password
    with target.open("wb") as output:
        subprocess.run(command, check=True, env=env, stdout=output)


def _qdrant_snapshot(settings: Settings, target: Path) -> None:
    if not settings.qdrant_enabled:
        return
    base = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}/snapshots"
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    request = urllib.request.Request(base, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            target.write_bytes(response.read())
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError("Qdrant 快照元数据获取失败") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up Agent relational and vector metadata")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    settings = Settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or ROOT / "backups" / stamp
    output.mkdir(parents=True, exist_ok=False)
    _mysql_backup(settings, output / ("agent.sqlite3" if settings.database_url.startswith("sqlite") else "agent.sql"))
    _qdrant_snapshot(settings, output / "qdrant-snapshots.json")
    (output / "manifest.json").write_text(json.dumps({"createdAt": stamp, "collection": settings.qdrant_collection, "files": sorted(item.name for item in output.iterdir())}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
