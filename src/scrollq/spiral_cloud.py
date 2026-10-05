"""Cloud execution guard rails for the frozen PHerc0826 Spiral baseline.

This module does not fit, export, or evaluate geometry. It makes the one paid
GPU run harder to waste:

* ``check``      -- validate the frozen cloud execution manifest against the
                    frozen recipe and the committed bootstrap scripts;
* ``plan``       -- turn the manifest plus launch-time identities (project,
                    zone, exact image, scrollq commit, evidence bucket) into
                    exact ``gcloud`` argv lists, without executing anything;
* ``disk-floor`` -- fail when free space on the data disk drops below a floor;
* ``gpu-gate``   -- record GPU/driver identity and prove torch CUDA, Triton,
                    the compiled ``vc_spiral`` extension and villa's own CUDA
                    startup check work before any large input is used;
* ``fetch-lasagna`` -- stage the exact Lasagna group directly from the public
                    bucket, verify every object, and rename the stores to the
                    conventional villa input names;
* ``smoke-recipe`` / ``smoke-verdict`` -- derive a short, non-promotional run
                    of the same frozen recipe and decide from its receipt
                    whether the untouched 30k run can fit in the time budget;
* ``compare-preflight`` -- prove inputs did not change between preflights;
* ``bundle``     -- write one compact failure bundle for any failed gate.

The experimental contract (steps, seed, z-range, track/patch receipts and the
12.6/41.6 reproduction check) lives in the recipe and is only mirrored here so
that ``check`` can refuse a manifest that would move it.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
GIB = 1 << 30
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# villa spiral_progress.py: "PROGRESS <stage> — 1,234/30,000 iterations (4.1%) — 12.3 it/s — ..."
PROGRESS_RE = re.compile(
    r"PROGRESS (?P<stage>.+?) — (?P<step>[0-9][0-9,]*)/(?P<total>[0-9][0-9,]*) "
    r"iterations \([^)]*\)(?: — (?P<rate>[0-9]+(?:\.[0-9]+)?) it/s)?"
)
SAFE_ENV_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "FIT_SPIRAL_CONFIG_OVERRIDES",
    "FIT_SPIRAL_RUN_DIR",
    "PATH",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONUNBUFFERED",
    "SCROLIQ_ROLE",
    "SCROLIQ_RUN_ID",
    "UV_PROJECT_ENVIRONMENT",
    "WANDB_MODE",
)


class SpiralCloudError(ValueError):
    """A cloud execution invariant failed."""


# --------------------------------------------------------------------------- utils


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpiralCloudError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpiralCloudError(f"{label} must be a JSON object")
    return value


def _dump(document: Any) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _write_new(path: Path, document: Any) -> None:
    """Create-only JSON write: evidence is never silently overwritten."""
    if path.exists():
        raise SpiralCloudError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(document), encoding="utf-8")


def _emit(document: Any, out: str | None) -> None:
    if out:
        _write_new(Path(out), document)
    sys.stdout.write(_dump(document))


def _get(mapping: Mapping[str, Any], dotted: str) -> Any:
    value: Any = mapping
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# ------------------------------------------------------------------ manifest check

# Every value that only exists once a real account/image/commit is chosen.
# ``check`` lists them as unresolved; ``plan`` requires them on the command line
# or in the manifest. Nothing here may be guessed.
LAUNCH_TIME_FIELDS = (
    "gcp.project",
    "gcp.zone",
    "gcp.image.name",
    "gcp.evidence_bucket.name",
    "software.scrollq.commit",
    "software.uv.version",
    "software.uv.linux_x86_64_tarball_sha256",
)


def check_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    recipe_path: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    check("schema_version", manifest.get("schema_version") == SCHEMA_VERSION,
          "manifest schema version is supported", actual=manifest.get("schema_version"))

    # -- recipe identity and the experimental contract -------------------------------
    recipe_meta = manifest.get("recipe") if isinstance(manifest.get("recipe"), Mapping) else {}
    rel = recipe_meta.get("path")
    recipe: dict[str, Any] = {}
    path = recipe_path or (repo_root / rel if isinstance(rel, str) else None)
    if path is None or not path.is_file():
        check("recipe_present", False, "frozen recipe file is present", path=str(path))
    else:
        recipe_bytes = path.read_bytes()
        actual = _sha256_bytes(recipe_bytes)
        check("recipe_sha256", actual == recipe_meta.get("sha256"),
              "frozen recipe bytes match the manifest", expected=recipe_meta.get("sha256"),
              actual=actual)
        try:
            recipe = json.loads(recipe_bytes)
        except json.JSONDecodeError as exc:
            check("recipe_json", False, f"recipe is not JSON: {exc}")

    contract = manifest.get("experiment_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    bounded = recipe.get("bounded_reproduction") if isinstance(recipe.get("bounded_reproduction"), Mapping) else {}
    reference = bounded.get("expected_reference_context") if isinstance(
        bounded.get("expected_reference_context"), Mapping) else {}
    comparison = reference.get("comparison_only_not_correctness_metrics") if isinstance(
        reference.get("comparison_only_not_correctness_metrics"), Mapping) else {}
    overrides = bounded.get("config_overrides") if isinstance(bounded.get("config_overrides"), Mapping) else {}
    mirrored = {
        "scroll": recipe.get("scroll"),
        "prize_volume_id": recipe.get("prize_volume_id"),
        "z_range_half_open": bounded.get("z_range_half_open"),
        "optimizer_num_training_steps": bounded.get("optimizer_num_training_steps"),
        "optimizer_random_seed": bounded.get("optimizer_random_seed"),
        "expected_tracks_in_roi": reference.get("documented_tracks_loaded_with_input_use_tracks_true"),
        "expected_fitted_patches": 0 if overrides.get("input_disable_patches") is True else None,
        "satisfied_tracks_percent": comparison.get("satisfied_tracks_percent"),
        "satisfied_track_points_percent": comparison.get("satisfied_track_points_percent"),
    }
    for key, value in mirrored.items():
        check(f"contract:{key}", value is not None and contract.get(key) == value,
              "manifest mirrors (and cannot move) the frozen recipe contract",
              manifest=contract.get(key), recipe=value)
    check("contract:ink_may_select_geometry",
          contract.get("ink_may_select_geometry") is False
          and _get(recipe, "promotion_policy.ink_may_select_geometry") is False,
          "no ink output may choose geometry")

    # -- software pins -----------------------------------------------------------------
    software = manifest.get("software") if isinstance(manifest.get("software"), Mapping) else {}
    for key, recipe_key in (("villa", "villa_commit"), ("assembler", "dataset_assembler_commit")):
        commit = _get(software, f"{key}.commit")
        check(f"software:{key}", isinstance(commit, str) and bool(COMMIT_RE.fullmatch(commit))
              and commit == _get(recipe, f"software.{recipe_key}"),
              f"{key} commit is the 40-hex pin from the frozen recipe",
              manifest=commit, recipe=_get(recipe, f"software.{recipe_key}"))

    # -- VM guard rails ----------------------------------------------------------------
    stage_vm = manifest.get("stage_vm") if isinstance(manifest.get("stage_vm"), Mapping) else {}
    gpu_vm = manifest.get("gpu_vm") if isinstance(manifest.get("gpu_vm"), Mapping) else {}
    for label, vm, ceiling in (("stage_vm", stage_vm, 12), ("gpu_vm", gpu_vm, 12)):
        hours = vm.get("max_run_duration_hours")
        check(f"{label}:termination", vm.get("termination_action") == "DELETE",
              "platform-enforced max run duration deletes the VM", actual=vm.get("termination_action"))
        check(f"{label}:max_run", _is_number(hours) and 0 < hours <= ceiling,
              f"max run duration is set and at most {ceiling} h", actual=hours)
    check("gpu_vm:accelerator", _get(gpu_vm, "accelerator.type") == "nvidia-l4"
          and _get(gpu_vm, "accelerator.count") == 1, "exactly one NVIDIA L4")
    candidates = gpu_vm.get("machine_type_candidates")
    ok_candidates = (
        isinstance(candidates, list) and bool(candidates)
        and all(isinstance(row, Mapping) and isinstance(row.get("name"), str)
                and str(row["name"]).startswith("g2-") and _is_number(row.get("host_ram_gib"))
                for row in candidates)
        and [row["host_ram_gib"] for row in candidates] == sorted(row["host_ram_gib"] for row in candidates)
    )
    check("gpu_vm:machine_type_candidates", ok_candidates,
          "G2 (single-L4) candidates are listed in ascending host RAM")
    watchdog = manifest.get("watchdog") if isinstance(manifest.get("watchdog"), Mapping) else {}
    prep = watchdog.get("gpu_prep_window_minutes")
    gate_window = watchdog.get("gpu_gate_window_minutes")
    gpu_minutes = (gpu_vm.get("max_run_duration_hours") or 0) * 60
    check("watchdog:prep_window", _is_number(prep) and 0 < prep < gpu_minutes,
          "the fit must start inside a preparation window shorter than the VM lifetime",
          actual=prep)
    check("watchdog:gate_window", _is_number(gate_window) and 0 < gate_window <= (prep or 0),
          "the gate-only GPU boot has its own, shorter window", actual=gate_window)

    # -- smoke contract ----------------------------------------------------------------
    smoke = manifest.get("smoke") if isinstance(manifest.get("smoke"), Mapping) else {}
    base_steps = bounded.get("optimizer_num_training_steps")
    steps = smoke.get("optimizer_num_training_steps")
    check("smoke:steps", isinstance(steps, int) and not isinstance(steps, bool)
          and isinstance(base_steps, int) and 0 < steps < base_steps,
          "smoke run is strictly shorter than the frozen baseline", smoke=steps, frozen=base_steps)
    check("smoke:non_promotional", smoke.get("promotional") is False
          and smoke.get("delete_outputs_after") is True and smoke.get("cache_isolated") is True,
          "smoke outputs are non-promotional, cache-isolated and deleted before the real run")
    factor = smoke.get("projection_safety_factor")
    check("smoke:safety_factor", _is_number(factor) and factor >= 1.0,
          "runtime projection is inflated, never deflated", actual=factor)

    # -- storage budget ----------------------------------------------------------------
    disk_gib = _get(manifest, "data_disk.size_gib")
    budget = manifest.get("storage_budget_gib") if isinstance(manifest.get("storage_budget_gib"), Mapping) else {}
    components = budget.get("components") if isinstance(budget.get("components"), Mapping) else {}
    floors = budget.get("floors") if isinstance(budget.get("floors"), Mapping) else {}
    comp_ok = bool(components) and all(
        isinstance(row, Mapping) and _is_number(row.get("gib")) and row["gib"] >= 0
        and isinstance(row.get("source"), str) and row["source"]
        for row in components.values())
    check("storage:components", comp_ok, "every storage component has a size and a stated source")
    total = sum(float(row["gib"]) for row in components.values()) if comp_ok else None
    check("storage:fits_disk", total is not None and _is_number(disk_gib) and total <= disk_gib,
          "sum of planned storage fits the data disk", total_gib=total, disk_gib=disk_gib)
    floors_ok = bool(floors)
    for name, row in floors.items():
        if not (isinstance(row, Mapping) and _is_number(row.get("min_free_gib"))
                and isinstance(row.get("covers"), list) and row["covers"]
                and all(key in components for key in row["covers"])):
            floors_ok = False
            check(f"storage:floor:{name}", False, "floor names known downstream components")
            continue
        need = sum(float(components[key]["gib"]) for key in row["covers"])
        good = row["min_free_gib"] >= need and (not _is_number(disk_gib) or row["min_free_gib"] <= disk_gib)
        floors_ok = floors_ok and good
        check(f"storage:floor:{name}", good,
              "floor covers everything still to be written after this point",
              min_free_gib=row["min_free_gib"], downstream_gib=round(need, 3))
    check("storage:floors", floors_ok, "every staging/fit checkpoint has a free-space floor")

    # -- script pins -------------------------------------------------------------------
    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), Mapping) else {}
    check("scripts:declared", bool(scripts) and "cloud/spiral-gcp/bootstrap.sh" in scripts,
          "bootstrap and role scripts are hash-pinned")
    for rel_path, expected in sorted(scripts.items()):
        target = repo_root / rel_path
        actual = _sha256(target) if target.is_file() and not target.is_symlink() else None
        check(f"script:{rel_path}", actual is not None and actual == expected,
              "committed script bytes match the manifest", expected=expected, actual=actual)

    # -- small published inputs pinned before any VM exists ----------------------------
    sources = manifest.get("staging_sources") if isinstance(manifest.get("staging_sources"), Mapping) else {}
    pinned = [
        ("umbilicus", _get(sources, "umbilicus.sha256")),
        ("spiral_scroll_json", _get(sources, "spiral_scroll_json.sha256")),
        ("lasagna_manifest", _get(sources, "lasagna.manifest_file.sha256")),
    ]
    stores = _get(sources, "lasagna.stores")
    if isinstance(stores, list):
        for store in stores:
            if isinstance(store, Mapping):
                for meta in ("zattrs_sha256", "zgroup_sha256", "zarray_sha256"):
                    pinned.append((f"lasagna:{store.get('local')}:{meta}", store.get(meta)))
    for name, value in pinned:
        check(f"pinned:{name}", isinstance(value, str) and bool(SHA256_RE.fullmatch(value)),
              "small published input is hash-pinned before launch")
    sense = _get(recipe, "scroll_spec_expected.spiral_outward_sense_candidate")
    check("staging:outward_sense", sources.get("outward_sense") is not None
          and sources.get("outward_sense") == sense,
          "assembler is given the recipe's outward sense; it is never guessed",
          manifest=sources.get("outward_sense"), recipe=sense)
    for key in ("villa_python", "scrollq_python"):
        check(f"software:{key}", isinstance(software.get(key), str) and bool(software.get(key)),
              f"{key} is pinned")
    expected_locals = {"las_008_nx.ome.zarr", "las_008_ny.ome.zarr", "las_008_grad_mag.ome.zarr"}
    locals_ = {row.get("local") for row in stores if isinstance(row, Mapping)} if isinstance(stores, list) else set()
    check("lasagna:local_names", locals_ == expected_locals,
          "stores are staged under the conventional villa / preflight names",
          actual=sorted(str(x) for x in locals_))
    group = _get(sources, "lasagna.group")
    check("lasagna:group", group is not None
          and str(group) == str(_get(recipe, "scroll_spec_expected.normal_zarr_group")),
          "fetched group is the frozen normal_zarr_group", actual=group)
    scale = _get(recipe, "scroll_spec_expected.lasagna_scale")
    scales_ok = isinstance(stores, list) and bool(stores) and all(
        isinstance(row, Mapping) and row.get("expected_scale") == [scale] * 3 for row in stores)
    check("lasagna:scale", scales_ok, "pinned multiscale factor equals the frozen lasagna_scale",
          lasagna_scale=scale)

    unresolved = [field for field in LAUNCH_TIME_FIELDS if _get(manifest, field) in (None, "")]
    structurally_ok = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud check",
        "status": "pass" if structurally_ok else "failed",
        "ok": structurally_ok,
        "ready_to_launch": structurally_ok and not unresolved,
        "unresolved_launch_time_fields": unresolved,
        "storage_total_gib": total,
        "checks": checks,
    }


# --------------------------------------------------------------------------- plan


def choose_gpu_machine_type(manifest: Mapping[str, Any], resident_pool_bytes: int | None) -> dict[str, Any]:
    """Frozen host-RAM rule; returns the smallest single-L4 G2 type that satisfies it."""
    rule = _get(manifest, "gpu_vm.host_ram_rule") or {}
    candidates = _get(manifest, "gpu_vm.machine_type_candidates") or []
    if resident_pool_bytes is None:
        default = _get(manifest, "gpu_vm.default_machine_type")
        return {"machine_type": default, "rule": "default (no staged pool measurement supplied)",
                "required_host_ram_gib": None}
    pool_gib = resident_pool_bytes / GIB
    need = pool_gib * float(rule.get("pool_multiplier", 1.0)) + float(rule.get("base_gib", 0.0))
    for row in candidates:
        if float(row["host_ram_gib"]) >= need:
            return {"machine_type": row["name"], "rule": rule, "resident_pool_gib": round(pool_gib, 3),
                    "required_host_ram_gib": round(need, 3)}
    raise SpiralCloudError(
        f"no single-L4 candidate has {need:.1f} GiB host RAM for {pool_gib:.1f} GiB of resident pools")


def build_plan(
    manifest: Mapping[str, Any],
    manifest_bytes: bytes,
    *,
    repo_root: Path,
    overrides: Mapping[str, str],
    run_id: str,
    staged: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = copy.deepcopy(dict(manifest))
    for dotted, value in overrides.items():
        if not value:
            continue
        node = resolved
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) not in (None, "", value):
            raise SpiralCloudError(f"{dotted} is frozen in the manifest as {node[parts[-1]]!r}")
        node[parts[-1]] = value

    report = check_manifest(resolved, repo_root=repo_root)
    if not report["ok"]:
        failed = [row["name"] for row in report["checks"] if not row["ok"]]
        raise SpiralCloudError("manifest check failed: " + ", ".join(failed))
    missing = [field for field in LAUNCH_TIME_FIELDS if _get(resolved, field) in (None, "")]
    if missing:
        raise SpiralCloudError("unresolved launch-time fields: " + ", ".join(missing))
    commit = resolved["software"]["scrollq"]["commit"]
    if not COMMIT_RE.fullmatch(commit):
        raise SpiralCloudError("software.scrollq.commit must be a 40-hex commit")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", run_id):
        raise SpiralCloudError("run id must be 3-41 lowercase letters, digits or dashes")

    # The VM verifies the manifest bytes at the pinned commit, so the commit must
    # carry exactly these manifest and script bytes.
    manifest_rel = _get(resolved, "self_path")
    pinned_paths = {manifest_rel: _sha256_bytes(manifest_bytes), **dict(resolved["scripts"])}
    for rel_path, expected in pinned_paths.items():
        try:
            blob = subprocess.run(["git", "-C", str(repo_root), "show", f"{commit}:{rel_path}"],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SpiralCloudError(f"cannot read {rel_path} at scrollq commit {commit}: {exc}") from exc
        if _sha256_bytes(blob) != expected:
            raise SpiralCloudError(f"{rel_path} at {commit} differs from the checked manifest/script bytes")

    gcp = resolved["gcp"]
    project, zone = gcp["project"], gcp["zone"]
    region = zone.rsplit("-", 1)[0]
    disk = resolved["data_disk"]
    bucket = gcp["evidence_bucket"]["name"]
    evidence_uri = f"gs://{bucket}/{run_id}"
    image = gcp["image"]
    manifest_sha = _sha256_bytes(manifest_bytes)
    disk_name = f"{disk['name_prefix']}-{run_id}"
    pool_bytes = None
    if staged is not None:
        pool_bytes = _get(staged, "resident_pools.total_bytes")
        if not isinstance(pool_bytes, int) or pool_bytes <= 0:
            raise SpiralCloudError("staged data receipt lacks resident_pools.total_bytes")
    gpu_choice = choose_gpu_machine_type(resolved, pool_bytes)

    def instance(role: str, vm: Mapping[str, Any], machine_type: str) -> list[str]:
        name = f"scroliq-{role}-{run_id}"[:63]
        metadata = ",".join([
            f"scroliq-role={role}",
            f"scroliq-commit={commit}",
            f"scroliq-manifest-sha256={manifest_sha}",
            f"scroliq-evidence-uri={evidence_uri}",
            f"scroliq-run-id={run_id}",
            f"scroliq-zone={zone}",
        ])
        argv = [
            "gcloud", "compute", "instances", "create", name,
            f"--project={project}", f"--zone={zone}",
            f"--machine-type={machine_type}",
            f"--image={image['name']}", f"--image-project={image['project']}",
            f"--boot-disk-size={vm['boot_disk_gib']}GB",
            f"--boot-disk-type={vm['boot_disk_type']}",
            f"--disk=name={disk_name},device-name={disk['device_name']},mode=rw,boot=no,auto-delete=no",
            "--provisioning-model=STANDARD",
            f"--max-run-duration={int(vm['max_run_duration_hours'] * 60)}m",
            f"--instance-termination-action={vm['termination_action']}",
            "--scopes=storage-rw,logging-write,compute-rw",
            f"--metadata={metadata}",
            "--metadata-from-file=startup-script=cloud/spiral-gcp/bootstrap.sh",
        ]
        if role.startswith("gpu"):
            argv.append("--maintenance-policy=TERMINATE")
        return argv

    stage_vm, gpu_vm = resolved["stage_vm"], resolved["gpu_vm"]
    lifecycle = {"rule": [{"action": {"type": "Delete"},
                           "condition": {"age": gcp["evidence_bucket"]["lifecycle_delete_age_days"]}}]}
    steps = [
        {"step": "evidence_bucket", "argv": [
            "gcloud", "storage", "buckets", "create", f"gs://{bucket}", f"--project={project}",
            f"--location={region}", "--uniform-bucket-level-access"]},
        {"step": "evidence_bucket_lifecycle", "writes_file": "lifecycle.json", "file_content": lifecycle,
         "argv": ["gcloud", "storage", "buckets", "update", f"gs://{bucket}", "--lifecycle-file=lifecycle.json"]},
        {"step": "data_disk", "argv": [
            "gcloud", "compute", "disks", "create", disk_name, f"--project={project}", f"--zone={zone}",
            f"--size={disk['size_gib']}GB", f"--type={disk['type']}"]},
        {"step": "stage_env (CPU: tools, pinned clones, villa env, CPU import gate)",
         "argv": instance("stage-env", stage_vm, stage_vm["machine_type"]),
         "wait_for": f"{evidence_uri}/stage-env/STATUS.json reports pass"},
        {"step": "gpu_gate (L4: driver, torch CUDA, Triton, vc_spiral, villa CUDA startup; no large data)",
         "argv": instance("gpu-gate", gpu_vm, gpu_vm["gate_machine_type"]),
         "wait_for": f"{evidence_uri}/gpu-gate/STATUS.json reports pass"},
        {"step": "stage_data (CPU: tracks, Lasagna, resident pools, preflight)",
         "argv": instance("stage-data", stage_vm, stage_vm["machine_type"]),
         "wait_for": f"{evidence_uri}/stage-data/STATUS.json reports pass; re-run plan with --staged"},
        {"step": "gpu_run (L4: re-gate, smoke, frozen 30k fit, reproduction check, export)",
         "argv": instance("gpu-run", gpu_vm, gpu_choice["machine_type"]),
         "machine_type_choice": gpu_choice,
         "wait_for": f"{evidence_uri}/gpu-run/STATUS.json"},
        {"step": "cleanup_data_disk (only after evidence is verified in the bucket)", "argv": [
            "gcloud", "compute", "disks", "delete", disk_name, f"--project={project}", f"--zone={zone}"]},
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud plan",
        "created_utc": _utc_now(),
        "run_id": run_id,
        "manifest_sha256": manifest_sha,
        "scrollq_commit": commit,
        "evidence_uri": evidence_uri,
        "resolved": {field: _get(resolved, field) for field in LAUNCH_TIME_FIELDS},
        "executes_nothing": True,
        "steps": steps,
        "note": "Each VM halts or deletes itself; the max-run DELETE is the hard guard. "
                "Never run two steps against the data disk at once.",
    }


# --------------------------------------------------------------------- disk floor


def disk_floor(path: Path, min_free_gib: float, label: str) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    ok = usage.free >= min_free_gib * GIB
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud disk-floor",
        "label": label,
        "path": str(path),
        "checked_utc": _utc_now(),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "min_free_gib": min_free_gib,
        "status": "pass" if ok else "failed",
        "ok": ok,
    }


def manifest_floor(manifest: Mapping[str, Any], name: str) -> float:
    value = _get(manifest, f"storage_budget_gib.floors.{name}.min_free_gib")
    if not _is_number(value):
        raise SpiralCloudError(f"manifest has no storage floor named {name!r}")
    return float(value)


# ----------------------------------------------------------------------- GPU gate

GATE_PROBE = r'''
import json, os, sys, time
out = {}
def step(name, fn):
    t = time.monotonic()
    try:
        out[name] = {"ok": True, "value": fn()}
    except BaseException as exc:  # recorded, never raised
        out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    out[name]["seconds"] = round(time.monotonic() - t, 3)
    return out[name]["ok"]
cpu_only = sys.argv[1] == "cpu"
def torch_info():
    import torch
    return {"version": torch.__version__, "cuda_build": torch.version.cuda}
def vc_spiral_info():
    # The four nanobind extensions declared in villa spiral-fitting/cpp/CMakeLists.txt.
    import importlib
    mods = {}
    for name in ("spiral_sampling", "track_crossings", "track_store", "surface_index"):
        mods[name] = getattr(importlib.import_module("vc_spiral." + name), "__file__", None)
    return mods
def triton_info():
    import triton
    return {"version": triton.__version__}
step("import_torch", torch_info)
step("import_triton", triton_info)
step("import_vc_spiral", vc_spiral_info)
step("import_fit_spiral", lambda: __import__("fit_spiral").__file__)
if not cpu_only:
    def cuda():
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("torch.cuda.is_available() is False")
        props = torch.cuda.get_device_properties(0)
        a = torch.randn(512, 512, device="cuda")
        b = (a @ a).sum().item()
        torch.cuda.synchronize()
        return {"device": props.name, "total_memory": props.total_memory,
                "capability": list(torch.cuda.get_device_capability(0)), "matmul_finite": b == b}
    def triton_kernel():
        import torch, triton, triton.language as tl
        @triton.jit
        def add(x_ptr, y_ptr, o_ptr, n, BLOCK: tl.constexpr):
            offs = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
            mask = offs < n
            tl.store(o_ptr + offs, tl.load(x_ptr + offs, mask=mask) + tl.load(y_ptr + offs, mask=mask), mask=mask)
        x = torch.arange(1000, device="cuda", dtype=torch.float32)
        o = torch.empty_like(x)
        add[(triton.cdiv(1000, 256),)](x, x, o, 1000, BLOCK=256)
        torch.cuda.synchronize()
        if not torch.equal(o, x * 2):
            raise RuntimeError("Triton kernel produced wrong values")
        return "compiled and matched"
    def villa_cuda_startup():
        from types import SimpleNamespace
        from fit_spiral import FitContext
        FitContext.check_cuda_ready(SimpleNamespace(progress=None))
        return "FitContext.check_cuda_ready passed"
    step("torch_cuda", cuda)
    step("triton_kernel", triton_kernel)
    step("villa_cuda_startup", villa_cuda_startup)
print("SCROLIQ_GATE_JSON=" + json.dumps(out, sort_keys=True))
'''


def _nvidia_smi() -> dict[str, Any]:
    tool = shutil.which("nvidia-smi")
    if not tool:
        return {"ok": False, "error": "nvidia-smi not found"}
    try:
        result = subprocess.run(
            [tool, "--query-gpu=name,driver_version,memory.total,uuid", "--format=csv,noheader"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    rows = []
    for line in result.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append({"name": parts[0], "driver_version": parts[1], "memory_total": parts[2],
                         "uuid": parts[3] if len(parts) > 3 else None})
    return {"ok": bool(rows), "gpus": rows}


def gpu_gate(
    *,
    python: str,
    villa_root: Path,
    expect_gpu: str,
    min_driver_major: int,
    cpu_only: bool,
    villa_tests: Sequence[str] = (),
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    smi: Callable[[], dict[str, Any]] = _nvidia_smi,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    gpu: dict[str, Any] = {"not_run": "cpu-only gate"}
    if not cpu_only:
        gpu = smi()
        rows = gpu.get("gpus") or []
        check("nvidia_smi", bool(gpu.get("ok")), "nvidia-smi reports at least one GPU",
              error=gpu.get("error"))
        check("gpu_count", len(rows) == 1, "exactly one GPU is visible", count=len(rows))
        names = [row["name"] for row in rows]
        check("gpu_name", bool(rows) and all(expect_gpu in name for name in names),
              f"GPU is an {expect_gpu}", actual=names)
        majors = []
        for row in rows:
            match = re.match(r"(\d+)", row.get("driver_version") or "")
            majors.append(int(match.group(1)) if match else None)
        check("driver_major", bool(majors) and all(m is not None and m >= min_driver_major for m in majors),
              f"driver major version >= {min_driver_major} (CUDA build of the pinned torch)",
              actual=[row.get("driver_version") for row in rows])

    spiral = villa_root / "spiral-fitting"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(spiral)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AGENTS_AGENT_MODE"] = "1"
    probe: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="scroliq-gate-") as tmp:
        script = Path(tmp) / "probe.py"
        script.write_text(GATE_PROBE, encoding="utf-8")
        try:
            result = runner([python, str(script), "cpu" if cpu_only else "gpu"], cwd=str(spiral), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1800)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            stdout, stderr, code = "", str(exc), None
    marker = [line for line in stdout.splitlines() if line.startswith("SCROLIQ_GATE_JSON=")]
    if marker:
        try:
            probe = json.loads(marker[-1].split("=", 1)[1])
        except json.JSONDecodeError:
            probe = {}
    check("probe_ran", code == 0 and bool(probe), "probe ran in the villa environment",
          return_code=code, stderr_tail=stderr[-4000:])
    required = ["import_torch", "import_triton", "import_vc_spiral", "import_fit_spiral"]
    if not cpu_only:
        required += ["torch_cuda", "triton_kernel", "villa_cuda_startup"]
    for name in required:
        row = probe.get(name) if isinstance(probe.get(name), Mapping) else {}
        check(f"probe:{name}", row.get("ok") is True, f"{name} succeeded",
              value=row.get("value"), error=row.get("error"))
    if not cpu_only and isinstance(_get(probe, "torch_cuda.value.device"), str):
        check("torch_sees_expected_gpu", expect_gpu in probe["torch_cuda"]["value"]["device"],
              "torch reports the expected device", actual=probe["torch_cuda"]["value"]["device"])

    test_results = []
    for test in villa_tests:
        try:
            result = runner([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
                            cwd=str(villa_root), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=1800)
            code, tail = result.returncode, result.stdout[-4000:]
        except (OSError, subprocess.SubprocessError) as exc:
            code, tail = None, str(exc)
        test_results.append({"test": test, "return_code": code, "output_tail": tail})
        check(f"villa_test:{test}", code == 0, "villa's own test passes on this host")

    ok = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud gpu-gate",
        "mode": "cpu-import-only" if cpu_only else "gpu",
        "checked_utc": _utc_now(),
        "status": "pass" if ok else "failed",
        "ok": ok,
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "nvidia_smi": gpu,
        "probe": probe,
        "villa_tests": test_results,
        "checks": checks,
    }


# ------------------------------------------------------------------ Lasagna fetch


class _HttpTransport:
    def __init__(self, workers: int) -> None:
        import requests
        from requests.adapters import HTTPAdapter, Retry

        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=workers,
                              max_retries=Retry(total=6, backoff_factor=1.0,
                                                status_forcelist=(429, 500, 502, 503, 504)))
        self.session.mount("https://", adapter)

    def get(self, url: str) -> bytes:
        response = self.session.get(url, timeout=120)
        if response.status_code != 200:
            raise SpiralCloudError(f"GET {url}: HTTP {response.status_code}")
        return response.content


def s3_list(get: Callable[[str], bytes], base_url: str, prefix: str) -> list[dict[str, Any]]:
    """List every object below ``prefix`` with a real XML parser (lesson 9)."""
    from urllib.parse import quote

    rows: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        url = f"{base_url}/?list-type=2&prefix={quote(prefix)}"
        if token:
            url += f"&continuation-token={quote(token, safe='')}"
        root = ET.fromstring(get(url))
        for item in root.iter(f"{S3_NS}Contents"):
            key = item.findtext(f"{S3_NS}Key")
            size = item.findtext(f"{S3_NS}Size")
            etag = (item.findtext(f"{S3_NS}ETag") or "").strip('"')
            if key is None or size is None:
                raise SpiralCloudError("S3 listing entry lacks Key or Size")
            rows.append({"key": key, "size": int(size), "etag": etag})
        truncated = (root.findtext(f"{S3_NS}IsTruncated") or "false").lower() == "true"
        token = root.findtext(f"{S3_NS}NextContinuationToken")
        if not truncated:
            break
        if not token:
            raise SpiralCloudError("truncated S3 listing without a continuation token")
    return rows


def _verify_local(path: Path, row: Mapping[str, Any]) -> str | None:
    """Return 'md5' / 'size' when the local file matches the listing, else None."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size != row["size"]:
        return None
    etag = row.get("etag") or ""
    if etag and "-" not in etag and re.fullmatch(r"[0-9a-f]{32}", etag):
        digest = hashlib.md5()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return "md5" if digest.hexdigest() == etag else None
    return "size"


