"""Measured human-input ledger for Grand Prize submission accounting."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .package_hash import sha256_path

SCHEMA_VERSION = 1
MAX_HOURS = 8.0
STAGES = {
    "annotation",
    "segmentation",
    "geometry-review",
    "vc3d-review",
    "ink-review",
    "submission-review",
    "other",
}


class HumanTimeError(ValueError):
    """Raised when the human-input ledger is malformed or exceeds the cap."""


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanTimeError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise HumanTimeError(f"{field} is not a valid ISO-8601 timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _load(path: Path, *, create: bool = False) -> dict[str, Any]:
    if not path.exists():
        if create:
            return {"schema_version": SCHEMA_VERSION, "entries": []}
        raise HumanTimeError(f"ledger does not exist: {path}")
    if path.is_symlink() or not path.is_file():
        raise HumanTimeError(f"ledger must be a regular file: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HumanTimeError(f"cannot read ledger {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise HumanTimeError(f"ledger must be a schema_version={SCHEMA_VERSION} JSON object")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise HumanTimeError("ledger.entries must be a list")
    return document


def _validate_entry(row: Any, index: int) -> float:
    if not isinstance(row, dict):
        raise HumanTimeError(f"entry {index} must be an object")
    description = row.get("description")
    if not isinstance(description, str) or not description.strip():
        raise HumanTimeError(f"entry {index}.description must be non-empty")
    hours = row.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        raise HumanTimeError(f"entry {index}.hours must be numeric")
    hours = float(hours)
    if not math.isfinite(hours) or hours < 0:
        raise HumanTimeError(f"entry {index}.hours must be finite and non-negative")
    stage = row.get("stage")
    if stage is not None and stage not in STAGES:
        raise HumanTimeError(f"entry {index}.stage must be one of {sorted(STAGES)}")
    started = row.get("started_utc")
    ended = row.get("ended_utc")
    if started is not None or ended is not None:
        if started is None or ended is None:
            raise HumanTimeError(f"entry {index} must provide both started_utc and ended_utc")
        start_dt = _parse_utc(started, f"entry {index}.started_utc")
        end_dt = _parse_utc(ended, f"entry {index}.ended_utc")
        if end_dt < start_dt:
            raise HumanTimeError(f"entry {index}.ended_utc precedes started_utc")
        measured = (end_dt - start_dt).total_seconds() / 3600.0
        if abs(measured - hours) > 1e-9:
            raise HumanTimeError(
                f"entry {index}.hours does not match measured UTC duration "
                f"({hours:g} != {measured:g})"
            )
    return hours


def summarize(document: dict[str, Any]) -> dict[str, Any]:
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise HumanTimeError("ledger.entries must be a list")
    total = sum(_validate_entry(row, i) for i, row in enumerate(entries))
    return {
        "schema_version": SCHEMA_VERSION,
        "entry_count": len(entries),
        "total_hours": total,
        "remaining_hours": max(0.0, MAX_HOURS - total),
        "within_limit": total <= MAX_HOURS + 1e-9,
    }


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def init_ledger(path: Path) -> dict[str, Any]:
    if path.exists():
        raise HumanTimeError(f"refusing to overwrite existing ledger: {path}")
    document = {"schema_version": SCHEMA_VERSION, "entries": []}
    _atomic_write(path, document)
    return document


def add_entry(
    path: Path,
    *,
    description: str,
    hours: float | None = None,
    started_utc: str | None = None,
    ended_utc: str | None = None,
    operator: str | None = None,
    stage: str | None = None,
    artifact: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    document = _load(path, create=True)
    existing = summarize(document)

    if not isinstance(description, str) or not description.strip():
        raise HumanTimeError("description must be non-empty")
    if stage is not None and stage not in STAGES:
        raise HumanTimeError(f"stage must be one of {sorted(STAGES)}")

    if started_utc is not None or ended_utc is not None:
        if started_utc is None or ended_utc is None:
            raise HumanTimeError("both started_utc and ended_utc are required")
        start_dt = _parse_utc(started_utc, "started_utc")
        end_dt = _parse_utc(ended_utc, "ended_utc")
        if end_dt < start_dt:
            raise HumanTimeError("ended_utc precedes started_utc")
        measured = (end_dt - start_dt).total_seconds() / 3600.0
        if hours is not None and abs(float(hours) - measured) > 1e-9:
            raise HumanTimeError("supplied hours does not match measured UTC duration")
        entry_hours = measured
    else:
        if hours is None:
            raise HumanTimeError("provide hours or both started_utc and ended_utc")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            raise HumanTimeError("hours must be numeric")
        entry_hours = float(hours)
        if not math.isfinite(entry_hours) or entry_hours < 0:
            raise HumanTimeError("hours must be finite and non-negative")

    new_total = existing["total_hours"] + entry_hours
    if new_total > MAX_HOURS + 1e-9:
        raise HumanTimeError(
            f"entry would exceed {MAX_HOURS:g}-hour limit "
            f"({existing['total_hours']:g} + {entry_hours:g} = {new_total:g})"
        )

    entries = document["entries"]
    entry: dict[str, Any] = {
        "id": f"input-{len(entries) + 1:03d}",
        "description": description.strip(),
        "hours": entry_hours,
    }
    if started_utc is not None:
        entry["started_utc"] = _utc_text(_parse_utc(started_utc, "started_utc"))
        entry["ended_utc"] = _utc_text(_parse_utc(ended_utc, "ended_utc"))
    if operator is not None:
        if not operator.strip():
            raise HumanTimeError("operator must be non-empty when supplied")
        entry["operator"] = operator.strip()
    if stage is not None:
        entry["stage"] = stage
    if artifact is not None:
        root_path = (root or path.parent).resolve()
        artifact_path = artifact if artifact.is_absolute() else root_path / artifact
        artifact_path = artifact_path.resolve()
        if root_path != artifact_path and root_path not in artifact_path.parents:
            raise HumanTimeError("artifact path escapes root")
        if artifact_path.is_symlink():
            raise HumanTimeError("artifact may not be a symlink")
        try:
            digest = sha256_path(artifact_path)
        except (OSError, ValueError) as exc:
            raise HumanTimeError(f"cannot hash artifact: {exc}") from exc
        entry["artifact"] = {
            "path": artifact_path.relative_to(root_path).as_posix(),
            "sha256": digest,
        }

    entries.append(entry)
    _validate_entry(entry, len(entries) - 1)
    _atomic_write(path, document)
    return {
        "entry": entry,
        "summary": summarize(document),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create and append measured human-input receipts for the "
            "Vesuvius Challenge Grand Prize 8-hour accounting limit"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create an empty schema-v1 ledger")
    init.add_argument("--ledger", required=True)

    add = sub.add_parser("add", help="append one human-input receipt")
    add.add_argument("--ledger", required=True)
    add.add_argument("--description", required=True)
    group = add.add_mutually_exclusive_group(required=True)
    group.add_argument("--hours", type=float)
    group.add_argument("--start-utc")
    add.add_argument("--end-utc")
    add.add_argument("--operator")
    add.add_argument("--stage", choices=sorted(STAGES))
    add.add_argument("--artifact")
    add.add_argument("--root")

    summary = sub.add_parser("summary", help="validate and summarize a ledger")
    summary.add_argument("--ledger", required=True)
    summary.add_argument("--format", choices=("text", "json"), default="text")

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            document = init_ledger(Path(args.ledger))
            result: dict[str, Any] = summarize(document)
        elif args.command == "add":
            if args.start_utc is not None and args.end_utc is None:
                raise HumanTimeError("--end-utc is required with --start-utc")
            result = add_entry(
                Path(args.ledger),
                description=args.description,
                hours=args.hours,
                started_utc=args.start_utc,
                ended_utc=args.end_utc,
                operator=args.operator,
                stage=args.stage,
                artifact=Path(args.artifact) if args.artifact else None,
                root=Path(args.root) if args.root else None,
            )
        else:
            result = summarize(_load(Path(args.ledger)))
    except HumanTimeError as exc:
        parser.error(str(exc))

    if args.command == "summary" and args.format == "text":
        print(
            f"entries={result['entry_count']} total_hours={result['total_hours']:.6g} "
            f"remaining_hours={result['remaining_hours']:.6g} "
            f"within_limit={str(result['within_limit']).lower()}"
        )
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
