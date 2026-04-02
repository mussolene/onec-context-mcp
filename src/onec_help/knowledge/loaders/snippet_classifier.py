"""Classify community content (HelpF, FastCode) as snippet vs reference.

snippet: code-centric example (Процедура, Функция, executable 1C code)
reference: instructional text, how-to, guide (description dominates, little/no code)
"""

from __future__ import annotations

import re
from typing import Literal

# Типичные конструкции 1С/BSL — признак реального сниппета
_BSL_KEYWORDS = (
    "Процедура",
    "Функция",
    "КонецПроцедуры",
    "КонецФункции",
    "Запрос",
    "Выполнить",
    "Новый ",
    "Возврат",
    "Для ",
    "Цикл",
    "КонецЦикла",
    "Если ",
    "Тогда",
    "КонецЕсли",
    "Пока ",
    "Попытка",
    "Исключение",
)

# Паттерны заголовков инструкций/справочников
_REFERENCE_TITLE_RE = re.compile(
    r"^(как\s+|инструкция|руководство|настройка|восстановление|установка|"
    r"руководство|методика|решение\s+проблемы|ошибка|troubleshooting)",
    re.I,
)


def classify_snippet_vs_reference(
    title: str,
    description: str,
    code_snippet: str,
) -> Literal["snippet", "reference"]:
    """Classify item as snippet (code example) or reference (instructional text).

    Returns "snippet" when code dominates and looks like 1C/BSL.
    Returns "reference" when description dominates or code is absent/trivial.
    """
    code = (code_snippet or "").strip()
    desc = (description or "").strip()
    title_ = (title or "").strip()
    code_len = len(code)
    desc_len = len(desc)

    # Нет кода или очень короткий — инструкция
    if code_len < 80:
        return "reference"

    # Явные паттерны заголовка — справочная инструкция
    if _REFERENCE_TITLE_RE.search(title_):
        # Но если код большой и с BSL — всё равно сниппет
        code_has_bsl = any(kw in code for kw in _BSL_KEYWORDS)
        if not (code_has_bsl and code_len > desc_len):
            return "reference"

    # Признаки BSL-кода
    code_has_bsl = any(kw in code for kw in _BSL_KEYWORDS)

    # Код доминирует: много BSL, длина кода больше описания
    if code_has_bsl and code_len > desc_len * 1.2:
        return "snippet"

    # Доля кода в общем объёме
    total = code_len + desc_len
    if total > 0 and code_len / total > 0.45 and code_has_bsl:
        return "snippet"

    # Иначе — справочная инструкция (текст важнее кода)
    return "reference"
