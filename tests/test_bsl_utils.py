"""Tests for bsl_utils."""

from pathlib import Path

from onec_help.knowledge.bsl_utils import (
    extract_func_name,
    extract_procedures_and_functions,
    get_functions,
)

FIXTURE_OBJECT_MODULE = (
    Path(__file__).resolve().parent / "fixtures" / "bsl_sample" / "ObjectModule.bsl"
)


def test_get_functions_splits_by_end_markers() -> None:
    """get_functions splits on КонецПроцедуры and КонецФункции."""
    code = """
// prelude
Процедура П1()
    Сообщить(1);
КонецПроцедуры

Функция Ф1()
    Возврат Истина;
КонецФункции
// tail
"""
    parts = get_functions(code)
    assert len(parts) >= 5  # prelude, КонецПроцедуры, block, КонецФункции, tail


def test_extract_func_name_procedure() -> None:
    """extract_func_name extracts procedure name."""
    code = "Процедура Подписать(Данные, Сертификат)\n    Возврат;\nКонецПроцедуры"
    assert extract_func_name(code) == "Подписать"


def test_extract_func_name_function() -> None:
    """extract_func_name extracts function name."""
    code = "Функция ПолучитьЗначение(Параметр)\n    Возврат 0;\nКонецФункции"
    assert extract_func_name(code) == "ПолучитьЗначение"


def test_extract_func_name_none_for_empty() -> None:
    """extract_func_name returns None when no declaration."""
    assert extract_func_name("Сообщить(1);") is None


def test_extract_procedures_and_functions() -> None:
    """extract_procedures_and_functions returns list of {name, code, line_start}."""
    code = """
Процедура П1()
    Сообщить(1);
КонецПроцедуры

Функция Ф1()
    Возврат Истина;
КонецФункции
"""
    items = extract_procedures_and_functions(code)
    assert len(items) >= 1
    names = [i["name"] for i in items]
    assert "П1" in names or "Ф1" in names
    for item in items:
        assert "name" in item
        assert "code" in item
        assert "line_start" in item
        assert "Процедура" in item["code"] or "Функция" in item["code"]


def test_extract_procedures_and_functions_skips_nameless_block() -> None:
    """Block with Procedure but no name is skipped (line 42: if name)."""
    code = """
Процедура ()
    Сообщить(1);
КонецПроцедуры

Функция Нормальная()
    Возврат 1;
КонецФункции
"""
    items = extract_procedures_and_functions(code)
    assert len(items) == 1
    assert items[0]["name"] == "Нормальная"


def test_extract_procedures_and_functions_skips_whitespace_blocks() -> None:
    """Whitespace-only blocks between markers are skipped (continue branch)."""
    code = """
Процедура П1()
    X;
КонецПроцедуры

КонецПроцедуры

Функция Ф2()
    Y;
КонецФункции
"""
    items = extract_procedures_and_functions(code)
    # П1 and possibly Ф2; the empty block between two КонецПроцедуры is skipped
    assert len(items) >= 1


def test_get_functions_on_real_object_module() -> None:
    """get_functions and extract_func_name work on real ObjectModule.bsl fixture."""
    content = FIXTURE_OBJECT_MODULE.read_text(encoding="utf-8")
    parts = get_functions(content)
    assert len(parts) > 1
    # Should find ПолучитьВсе, НайтиПоОтпечатку, etc.
    items = extract_procedures_and_functions(content)
    names = [i["name"] for i in items if i["name"]]
    assert "ПолучитьВсе" in names or "НайтиПоОтпечатку" in names