def fetch_lasagna(
    manifest: Mapping[str, Any],
    *,
    dataset: Path,
    evidence_dir: Path,
    workers: int = 64,
    get: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    source = _get(manifest, "staging_sources.lasagna")
    if not isinstance(source, Mapping):
        raise SpiralCloudError("manifest lacks staging_sources.lasagna")
    if get is None:
        get = _HttpTransport(workers).get
    base_url = source["bucket_url"].rstrip("/")
    run_prefix = source["run_prefix"].rstrip("/") + "/"
    group = str(source["group"])
    out_root = dataset / "lasagna_inputs"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    manifest_file = source["manifest_file"]
    blob = get(f"{base_url}/{run_prefix}{manifest_file['name']}")
    check("lasagna_manifest_sha256", _sha256_bytes(blob) == manifest_file["sha256"],
          "Lasagna run manifest matches the pinned bytes")
    (evidence_dir / manifest_file["name"]).write_bytes(blob)

    stores_report = []
    lock = threading.Lock()
    for store in source["stores"]:
        src_prefix = f"{run_prefix}{store['source']}/"
        local = out_root / store["local"]
        meta_rows = []
        for rel, pin in ((".zattrs", "zattrs_sha256"), (".zgroup", "zgroup_sha256"),
                         (f"{group}/.zarray", "zarray_sha256")):
            data = get(f"{base_url}/{src_prefix}{rel}")
            good = _sha256_bytes(data) == store[pin]
            check(f"{store['local']}:{rel}", good, "store metadata matches pinned bytes")
            meta_rows.append({"path": rel, "sha256": _sha256_bytes(data), "size": len(data)})
            if good:
                target = local / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if rel == ".zattrs" and good:
                attrs = json.loads(data)
                scales = {d.get("path"): d.get("coordinateTransformations", [{}])[0].get("scale")
                          for d in _get(attrs, "multiscales")[0]["datasets"]}
                check(f"{store['local']}:scale", scales.get(group) == store["expected_scale"],
                      "multiscale metadata gives the frozen lasagna_scale for this group",
                      actual=scales.get(group))

        listing = [row for row in s3_list(get, base_url, f"{src_prefix}{group}/")
                   if not row["key"].endswith("/.zarray")]
        check(f"{store['local']}:listed_chunks", len(listing) > 0,
              "positive control: the group lists at least one chunk object", count=len(listing))
        listing.sort(key=lambda row: row["key"])
        listing_text = "".join(f"{r['key']}\t{r['size']}\t{r['etag']}\n" for r in listing)
        with gzip.open(evidence_dir / f"{store['local']}.listing.tsv.gz", "wt", encoding="utf-8") as fh:
            fh.write(listing_text)

        counters = {"downloaded": 0, "already_present": 0, "md5": 0, "size": 0, "failed": 0}
        failures: list[str] = []

        def one(row: Mapping[str, Any]) -> None:
            rel_key = row["key"][len(src_prefix):]
            target = local / rel_key
            mode = _verify_local(target, row)
            fetched = False
            if mode is None:
                try:
                    data = get(f"{base_url}/{row['key']}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_name(target.name + ".part")
                    tmp.write_bytes(data)
                    os.replace(tmp, target)
                    fetched = True
                    mode = _verify_local(target, row)
                except Exception as exc:  # recorded and counted, never dropped
                    with lock:
                        counters["failed"] += 1
                        failures.append(f"{rel_key}: {exc}")
                    return
            with lock:
                if mode is None:
                    counters["failed"] += 1
                    failures.append(f"{rel_key}: size/md5 mismatch after download")
                    return
                counters["downloaded" if fetched else "already_present"] += 1
                counters[mode] += 1

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, listing))

        listed_bytes = sum(row["size"] for row in listing)
        local_chunks = sum(1 for p in (local / group).rglob("*")
                           if p.is_file() and p.name != ".zarray" and not p.name.endswith(".part"))
        check(f"{store['local']}:complete", counters["failed"] == 0 and local_chunks == len(listing),
              "every listed object is present locally and verified; nothing extra",
              listed=len(listing), local=local_chunks, failed=counters["failed"])
        stores_report.append({
            "source": store["source"], "local": store["local"], "group": group,
            "listed_objects": len(listing), "listed_bytes": listed_bytes,
            "listing_sha256": _sha256_bytes(listing_text.encode("utf-8")),
            "metadata": meta_rows, **counters, "failures": failures[:50],
        })

    ok = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud fetch-lasagna",
        "checked_utc": _utc_now(),
        "status": "pass" if ok else "failed",
        "ok": ok,
        "source": f"{base_url}/{run_prefix}",
        "stores": stores_report,
        "total_bytes": sum(row["listed_bytes"] for row in stores_report),
        "checks": checks,
    }


