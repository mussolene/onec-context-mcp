from __future__ import annotations


def test_resolve_platform_surface_query_for_document_method() -> None:
    from onec_help.knowledge.language_resolver import resolve_platform_surface_api_query

    resolved = resolve_platform_surface_api_query("Документы.РеализацияТоваровУслуг.СоздатьДокумент")

    assert resolved["resolver_kind"] == "platform_surface_chain"
    assert resolved["family"] == "Документы"
    names = [item["name"] for item in resolved["candidates"]]
    assert "ДокументМенеджер.<Имя документа>.СоздатьДокумент" in names
    assert "ДокументыМенеджер.<Имя документа>" in names


def test_resolve_platform_surface_query_for_constant_method() -> None:
    from onec_help.knowledge.language_resolver import resolve_platform_surface_api_query

    resolved = resolve_platform_surface_api_query("Константы.ИспользоватьСкидки.Получить")

    names = [item["name"] for item in resolved["candidates"]]
    assert "КонстантаМенеджер.<Имя константы>.Получить" in names
    assert "КонстантыМенеджер.<Имя константы>" in names


def test_resolve_platform_surface_query_strips_global_context_prefix() -> None:
    from onec_help.knowledge.language_resolver import resolve_platform_surface_api_query

    resolved = resolve_platform_surface_api_query(
        "Глобальный контекст.Документы.РеализацияТоваровУслуг.СоздатьДокумент"
    )

    assert resolved["normalized_query"] == "Документы.РеализацияТоваровУслуг.СоздатьДокумент"
    assert resolved["family"] == "Документы"

