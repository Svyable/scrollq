import pytest

from scrollq import legibility_plan as lp


def _report():
    return {
        "tool": "scroliq-legibility",
        "threshold": 0.70,
        "scroll_id": "PHerc0813",
        "columns": [
            {
                "column": 1,
                "counted": True,
                "preserved_characters": 20,
                "legible_characters": 14,
                "lines": [
                    {
                        "line": 1,
                        "preserved_characters": 10,
                        "legible_characters": 8,
                    },
                    {
                        "line": 2,
                        "preserved_characters": 10,
                        "legible_characters": 6,
                    },
                ],
            },
            {
                "column": 2,
                "counted": True,
                "preserved_characters": 10,
                "legible_characters": 6,
                "lines": [
                    {
                        "line": 1,
                        "preserved_characters": 10,
                        "legible_characters": 6,
                    }
                ],
            },
            {
                "column": 3,
                "counted": False,
                "preserved_characters": 0,
                "legible_characters": 0,
                "lines": [],
            },
        ],
    }


def test_build_plan_surfaces_one_character_wins_and_column_rescues():
    plan = lp.build_plan(_report(), report_sha256="a" * 64)

    assert plan["legibility_report_sha256"] == "a" * 64
    assert plan["summary"]["one_character_line_rescues"] == 2
    assert plan["summary"]["one_character_column_rescues"] == 1
    assert plan["summary"]["columns_below_threshold"] == 1
    assert plan["column_rescue_queue"][0]["column"] == 2
    assert plan["column_rescue_queue"][0]["characters_needed"] == 1
    assert [(row["column"], row["line"]) for row in plan["line_rescue_queue"]] == [
        (1, 2),
        (2, 1),
    ]
    assert plan["fragile_lines"][0]["column"] == 1
    assert plan["fragile_lines"][0]["line"] == 1


def test_required_legible_is_stable_at_exact_seventy_percent():
    assert lp._required_legible(10, 0.70) == 7
    assert lp._required_legible(3, 0.70) == 3
    assert lp._required_legible(0, 0.70) == 0


def test_rescue_queue_sorts_by_cheapest_character_gain_then_evidence_size():
    report = _report()
    report["columns"][0]["lines"] = [
        {"line": 1, "preserved_characters": 20, "legible_characters": 12},
        {"line": 2, "preserved_characters": 10, "legible_characters": 6},
    ]
    report["columns"][0]["preserved_characters"] = 30
    report["columns"][0]["legible_characters"] = 18
    report["columns"][1]["counted"] = False

    plan = lp.build_plan(report)

    assert plan["line_rescue_queue"][0]["line"] == 2
    assert plan["line_rescue_queue"][0]["characters_needed"] == 1
    assert plan["line_rescue_queue"][1]["line"] == 1
    assert plan["line_rescue_queue"][1]["characters_needed"] == 2


def test_wrong_source_report_is_rejected():
    with pytest.raises(ValueError, match="scroliq-legibility"):
        lp.build_plan({"tool": "something-else", "threshold": 0.7, "columns": []})
