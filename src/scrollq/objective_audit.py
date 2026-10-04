"""Audit that a training/optimization run's *effective* objective matches its config.

A nonzero configured loss weight is not evidence that the term contributed
anything. A reported Lasagna defect is the model case: dense normal/spacing
losses were configured but, with no outer-shell mesh, silently evaluated to
zero. Nothing failed; the run just was not the run its config described.

An objective passport therefore carries two blocks:

``configured_objective``
    what the config asked for: per term a weight, an optional ``expect``
    (``active`` or ``inactive``; default follows the weight) and an optional
    ``claim`` naming the property the passport says the term enforces.

``effective_objective``
    what happened: per term evaluation count, finite count, nonzero count,
    accumulated weighted contribution and, preferably, gradient-norm
    statistics. :class:`ObjectiveTracker` produces this block.

``audit_objective`` fails closed. A term that was expected active but never
evaluated, always zero, non-finite, or (when it carries a claim) without any
gradient evidence is an integrity failure; so is a term expected *inactive*
that is active (an ablation arm that was not ablated) and an active term the
config never declared.

This audits integrity of the record, not model quality: a verified passport
says the terms did what the config says, not that the objective is good.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
TOOL = "scroliq-objective-audit"
VERDICT_OK = "OBJECTIVE_VERIFIED"
VERDICT_FAIL = "OBJECTIVE_INTEGRITY_FAILURE"
EXPECTATIONS = ("active", "inactive")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")


class ObjectiveAuditError(ValueError):
    """Raised when a passport is malformed (distinct from failing the audit)."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    raw = json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObjectiveAuditError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ObjectiveAuditError(f"{field} must be finite")
    if nonnegative and number < 0:
        raise ObjectiveAuditError(f"{field} must be >= 0")
    return number