def resident_pool_bytes(dataset: Path, group: str) -> dict[str, Any]:
    root = dataset / "lasagna_inputs"
    rows = []
    for sidecar in sorted(root.glob(f"*.respool_g{group}*")):
        if sidecar.is_dir():
            size = sum(p.stat().st_size for p in sidecar.rglob("*") if p.is_file())
            rows.append({"sidecar": sidecar.name, "bytes": size})
    return {"sidecars": rows, "total_bytes": sum(row["bytes"] for row in rows)}


# --------------------------------------------------------------------------- smoke


def derive_smoke_recipe(recipe_bytes: bytes, steps: int) -> dict[str, Any]:
    recipe = json.loads(recipe_bytes)
    bounded = recipe["bounded_reproduction"]
    base_steps = bounded["optimizer_num_training_steps"]
    if not (isinstance(steps, int) and 0 < steps < base_steps):
        raise SpiralCloudError(f"smoke steps must be in (0, {base_steps})")
    smoke = copy.deepcopy(recipe)
    smoke["status"] = "smoke_non_promotional"
    smoke["bounded_reproduction"]["optimizer_num_training_steps"] = steps
    smoke["bounded_reproduction"]["config_overrides"]["optimizer_num_training_steps"] = steps
    smoke["bounded_reproduction"].pop("shell_template", None)
    smoke["smoke"] = {
        "promotional": False,
        "base_recipe_sha256": _sha256_bytes(recipe_bytes),
        "base_optimizer_num_training_steps": base_steps,
        "purpose": "prove tracks load, resident pools fit, optimizer starts and a checkpoint is "
                   "written before the untouched frozen run; never a reproduction result",
    }
    return smoke


