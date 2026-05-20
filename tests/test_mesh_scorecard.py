import json
from pathlib import Path
from unittest.mock import patch

from onec_help.knowledge.mesh_scorecard import (
    build_mesh_scorecard,
    compose_mesh_benchmark,
    load_mesh_benchmark,
)


def test_load_mesh_benchmark_filters_invalid_rows(tmp_path: Path) -> None:
    bench = tmp_path / "mesh_bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "id": "ok",
                    "profile": "exact_api_surface",
                    "runner": "task_context",
                    "query": "A",
                },
                {"id": "skip-no-profile", "runner": "task_context", "query": "B"},
                {"id": "skip-runner", "profile": "x", "runner": "other", "query": "C"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rows = load_mesh_benchmark(bench)
    assert len(rows) == 1
    assert rows[0]["id"] == "ok"


def test_build_mesh_scorecard_reports_cards_and_targets(tmp_path: Path) -> None:
    bench = tmp_path / "mesh_bench.json"
    external = tmp_path / "mesh_external.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "id": "exact",
                    "suite": "golden_local",
                    "profile": "exact_api_surface",
                    "runner": "task_context",
                    "query": "Документы.Sales.СоздатьДокумент",
                    "expected_route_kind": "platform_surface_chain",
                    "expected_candidate_contains": [
                        "ДокументМенеджер.<Имя документа>.СоздатьДокумент"
                    ],
                    "expected_help_contains": ["ДокументМенеджер.<Имя документа>.СоздатьДокумент"],
                },
                {
                    "id": "field",
                    "suite": "bulk_runtime",
                    "profile": "metadata_navigation",
                    "runner": "metadata_field",
                    "object_query": "AccumulationRegister.Продажи",
                    "field_query": "Стоимость",
                    "config_version": "1.0",
                    "expected_field_contains": ["Стоимость"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    external.write_text("[]", encoding="utf-8")

    with (
        patch(
            "onec_help.knowledge.mesh_scorecard.plan_1c_query",
            return_value={
                "route_kind": "platform_surface_chain",
                "resolver_kind": "platform_surface_chain",
                "candidate_nodes": [{"name": "ДокументМенеджер.<Имя документа>.СоздатьДокумент"}],
            },
        ),
        patch(
            "onec_help.knowledge.mesh_scorecard._fast_help_hits",
            return_value=["ДокументМенеджер.<Имя документа>.СоздатьДокумент"],
        ),
        patch("onec_help.knowledge.mesh_scorecard.search_metadata_exact", return_value=[]),
        patch("onec_help.knowledge.mesh_scorecard.get_workflow_path", return_value=[]),
        patch(
            "onec_help.knowledge.mesh_scorecard.search_metadata_fields",
            return_value=[{"field_name": "Стоимость"}],
        ),
        patch(
            "onec_help.knowledge.mesh_scorecard.get_qdrant_mesh_status",
            return_value={
                "exists": True,
                "api_members": 10,
                "api_edges": 20,
                "metadata_nodes": 3,
                "metadata_fields": 4,
                "guidance": 2,
            },
        ),
        patch(
            "onec_help.knowledge.mesh_scorecard.get_mcp_metrics",
            return_value={"total": 5, "last_hour": 2, "errors_total": 0},
        ),
        patch(
            "onec_help.knowledge.mesh_scorecard._generate_runtime_benchmark_cases",
            return_value=[],
        ),
    ):
        scorecard = build_mesh_scorecard(
            benchmark_path=bench, external_path=external, total_target=2
        )

    assert scorecard["summary"]["overall_case_pass_pct"] == 100.0
    assert scorecard["summary"]["suite_counts"]["golden_local"] == 1
    assert scorecard["summary"]["suite_counts"]["bulk_runtime"] == 1
    assert scorecard["cards"]["exact_api_surface"]["help_hit_pct"] == 100.0
    assert scorecard["cards"]["metadata_navigation"]["field_hit_pct"] == 100.0
    assert scorecard["suite_cards"]["golden_local"]["case_pass_pct"] == 100.0
    assert scorecard["runner_cards"]["metadata_field"]["field_hit_pct"] == 100.0
    assert scorecard["mesh_store"]["exists"] is True
    assert scorecard["mcp_metrics"]["total"] == 5
    assert scorecard["targets"]["overall_case_pass_pct"]["met"] is True


def test_compose_mesh_benchmark_merges_local_external_and_generated(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    external = tmp_path / "external.json"
    local.write_text(
        json.dumps(
            [
                {
                    "id": "local_case",
                    "suite": "golden_local",
                    "profile": "exact_api_surface",
                    "runner": "task_context",
                    "query": "HTTPСоединение.Получить",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    external.write_text(
        json.dumps(
            [
                {
                    "id": "web_case",
                    "suite": "golden_web",
                    "profile": "workflow_context",
                    "runner": "task_context",
                    "query": "как удалить временную таблицу в 1С",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    generated = [
        {
            "id": "bulk_case",
            "suite": "bulk_runtime",
            "profile": "metadata_navigation",
            "runner": "metadata_exact",
            "query": "Document.РеализацияТоваровУслуг",
            "config_version": "3.0.184.16",
        }
    ]
    with patch(
        "onec_help.knowledge.mesh_scorecard._generate_runtime_benchmark_cases",
        return_value=generated,
    ):
        rows = compose_mesh_benchmark(
            benchmark_path=local,
            external_path=external,
            total_target=3,
        )

    assert [row["id"] for row in rows] == ["local_case", "web_case", "bulk_case"]