def _count(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ObjectiveAuditError(f"{field} must be an integer >= 0")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise ObjectiveAuditError(f"{field} must be an identifier-like string")
    return value


def _configured_terms(block: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(block, Mapping) or not isinstance(block.get("terms"), list):
        raise ObjectiveAuditError("configured_objective.terms must be a list")
    terms: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(block["terms"]):
        where = f"configured_objective.terms[{index}]"
        if not isinstance(raw, Mapping):
            raise ObjectiveAuditError(f"{where} must be an object")
        name = _name(raw.get("name"), f"{where}.name")
        if name in terms:
            raise ObjectiveAuditError(f"duplicate configured term: {name}")
        weight = _number(raw.get("weight"), f"{where}.weight")
        expect = raw.get("expect")
        if expect is None:
            expect = "active" if weight != 0 else "inactive"
        if expect not in EXPECTATIONS:
            raise ObjectiveAuditError(f"{where}.expect must be one of {EXPECTATIONS}")
        if expect == "active" and weight == 0:
            raise ObjectiveAuditError(
                f"{where}: a term expected active cannot have weight 0"
            )
        claim = raw.get("claim")
        if claim is not None and (not isinstance(claim, str) or not claim.strip()):
            raise ObjectiveAuditError(f"{where}.claim must be a non-empty string")
        if claim is not None and expect == "inactive":
            raise ObjectiveAuditError(f"{where}: an inactive term cannot carry a claim")
        terms[name] = {"weight": weight, "expect": expect, "claim": claim}
    if not terms:
        raise ObjectiveAuditError("configured_objective.terms must not be empty")
    return terms


def _gradient(value: Any, field: str, evaluations: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ObjectiveAuditError(f"{field} must be an object or null")
    count = _count(value.get("count"), f"{field}.count")
    if count > evaluations:
        raise ObjectiveAuditError(f"{field}.count exceeds evaluations")
    return {
        "count": count,
        "sum": _number(value.get("sum"), f"{field}.sum", nonnegative=True),
        "max": _number(value.get("max"), f"{field}.max", nonnegative=True),
        "nonfinite": _count(value.get("nonfinite", 0), f"{field}.nonfinite"),
    }


def _effective_terms(block: Any) -> tuple[int, dict[str, dict[str, Any]]]:
    if not isinstance(block, Mapping) or not isinstance(block.get("terms"), list):
        raise ObjectiveAuditError("effective_objective.terms must be a list")
    steps = block.get("steps")
    if type(steps) is not int or steps < 1:
        raise ObjectiveAuditError(
            "effective_objective.steps must be an integer >= 1; a run with no "
            "optimization steps proves nothing"
        )
    terms: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(block["terms"]):
        where = f"effective_objective.terms[{index}]"
        if not isinstance(raw, Mapping):
            raise ObjectiveAuditError(f"{where} must be an object")
        name = _name(raw.get("name"), f"{where}.name")
        if name in terms:
            raise ObjectiveAuditError(f"duplicate effective term: {name}")
        evaluations = _count(raw.get("evaluations"), f"{where}.evaluations")
        finite = _count(raw.get("finite_evaluations"), f"{where}.finite_evaluations")
        nonzero = _count(raw.get("nonzero_evaluations"), f"{where}.nonzero_evaluations")
        if finite > evaluations:
            raise ObjectiveAuditError(f"{where}: finite_evaluations exceeds evaluations")
        if nonzero > finite:
            raise ObjectiveAuditError(f"{where}: nonzero_evaluations exceeds finite_evaluations")
        terms[name] = {
            "evaluations": evaluations,
            "finite_evaluations": finite,
            "nonzero_evaluations": nonzero,
            "accumulated_contribution": _number(
                raw.get("accumulated_contribution"), f"{where}.accumulated_contribution"
            ),
            "gradient_norm": _gradient(raw.get("gradient_norm"), f"{where}.gradient_norm", evaluations),
        }
    return steps, terms


def _term_failures(
    name: str,
    configured: Mapping[str, Any],
    effective: Mapping[str, Any] | None,
    *,
    min_nonzero_fraction: float,
    require_gradient_for_claims: bool,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []

    def fail(code: str, detail: str) -> None:
        failures.append({"code": code, "detail": detail})

    if configured["expect"] == "inactive":
        if effective is not None:
            grad = effective["gradient_norm"]
            if effective["nonzero_evaluations"] > 0:
                fail(
                    "INACTIVE_TERM_IS_ACTIVE",
                    f"expected inactive but {effective['nonzero_evaluations']} nonzero "
                    "evaluation(s) were recorded; this arm is not ablated",
                )
            if grad is not None and grad["max"] > 0:
                fail(
                    "INACTIVE_TERM_HAS_GRADIENT",
                    f"expected inactive but gradient norm reached {grad['max']:g}",
                )
        return failures

    if effective is None:
        fail(
            "MISSING_FROM_EFFECTIVE",
            "configured active term has no effective record; its contribution was "
            "never measured",
        )
        return failures
    evaluations = effective["evaluations"]
    if evaluations == 0:
        fail("NEVER_EVALUATED", "the term was configured but never evaluated")
        return failures
    if effective["finite_evaluations"] < evaluations:
        fail(
            "NONFINITE",
            f"{evaluations - effective['finite_evaluations']} of {evaluations} "
            "evaluations were non-finite",
        )
    nonzero = effective["nonzero_evaluations"]
    if nonzero == 0:
        fail(
            "ALWAYS_ZERO",
            f"all {evaluations} evaluation(s) contributed exactly zero; a nonzero "
            "configured weight did not make this term active",
        )
    elif nonzero / evaluations < min_nonzero_fraction:
        fail(
            "LOW_ACTIVATION",
            f"nonzero in {nonzero / evaluations:.3g} of evaluations; "
            f"required >= {min_nonzero_fraction:g}",
        )
    grad = effective["gradient_norm"]
    if grad is not None:
        if grad["nonfinite"] > 0:
            fail("NONFINITE_GRADIENT", f"{grad['nonfinite']} non-finite gradient norm(s)")
        if grad["count"] == 0 or grad["max"] == 0:
            fail(
                "ZERO_GRADIENT",
                "gradient norm was never positive; the term did not reach the parameters",
            )
    elif configured["claim"] is not None and require_gradient_for_claims:
        fail(
            "NO_GRADIENT_EVIDENCE",
            f"term claims {configured['claim']!r} but no gradient-norm evidence was "
            "recorded; a nonzero loss value alone does not show it constrains the fit",
        )
    return failures


def audit_objective(
    passport: Mapping[str, Any],
    *,
    min_nonzero_fraction: float = 0.0,
    require_gradient_for_claims: bool = True,
) -> dict[str, Any]:
    """Compare configured with effective objective; fail closed on any gap."""
    if not isinstance(passport, Mapping):
        raise ObjectiveAuditError("passport must be a JSON object")
    if passport.get("schema_version") != SCHEMA_VERSION:
        raise ObjectiveAuditError(f"schema_version must be {SCHEMA_VERSION}")
    if (
        not isinstance(min_nonzero_fraction, (int, float))
        or isinstance(min_nonzero_fraction, bool)
        or not 0 <= float(min_nonzero_fraction) <= 1
    ):
        raise ObjectiveAuditError("min_nonzero_fraction must be in [0, 1]")

    configured = _configured_terms(passport.get("configured_objective"))
    steps, effective = _effective_terms(passport.get("effective_objective"))

    rows: list[dict[str, Any]] = []
    for name, conf in configured.items():
        eff = effective.get(name)
        failures = _term_failures(
            name,
            conf,
            eff,
            min_nonzero_fraction=float(min_nonzero_fraction),
            require_gradient_for_claims=require_gradient_for_claims,
        )
        rows.append(
            {
                "name": name,
                "weight": conf["weight"],
                "expect": conf["expect"],
                "claim": conf["claim"],
                "effective": eff,
                "nonzero_fraction": (
                    eff["nonzero_evaluations"] / eff["evaluations"]
                    if eff and eff["evaluations"]
                    else None
                ),
                "status": "fail" if failures else "ok",
                "failures": failures,
            }
        )

    undeclared = []
    for name, eff in effective.items():
        if name in configured:
            continue
        active = eff["nonzero_evaluations"] > 0 or (
            eff["gradient_norm"] is not None and eff["gradient_norm"]["max"] > 0
        )
        if active:
            undeclared.append(
                {
                    "name": name,
                    "failures": [
                        {
                            "code": "UNDECLARED_ACTIVE_TERM",
                            "detail": "an active term the configured objective never declared",
                        }
                    ],
                    "effective": eff,
                }
            )

    failed = [r["name"] for r in rows if r["status"] == "fail"] + [
        u["name"] for u in undeclared
    ]
    verified_claims = sorted(
        r["claim"]
        for r in rows
        if r["claim"] is not None
        and r["status"] == "ok"
        and r["effective"] is not None
        and r["effective"]["gradient_norm"] is not None
    )
    active_expected = [r for r in rows if r["expect"] == "active"]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "verdict": VERDICT_FAIL if failed else VERDICT_OK,
        "run_id": passport.get("run_id"),
        "arm": passport.get("arm"),
        "passport_sha256": _canonical_sha256(passport),
        "steps": steps,
        "thresholds": {
            "min_nonzero_fraction": float(min_nonzero_fraction),
            "require_gradient_for_claims": bool(require_gradient_for_claims),
        },
        "summary": {
            "configured_terms": len(rows),
            "configured_active": len(active_expected),
            "effectively_active": sum(1 for r in active_expected if r["status"] == "ok"),
            "configured_inactive": sum(1 for r in rows if r["expect"] == "inactive"),
            "undeclared_active_terms": len(undeclared),
            "failed_terms": failed,
            "claims_with_gradient_evidence": verified_claims,
        },
        "terms": rows,
        "undeclared_terms": undeclared,
        "limitation": (
            "Verifies that each term behaved as the configuration says it should. "
            "It does not show the objective is well chosen, that a safety/topology "
            "term constrains the fit correctly, or that the result is readable."
        ),
    }


class ObjectiveTracker:
    """Accumulate the ``effective_objective`` block inside a training loop.

    Call :meth:`record` once per term evaluation with the term's **weighted
    contribution to the total loss as actually computed** (after any mask or
    early-return), never the configured weight. Terms the loop never calls
    still appear, with zero evaluations, so non-activation is explicit.
    """

    def __init__(self, configured_names: Iterable[str]) -> None:
        self._terms: dict[str, dict[str, Any]] = {}
        self.steps = 0
        for name in configured_names:
            self._ensure(_name(name, "term name"))

    def _ensure(self, name: str) -> dict[str, Any]:
        if name not in self._terms:
            self._terms[name] = {
                "evaluations": 0,
                "finite_evaluations": 0,
                "nonzero_evaluations": 0,
                "accumulated_contribution": 0.0,
                "grad_count": 0,
                "grad_sum": 0.0,
                "grad_max": 0.0,
                "grad_nonfinite": 0,
                "grad_reported": False,
            }
        return self._terms[name]

    def record(
        self,
        name: str,
        contribution: float,
        *,
        grad_norm: float | None = None,
    ) -> None:
        term = self._ensure(_name(name, "term name"))
        term["evaluations"] += 1
        value = float(contribution)
        if math.isfinite(value):
            term["finite_evaluations"] += 1
            term["accumulated_contribution"] += value
            if value != 0.0:
                term["nonzero_evaluations"] += 1
        if grad_norm is not None:
            term["grad_reported"] = True
            g = float(grad_norm)
            if math.isfinite(g) and g >= 0:
                term["grad_count"] += 1
                term["grad_sum"] += g
                term["grad_max"] = max(term["grad_max"], g)
            else:
                term["grad_nonfinite"] += 1

    def end_step(self) -> None:
        self.steps += 1

    def effective_objective(self) -> dict[str, Any]:
        terms = []
        for name, t in self._terms.items():
            terms.append(
                {
                    "name": name,
                    "evaluations": t["evaluations"],
                    "finite_evaluations": t["finite_evaluations"],
                    "nonzero_evaluations": t["nonzero_evaluations"],
                    "accumulated_contribution": t["accumulated_contribution"],
                    "gradient_norm": (
                        {
                            "count": t["grad_count"],
                            "sum": t["grad_sum"],
                            "max": t["grad_max"],
                            "nonfinite": t["grad_nonfinite"],
                        }
                        if t["grad_reported"]
                        else None
                    ),
                }
            )
        return {"steps": self.steps, "terms": terms}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--passport", required=True, help="objective passport JSON")
    parser.add_argument("--out", required=True, help="create-only JSON audit result")
    parser.add_argument(
        "--min-nonzero-fraction",
        type=float,
        default=0.0,
        help="minimum fraction of evaluations that must be nonzero (default: any)",
    )
    parser.add_argument(
        "--allow-missing-gradient",
        action="store_true",
        help="do not require gradient-norm evidence for terms that carry a claim",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        parser.error(f"result already exists: {out}")
    try:
        document = json.loads(Path(args.passport).read_text(encoding="utf-8"))
        result = audit_objective(
            document,
            min_nonzero_fraction=args.min_nonzero_fraction,
            require_gradient_for_claims=not args.allow_missing_gradient,
        )
    except (OSError, ValueError) as exc:  # JSON errors and ObjectiveAuditError
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")

    summary = result["summary"]
    print(
        f"{result['verdict']}: {summary['effectively_active']}/"
        f"{summary['configured_active']} configured-active terms effectively active"
        + (f"; failed: {', '.join(summary['failed_terms'])}" if summary["failed_terms"] else "")
    )
    return 0 if result["verdict"] == VERDICT_OK else 2


if __name__ == "__main__":
    raise SystemExit(main())