def _parse_progress(text: str) -> list[dict[str, Any]]:
    rows = []
    for match in PROGRESS_RE.finditer(text):
        rows.append({
            "stage": match.group("stage"),
            "step": int(match.group("step").replace(",", "")),
            "total": int(match.group("total").replace(",", "")),
            "rate": float(match.group("rate")) if match.group("rate") else None,
        })
    return rows


def _peak_vram_mib(csv_path: Path | None) -> int | None:
    if csv_path is None or not csv_path.is_file():
        return None
    peak = None
    for line in csv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"(\d+)\s*MiB", line)
        if match:
            value = int(match.group(1))
            peak = value if peak is None or value > peak else peak
    return peak


def smoke_verdict(
    manifest: Mapping[str, Any],
    *,
    run_dir: Path,
    elapsed_vm_seconds: float,
    vram_csv: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    receipt = _load_json(run_dir / "spiral-run.receipt.json", "smoke run receipt")
    smoke_cfg = manifest["smoke"]
    check("receipt_success", receipt.get("success") is True,
          "smoke run exited 0, wrote a checkpoint and passed the supervision receipt",
          status=receipt.get("status"), return_code=receipt.get("return_code"))
    check("receipt_is_smoke", receipt.get("mode") == "smoke" and receipt.get("promotional") is False,
          "receipt is marked non-promotional smoke")
    check("supervision", _get(receipt, "supervision.ok") is True,
          "480,117 tracks in ROI and zero patches observed (frozen receipt, not loosened)")
    recipe = _load_json(run_dir / "spiral-run.recipe.json", "smoke recipe copy")
    smoke_steps = _get(recipe, "bounded_reproduction.optimizer_num_training_steps")
    base_steps = _get(recipe, "smoke.base_optimizer_num_training_steps")
    check("smoke_steps", smoke_steps == smoke_cfg["optimizer_num_training_steps"],
          "smoke ran the manifest step count", actual=smoke_steps)

    text = ""
    for name in ("spiral-run.stdout.log", "spiral-run.stderr.log"):
        path = run_dir / name
        if path.is_file():
            text += path.read_text(encoding="utf-8", errors="replace")
    progress = [row for row in _parse_progress(text) if row["total"] == smoke_steps]
    rates = [row["rate"] for row in progress if row["rate"]]
    wall = receipt.get("wall_seconds")
    factor = float(smoke_cfg["projection_safety_factor"])
    projection: dict[str, Any] = {"smoke_wall_seconds": wall, "observed_rate_it_s": rates[-1] if rates else None}
    upper = None
    if _is_number(wall) and isinstance(smoke_steps, int) and isinstance(base_steps, int):
        # Upper bound: charges all smoke setup time to the optimizer.
        upper = wall / smoke_steps * base_steps
        projection["upper_bound_fit_seconds"] = round(upper, 1)
    estimate = None
    if rates and _is_number(wall) and isinstance(base_steps, int):
        setup = max(0.0, wall - smoke_steps / rates[-1])
        estimate = setup + base_steps / rates[-1]
        projection["rate_based_fit_seconds"] = round(estimate, 1)
    chosen = estimate if estimate is not None else upper
    max_run = _get(manifest, "gpu_vm.max_run_duration_hours") * 3600.0
    reserve = _get(manifest, "watchdog.export_reserve_minutes") * 60.0
    remaining = max_run - elapsed_vm_seconds - reserve
    projection.update({
        "basis": "rate" if estimate is not None else ("wall_upper_bound" if upper is not None else None),
        "safety_factor": factor,
        "projected_fit_seconds_with_safety": round(chosen * factor, 1) if chosen is not None else None,
        "remaining_budget_seconds": round(remaining, 1),
    })
    check("projection_available", chosen is not None, "a runtime projection could be computed")
    check("projection_fits_budget", chosen is not None and chosen * factor <= remaining,
          "projected frozen fit (with safety factor) finishes before the VM's hard deletion, "
          "leaving the export reserve")
    peak = _peak_vram_mib(vram_csv)
    ok = all(row["ok"] for row in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud smoke-verdict",
        "checked_utc": _utc_now(),
        "status": "proceed" if ok else "stop",
        "ok": ok,
        "projection": projection,
        "peak_vram_mib": peak,
        "progress_observations": progress[-5:],
        "checks": checks,
        "note": "Smoke results are execution evidence only and are deleted from the run disk "
                "before the frozen run starts.",
    }


# --------------------------------------------------------------- preflight compare


def compare_preflights(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    a = first.get("input_files") if isinstance(first.get("input_files"), Mapping) else {}
    b = second.get("input_files") if isinstance(second.get("input_files"), Mapping) else {}
    changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    ok = (first.get("ready_for_fit") is True and second.get("ready_for_fit") is True
          and bool(a) and not changed
          and first.get("config_overrides_canonical_json") == second.get("config_overrides_canonical_json"))
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud compare-preflight",
        "status": "pass" if ok else "failed",
        "ok": ok,
        "inputs_compared": len(a),
        "changed": changed,
    }


# -------------------------------------------------------------------------- bundle


def _tail(path: Path, limit: int) -> str:
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - limit))
        return fh.read().decode("utf-8", errors="replace")


