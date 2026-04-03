"""Tests for structured help scorecard and stopping metrics."""

import json
from pathlib import Path
from unittest.mock import patch

from onec_help.knowledge.help_structured_scorecard import (
    build_structured_help_scorecard,
    load_structured_benchmark,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def test_load_structured_benchmark_filters_invalid_rows(tmp_path: Path) -> None:
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "query": "HTTPСоединение",
                    "entity": "object",
                    "expected_full_name": "HTTPСоединение",
                },
                {"query": "", "entity": "member", "expected_full_name": "bad"},
                {"query": "x", "entity": "weird", "expected_full_name": "bad"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rows = load_structured_benchmark(bench)
    assert rows == [
        {
            "query": "HTTPСоединение",
            "entity": "object",
            "expected_full_name": "HTTPСоединение",
            "expected_kind": "",
        }
    ]


def test_build_structured_help_scorecard_reports_metrics(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "api_objects.jsonl",
        [
            {
                "id": 1,
                "object_name": "HTTPСоединение",
                "full_name": "HTTPСоединение",
                "kind": "type",
                "summary": "Объект для HTTP.",
                "availability": "Сервер",
                "topic_path": "HTTPConnection.html",
                "title": "HTTPСоединение",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "api_members.jsonl",
        [
            {
                "id": 2,
                "owner_name": "HTTPСоединение",
                "full_name": "HTTPСоединение.Получить",
                "kind": "method",
                "summary": "Получает ресурс.",
                "syntax": "HTTPСоединение.Получить(<Адрес>)",
                "params": [{"name": "Адрес", "type": "Строка", "description": ""}],
                "returns": "HTTPОтвет",
                "availability": "Сервер",
                "topic_path": "Get.html",
                "title": "HTTPСоединение.Получить",
            },
            {
                "id": 3,
                "owner_name": "HTTPСоединение",
                "full_name": "HTTPСоединение.Таймаут",
                "kind": "property",
                "summary": "Таймаут.",
                "syntax": "",
                "params": [],
                "returns": "",
                "availability": "Сервер",
                "topic_path": "Timeout.html",
                "title": "HTTPСоединение.Таймаут",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "api_examples.jsonl",
        [
            {
                "id": 4,
                "full_name": "HTTPСоединение.Получить",
                "code": 'Ответ = Соединение.Получить("/");',
                "topic_path": "Get.html",
                "title": "Пример",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "api_links.jsonl",
        [
            {
                "source_full_name": "HTTPСоединение.Получить",
                "target_name": "HTTPОтвет",
                "topic_path": "Get.html",
            }
        ],
    )
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "query": "HTTPСоединение.Получить",
                    "entity": "member",
                    "expected_full_name": "HTTPСоединение.Получить",
                    "expected_kind": "method",
                },
                {
                    "query": "HTTPСоединение",
                    "entity": "object",
                    "expected_full_name": "HTTPСоединение",
                    "expected_kind": "type",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_unpacked",
            return_value=[],
        ),
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_index",
            return_value=[
                {"path": "HTTPConnection.html", "entity_type": "topic"},
                {"path": "Get.html", "entity_type": "topic"},
                {"path": "Timeout.html", "entity_type": "topic"},
                {"path": "ExtraTopic.html", "entity_type": "topic"},
            ],
        ),
    ):
        scorecard = build_structured_help_scorecard(snapshot_dir=tmp_path, benchmark_path=bench)
    assert scorecard["counts"]["members"] == 2
    assert scorecard["coverage"]["summary_pct"] == 100.0
    assert scorecard["coverage"]["method_like_params_pct"] == 100.0
    assert scorecard["path_coverage"]["help_only_total"] == 1
    assert scorecard["benchmark"]["exact_top1_pct"] == 100.0
    assert scorecard["benchmark"]["structured_sufficient_pct"] == 100.0
    assert scorecard["targets"]["exact_top1_pct"]["met"] is True


def test_build_structured_help_scorecard_uses_member_name_for_bare_query(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "api_objects.jsonl", [])
    _write_jsonl(
        tmp_path / "api_members.jsonl",
        [
            {
                "id": 1,
                "owner_name": "Глобальный контекст",
                "member_name": "Формат",
                "full_name": "Глобальный контекст.Формат",
                "kind": "method",
                "summary": "Формирует представление значения.",
                "syntax": "Формат(<Значение>)",
                "params": [{"name": "<Значение>", "type": "Произвольный", "description": ""}],
                "returns": "Строка",
                "availability": "Клиент, сервер",
                "topic_path": "Format.html",
                "title": "Глобальный контекст.Формат",
            },
            {
                "id": 2,
                "owner_name": "Картинка",
                "member_name": "Формат",
                "full_name": "Картинка.Формат",
                "kind": "method",
                "summary": "Получает формат картинки.",
                "syntax": "",
                "params": [],
                "returns": "",
                "availability": "",
                "topic_path": "PictureFormat.html",
                "title": "Картинка.Формат",
            },
        ],
    )
    _write_jsonl(tmp_path / "api_examples.jsonl", [])
    _write_jsonl(tmp_path / "api_links.jsonl", [])
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "query": "Формат",
                    "entity": "member",
                    "expected_full_name": "Глобальный контекст.Формат",
                    "expected_kind": "method",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_unpacked",
            return_value=[],
        ),
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_index",
            return_value=[],
        ),
    ):
        scorecard = build_structured_help_scorecard(snapshot_dir=tmp_path, benchmark_path=bench)
    assert scorecard["benchmark"]["exact_top1_pct"] == 100.0


def test_build_structured_help_scorecard_accepts_bare_builtin_expected_name(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "api_objects.jsonl", [])
    _write_jsonl(
        tmp_path / "api_members.jsonl",
        [
            {
                "full_name": "Встроенные функции языка.Формат",
                "member_name": "Формат",
                "owner_name": "Встроенные функции языка",
                "kind": "function",
                "summary": "Форматирует значение.",
                "syntax": "Формат(<Значение>, <ФорматСтрока>)",
                "params": [{"name": "<Значение>", "type": "Произвольный", "description": ""}],
                "returns": "Строка",
                "availability": "Сервер, толстый клиент, тонкий клиент.",
                "topic_path": "8.3.27/shcntx_ru/objects/Script functions/methods/catalog994/Format971.html",
            }
        ],
    )
    _write_jsonl(tmp_path / "api_examples.jsonl", [])
    _write_jsonl(tmp_path / "api_links.jsonl", [])
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "query": "Формат",
                    "entity": "member",
                    "expected_full_name": "Формат",
                    "expected_kind": "function",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_unpacked",
            return_value=[
                {
                    "path": "8.3.27/shcntx_ru/objects/Script functions/methods/catalog994/Format971.html",
                    "entity_type": "topic",
                }
            ],
        ),
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_index",
            return_value=[],
        ),
    ):
        scorecard = build_structured_help_scorecard(snapshot_dir=tmp_path, benchmark_path=bench)
    assert scorecard["benchmark"]["exact_top1_pct"] == 100.0
    assert scorecard["cases"][0]["top_hit_full_name"] == "Встроенные функции языка.Формат"


