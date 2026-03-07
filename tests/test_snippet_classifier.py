"""Tests for snippet_classifier."""

from onec_help.snippet_classifier import classify_snippet_vs_reference


def test_snippet_code_dominates():
    """Code with BSL keywords and length > description → snippet."""
    code = """
Процедура Проверить()
    ХешОбъектаДоИзменения = ОбщегоНазначения.КонтрольнаяСуммаСтрокой(ЭтотОбъект);
    Возврат Истина;
КонецПроцедуры
"""
    assert classify_snippet_vs_reference("Проверка", "Коротко", code) == "snippet"


def test_reference_no_code():
    """No code or very short code → reference."""
    assert classify_snippet_vs_reference("Как сделать", "Длинное описание шагов", "") == "reference"
    assert classify_snippet_vs_reference("X", "Y", "short") == "reference"


def test_reference_title_pattern():
    """Instruction-like title with little code → reference."""
    assert (
        classify_snippet_vs_reference(
            "Как восстановить пароль 8.3.17",
            "Шаг 1... Шаг 2... Шаг 3... " * 20,
            "// 50 chars of code or so here x",
        )
        == "reference"
    )


def test_reference_description_dominates():
    """Long description, short code → reference."""
    long_desc = "Подробная инструкция. " * 50
    short_code = "Функция Х()\nВозврат 1;\nКонецФункции"  # ~40 chars
    assert classify_snippet_vs_reference("Тест", long_desc, short_code) == "reference"


def test_snippet_reference_title_but_lots_of_bsl():
    """Instruction title but substantial BSL code → snippet."""
    code = """
Процедура ВосстановитьПароль()
    Запрос = Новый Запрос;
    Запрос.Текст = "SELECT * FROM ...";
    Результат = Запрос.Выполнить();
    Для Каждого Строка Из Результат.Выгрузить() Цикл
        // обработка
    КонецЦикла;
КонецПроцедуры
"""
    assert classify_snippet_vs_reference("Как восстановить пароль", "Кратко", code) == "snippet"


def test_reference_code_short_description_long():
    """Code present but description dominates → reference."""
    code = "Функция Х()\nВозврат 1;\nКонецФункции" * 3
    long_desc = "Подробная инструкция с множеством шагов. " * 30
    assert classify_snippet_vs_reference("Руководство", long_desc, code) == "reference"


def test_snippet_code_share_over_45_percent():
    """Code share > 45% with BSL → snippet (line 76-78 branch)."""
    code = "Процедура Х()\nСообщить(1);\nКонецПроцедуры\n" * 25
    desc = "Короткое описание. " * 5
    assert classify_snippet_vs_reference("Тест", desc, code) == "snippet"


def test_reference_fallback_when_bsl_but_not_dominant():
    """BSL code but desc dominates and share < 45% → reference (lines 80-81)."""
    code = "Функция Х()\nВозврат;\nКонецФункции\n" * 10
    desc = "Длинное описание. " * 80
    assert classify_snippet_vs_reference("Разное", desc, code) == "reference"


def test_snippet_code_share_over_45_but_not_dominant():
    """Code share > 45%, BSL, but code_len <= desc_len*1.2 → snippet via line 76-78."""
    # code_len ~100, desc_len ~120: share > 0.45, but code not dominant
    code = "Процедура Х()\nСообщить(1);\nКонецПроцедуры\n" * 4  # ~100 chars, BSL
    desc = "Описание " * 15  # ~120 chars
    assert classify_snippet_vs_reference("Тест", desc, code) == "snippet"


def test_snippet_code_share_over_45_but_not_dominant_by_length() -> None:
    """Code share > 45%% and BSL but code_len <= desc_len*1.2 → snippet via line 76-78."""
    code = "Процедура Х()\nСообщить(1);\nКонецПроцедуры\n" * 4  # ~100 chars, BSL
    desc = "A" * 100  # same length so code_len not > desc_len*1.2
    assert classify_snippet_vs_reference("Test", desc, code) == "snippet"


def test_snippet_code_share_over_45_balanced_desc():
    """Code share > 45% with BSL, but code not > desc*1.2 → snippet via line 76-78."""
    code = "Процедура Х()\nСообщить(1);\nКонецПроцедуры\n" * 8  # ~200 chars, BSL
    desc = "Описание " * 25  # ~200 chars, balanced
    assert classify_snippet_vs_reference("Тест", desc, code) == "snippet"