def _cmd(argv: Sequence[str]) -> dict[str, Any]:
    if not shutil.which(argv[0]):
        return {"argv": list(argv), "error": "not found"}
    try:
        result = subprocess.run(list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=60)
        return {"argv": list(argv), "return_code": result.returncode, "output": result.stdout[-20000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"argv": list(argv), "error": str(exc)}


def failure_bundle(
    *,
    out_dir: Path,
    stage: str,
    failed_gate: str,
    reason: str,
    include: Iterable[Path],
    tail_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    if out_dir.exists():
        raise SpiralCloudError(f"refusing to overwrite existing bundle: {out_dir}")
    out_dir.mkdir(parents=True)
    files = []
    for path in include:
        row: dict[str, Any] = {"path": str(path)}
        if path.is_file() and not path.is_symlink():
            row.update({"size": path.stat().st_size, "sha256": _sha256(path)})
            tail = _tail(path, tail_bytes)
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(path).strip("/"))[-120:] + ".tail"
            (out_dir / name).write_text(tail, encoding="utf-8")
            row["tail_file"] = name
            row["tail_truncated"] = path.stat().st_size > tail_bytes
        else:
            row["missing"] = True
        files.append(row)
    meminfo = Path("/proc/meminfo")
    document = {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-spiral-cloud bundle",
        "created_utc": _utc_now(),
        "stage": stage,
        "failed_gate": failed_gate,
        "reason": reason,
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "python": sys.version},
        "environment": {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ},
        "disk": _cmd(["df", "-B1"]),
        "memory": meminfo.read_text(encoding="utf-8")[:4000] if meminfo.is_file() else None,
        "gpu": _cmd(["nvidia-smi", "-q"]),
        "processes": _cmd(["ps", "-eo", "pid,etimes,rss,pcpu,args", "--sort=-rss"]),
        "kernel_tail": _cmd(["dmesg", "--ctime", "--level=err,warn"]),
        "files": files,
    }
    (out_dir / "failure-bundle.json").write_text(_dump(document), encoding="utf-8")
    archive = out_dir.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(out_dir, arcname=out_dir.name)
    document["archive"] = {"path": str(archive), "sha256": _sha256(archive)}
    return document