def test_build_structured_help_scorecard_prefers_unpacked_paths(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "api_objects.jsonl", [])
    _write_jsonl(
        tmp_path / "api_members.jsonl",
        [
            {
                "id": 1,
                "owner_name": "HTTPСоединение",
                "member_name": "Получить",
                "full_name": "HTTPСоединение.Получить",
                "kind": "method",
                "summary": "Получает ресурс.",
                "syntax": "Получить()",
                "params": [{"name": "x", "type": "Строка", "description": ""}],
                "returns": "HTTPОтвет",
                "availability": "Сервер",
                "topic_path": "8.3.27/shcntx_ru/Get.html",
                "title": "HTTPСоединение.Получить",
            }
        ],
    )
    _write_jsonl(tmp_path / "api_examples.jsonl", [])
    _write_jsonl(tmp_path / "api_links.jsonl", [])
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "query": "HTTPСоединение.Получить",
                    "entity": "member",
                    "expected_full_name": "HTTPСоединение.Получить",
                    "expected_kind": "method",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_unpacked",
            return_value=[{"path": "8.3.27/shcntx_ru/Get.html", "entity_type": "topic"}],
        ),
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_index",
            return_value=[{"path": "Ignored.html", "entity_type": "topic"}],
        ),
    ):
        scorecard = build_structured_help_scorecard(snapshot_dir=tmp_path, benchmark_path=bench)
    assert scorecard["path_coverage"]["source"] == "unpacked_html"
    assert scorecard["path_coverage"]["path_coverage_pct"] == 100.0


def test_build_structured_help_scorecard_classifies_help_only_buckets(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "api_objects.jsonl", [])
    _write_jsonl(tmp_path / "api_members.jsonl", [])
    _write_jsonl(tmp_path / "api_examples.jsonl", [])
    _write_jsonl(tmp_path / "api_links.jsonl", [])
    bench = tmp_path / "bench.json"
    bench.write_text("[]", encoding="utf-8")
    with (
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_unpacked",
            return_value=[
                {"path": "8.3.27/shclang_ru/source_format.html", "entity_type": "topic"},
                {"path": "8.3.27/shlang_ru/expressions.html", "entity_type": "topic"},
                {"path": "8.3.27/shquery_ru/query_cast.html", "entity_type": "topic"},
                {"path": "8.3.27/shcntx_ru/tables/table5.html", "entity_type": "topic"},
                {"path": "8.3.27/shcntx_ru/objects/catalog56.html", "entity_type": "topic"},
                {"path": "8.3.27/shcntx_ru/forms/SomeForm.html", "entity_type": "topic"},
            ],
        ),
        patch(
            "onec_help.knowledge.help_structured_scorecard.iter_help_topics_from_index",
            return_value=[],
        ),
    ):
        scorecard = build_structured_help_scorecard(snapshot_dir=tmp_path, benchmark_path=bench)
    assert scorecard["path_coverage"]["help_only_buckets"] == {
        "language": 2,
        "query": 1,
        "tables": 1,
        "object_overview": 1,
        "forms": 1,
    }
