"""Шаблоны full_name менеджеров из справки 1С (structured help).

Строки совпадают с полем object_name в data/help_structured/api_objects.jsonl после ingest.
Используйте для get_1c_api_object / search_1c_api: подставьте имя объекта конфигурации вместо
плейсхолдера в угловых скобках (как в синтакс-помощнике платформы).
"""

from __future__ import annotations

# Ключ — object_type графа KD2 / Qdrant onec_config_metadata (англ. тип).
TEMPLATE_BY_METADATA_OBJECT_TYPE: dict[str, str] = {
    "Document": "ДокументМенеджер.<Имя документа>",
    "Catalog": "СправочникМенеджер.<Имя справочника>",
    "Enum": "ПеречислениеМенеджер.<Имя перечисления>",
    "InformationRegister": "РегистрСведенийМенеджер.<Имя регистра сведений>",
    "AccumulationRegister": "РегистрНакопленияМенеджер.<Имя регистра накопления>",
    "ChartOfCharacteristicTypes": "ПланВидовХарактеристикМенеджер.<Имя плана видов характеристик>",
    "ChartOfCalculationTypes": "ПланВидовРасчетаМенеджер.<Имя плана видов расчета>",
    "ChartOfAccounts": "ПланСчетовМенеджер.<Имя плана счетов>",
    "ExchangePlan": "ПланОбменаМенеджер.<Имя плана обмена>",
    "BusinessProcess": "БизнесПроцессМенеджер.<Имя бизнес-процесса>",
    "Task": "ЗадачаМенеджер.<Имя задачи>",
}


def manager_template_for_metadata_object_type(object_type: str | None) -> str | None:
    if not object_type:
        return None
    return TEMPLATE_BY_METADATA_OBJECT_TYPE.get(object_type)


def manager_help_hint_line() -> str:
    """Одна строка для подсказок MCP: без перечисления конкретных методов."""
    doc = TEMPLATE_BY_METADATA_OBJECT_TYPE["Document"]
    cat = TEMPLATE_BY_METADATA_OBJECT_TYPE["Catalog"]
    return (
        f"Справка по методам и свойствам менеджера (платформа): "
        f'get_1c_api_object("{doc}") / get_1c_api_object("{cat}") — '
        f"подставьте имя объекта из конфигурации вместо текста в угловых скобках; "
        f"полный набор шаблонов: модуль onec_help.knowledge.platform_help_manager_templates."
    )