# ---------------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scroliq-spiral-cloud",
        description="Fail-closed cloud execution guard rails for the frozen PHerc0826 Spiral baseline. "
                    "Validates the frozen cloud manifest, plans gcloud commands without running them, "
                    "and provides the on-VM gates (disk floors, GPU gate, Lasagna staging, smoke "
                    "verdict, preflight comparison, failure bundles).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="validate the frozen cloud execution manifest")
    p.add_argument("--manifest", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--require-ready", action="store_true",
                   help="also fail while launch-time fields are unresolved")
    p.add_argument("--out")

    p = sub.add_parser("plan", help="emit exact gcloud argv lists; executes nothing")
    p.add_argument("--manifest", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--project")
    p.add_argument("--zone")
    p.add_argument("--image", help="exact image name (not a family)")
    p.add_argument("--evidence-bucket")
    p.add_argument("--scrollq-commit")
    p.add_argument("--uv-version")
    p.add_argument("--uv-sha256")
    p.add_argument("--staged", help="stage-data receipt; selects the GPU machine type by the frozen rule")
    p.add_argument("--out")

    p = sub.add_parser("disk-floor", help="fail when free space is below a manifest floor")
    p.add_argument("--path", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--floor", required=True, help="floor name in storage_budget_gib.floors")
    p.add_argument("--out")

    p = sub.add_parser("gpu-gate", help="GPU/driver/torch/Triton/vc_spiral/villa CUDA gate")
    p.add_argument("--python", required=True, help="python of the villa environment")
    p.add_argument("--villa-root", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--cpu-only", action="store_true", help="import checks only (staging VM)")
    p.add_argument("--out")

    p = sub.add_parser("fetch-lasagna", help="stage the pinned Lasagna group from the public bucket")
    p.add_argument("--manifest", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--out")

    p = sub.add_parser("pool-size", help="measure resident-pool sidecar bytes")
    p.add_argument("--dataset", required=True)
    p.add_argument("--group", required=True)
    p.add_argument("--out")

    p = sub.add_parser("smoke-recipe", help="derive the non-promotional smoke recipe")
    p.add_argument("--recipe", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("smoke-verdict", help="proceed/stop decision from the smoke receipt")
    p.add_argument("--manifest", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--elapsed-vm-seconds", type=float, required=True)
    p.add_argument("--vram-csv")
    p.add_argument("--out")

    p = sub.add_parser("compare-preflight", help="prove inputs are unchanged between preflights")
    p.add_argument("first")
    p.add_argument("second")
    p.add_argument("--out")

    p = sub.add_parser("bundle", help="write a compact failure bundle")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--failed-gate", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--include", nargs="*", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            report = check_manifest(manifest, repo_root=Path(args.repo_root))
            _emit(report, args.out)
            return 0 if report["ok"] and (report["ready_to_launch"] or not args.require_ready) else 1
        if args.command == "plan":
            manifest_bytes = Path(args.manifest).read_bytes()
            manifest = json.loads(manifest_bytes)
            staged = _load_json(Path(args.staged), "stage-data receipt") if args.staged else None
            plan = build_plan(manifest, manifest_bytes, repo_root=Path(args.repo_root), run_id=args.run_id,
                              staged=staged, overrides={
                                  "gcp.project": args.project, "gcp.zone": args.zone,
                                  "gcp.image.name": args.image,
                                  "gcp.evidence_bucket.name": args.evidence_bucket,
                                  "software.scrollq.commit": args.scrollq_commit,
                                  "software.uv.version": args.uv_version,
                                  "software.uv.linux_x86_64_tarball_sha256": args.uv_sha256,
                              })
            _emit(plan, args.out)
            return 0
        if args.command == "disk-floor":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            report = disk_floor(Path(args.path), manifest_floor(manifest, args.floor), args.floor)
            _emit(report, args.out)
            return 0 if report["ok"] else 3
        if args.command == "gpu-gate":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            cuda = _get(manifest, "software.cuda_expectation") or {}
            report = gpu_gate(python=args.python, villa_root=Path(args.villa_root),
                              expect_gpu=cuda.get("gpu_name_contains", "L4"),
                              min_driver_major=int(cuda.get("min_driver_major", 0)),
                              cpu_only=args.cpu_only,
                              villa_tests=() if args.cpu_only else tuple(cuda.get("villa_gate_tests", ())))
            _emit(report, args.out)
            return 0 if report["ok"] else 1
        if args.command == "fetch-lasagna":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            report = fetch_lasagna(manifest, dataset=Path(args.dataset),
                                   evidence_dir=Path(args.evidence_dir), workers=args.workers)
            _emit(report, args.out)
            return 0 if report["ok"] else 1
        if args.command == "pool-size":
            report = resident_pool_bytes(Path(args.dataset), args.group)
            report["ok"] = report["total_bytes"] > 0
            _emit(report, args.out)
            return 0 if report["ok"] else 1
        if args.command == "smoke-recipe":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            smoke = derive_smoke_recipe(Path(args.recipe).read_bytes(),
                                        int(manifest["smoke"]["optimizer_num_training_steps"]))
            _write_new(Path(args.out), smoke)
            return 0
        if args.command == "smoke-verdict":
            manifest = _load_json(Path(args.manifest), "cloud manifest")
            report = smoke_verdict(manifest, run_dir=Path(args.run_dir),
                                   elapsed_vm_seconds=args.elapsed_vm_seconds,
                                   vram_csv=Path(args.vram_csv) if args.vram_csv else None)
            _emit(report, args.out)
            return 0 if report["ok"] else 1
        if args.command == "compare-preflight":
            report = compare_preflights(_load_json(Path(args.first), "preflight"),
                                        _load_json(Path(args.second), "preflight"))
            _emit(report, args.out)
            return 0 if report["ok"] else 1
        if args.command == "bundle":
            report = failure_bundle(out_dir=Path(args.out_dir), stage=args.stage,
                                    failed_gate=args.failed_gate, reason=args.reason,
                                    include=[Path(p) for p in args.include])
            sys.stdout.write(_dump(report))
            return 0
    except (OSError, SpiralCloudError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(f"{args.command}: {exc}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
