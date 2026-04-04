from types import SimpleNamespace

from onec_help.knowledge import metadata_graph


class _DummyClient:
    def __init__(self, pages):
        self._pages = pages

    def scroll(self, **kwargs):
        if not self._pages:
            return [], None
        points = list(self._pages[0])
        filt = kwargs.get("scroll_filter")
        must = list(getattr(filt, "must", []) or [])
        for cond in must:
            key = getattr(cond, "key", None)
            match = getattr(cond, "match", None)
            value = getattr(match, "value", None)
            if not key:
                continue
            points = [pt for pt in points if (getattr(pt, "payload", {}) or {}).get(key) == value]
        return points, None

    def collection_exists(self, collection_name: str) -> bool:
        return True


def _point(point_id: str, **payload):
    return SimpleNamespace(id=point_id, payload=payload)


def test_guess_type_filter_from_query() -> None:
    assert metadata_graph._guess_type_filter("документ реализация", None) == "Document"
    assert metadata_graph._guess_type_filter("catalog products", None) == "Catalog"
    assert metadata_graph._guess_type_filter("произвольный запрос", None) is None


def test_search_metadata_substring_prefers_exact_then_startswith() -> None:
    client = _DummyClient(
        [
            [
                _point(
                    "1",
                    object_type="Document",
                    name="SalesOrder",
                    full_name="Документ.ЗаказПокупателя",
                ),
                _point("2", object_type="Document", name="Sales", full_name="Document.Sales"),
                _point(
                    "3", object_type="Document", name="MySalesArchive", full_name="ArchiveSales"
                ),
            ]
        ]
    )
    results = metadata_graph._search_metadata_substring(
        client,
        "onec_config_metadata",
        "sales",
        "Document",
        filt=None,
        limit=3,
        max_points=100,
    )
    assert [item["id"] for item in results] == ["2", "1", "3"]


def test_search_metadata_exact_matches_name_without_broad_scan() -> None:
    client = _DummyClient(
        [
            [
                _point(
                    "Catalog/Items",
                    config_version="3.0.184.16",
                    object_type="Catalog",
                    id="Catalog/Items",
                    name="Items",
                    full_name="Номенклатура",
                    path="Catalogs/Items",
                )
            ]
        ]
    )
    results = metadata_graph.search_metadata_exact(
        "Items",
        "Catalog",
        "3.0.184.16",
        client=client,
    )
    assert len(results) == 1
    assert results[0]["id"] == "Catalog/Items"


def test_search_metadata_fields_finds_requisite_in_exact_object() -> None:
    class _FieldsClient(_DummyClient):
        def __init__(self):
            super().__init__(
                [
                    [
                        _point(
                            "Document/РеализацияТоваровУслуг",
                            config_version="3.0.184.16",
                            object_type="Document",
                            id="Document/РеализацияТоваровУслуг",
                            name="РеализацияТоваровУслуг",
                            full_name="Документ.РеализацияТоваровУслуг",
                            path="Documents/РеализацияТоваровУслуг",
                            attributes={
                                "requisites": [
                                    {
                                        "name": "Организация",
                                        "synonym": "Организация",
                                        "type": "cfg:CatalogRef.Организации",
                                    }
                                ]
                            },
                        )
                    ]
                ]
            )

    results = metadata_graph.search_metadata_fields(
        "РеализацияТоваровУслуг",
        "Организация",
        config_version="3.0.184.16",
        client=_FieldsClient(),
    )
    assert len(results) == 1
    assert results[0]["object_id"] == "Document/РеализацияТоваровУслуг"
    assert results[0]["field_name"] == "Организация"


def test_metadata_slash_aliases_from_dot_query() -> None:
    assert "Document/РеализацияТоваровУслуг" in metadata_graph._metadata_slash_aliases_from_query(
        "Документ.РеализацияТоваровУслуг"
    )
    assert "Document/Foo" in metadata_graph._metadata_slash_aliases_from_query("Document.Foo")
    assert metadata_graph._metadata_slash_aliases_from_query("no_dot") == []


def test_search_metadata_fields_finds_tabular_requisite() -> None:
    class _TabClient(_DummyClient):
        def __init__(self):
            super().__init__(
                [
                    [
                        _point(
                            "Document/РеализацияТоваровУслуг",
                            config_version="3.0.184.16",
                            object_type="Document",
                            id="Document/РеализацияТоваровУслуг",
                            name="РеализацияТоваровУслуг",
                            full_name="Реализация",
                            attributes={
                                "tabular_sections": [
                                    {
                                        "name": "Товары",
                                        "synonym": "Товары",
                                        "requisites": [
                                            {
                                                "name": "Номенклатура",
                                                "synonym": "Номенклатура",
                                                "type": "cfg:CatalogRef.Номенклатура",
                                            }
                                        ],
                                    }
                                ]
                            },
                        )
                    ]
                ]
            )

    results = metadata_graph.search_metadata_fields(
        "РеализацияТоваровУслуг",
        "Номенклатура",
        config_version="3.0.184.16",
        client=_TabClient(),
    )
    assert len(results) == 1
    assert results[0]["field_name"] == "Номенклатура"
    assert results[0]["field_tabular_section"] == "Товары"
    assert results[0]["field_group"] == "tabular_section_requisites"


def test_search_metadata_fields_finds_register_dimension() -> None:
    class _RegClient(_DummyClient):
        def __init__(self):
            super().__init__(
                [
                    [
                        _point(
                            "InformationRegister/Тест",
                            config_version="3.0.184.16",
                            object_type="InformationRegister",
                            id="InformationRegister/Тест",
                            name="Тест",
                            attributes={
                                "dimensions": [
                                    {"name": "Измерение1", "synonym": "Изм", "type": "Строка"}
                                ],
                                "resources": [{"name": "Ресурс1", "synonym": "", "type": "Число"}],
                            },
                        )
                    ]
                ]
            )

    r1 = metadata_graph.search_metadata_fields(
        "Тест", "Измерение1", config_version="3.0.184.16", client=_RegClient()
    )
    assert len(r1) == 1
    assert r1[0]["field_group"] == "dimensions"
    r2 = metadata_graph.search_metadata_fields(
        "Тест", "Ресурс1", config_version="3.0.184.16", client=_RegClient()
    )
    assert r2[0]["field_group"] == "resources"


def test_search_metadata_exact_accepts_dot_notation() -> None:
    client = _DummyClient(
        [
            [
                _point(
                    "Document/РеализацияТоваровУслуг",
                    config_version="3.0.184.16",
                    object_type="Document",
                    id="Document/РеализацияТоваровУслуг",
                    name="РеализацияТоваровУслуг",
                    full_name="Реализация",
                )
            ]
        ]
    )
    results = metadata_graph.search_metadata_exact(
        "Документ.РеализацияТоваровУслуг",
        None,
        "3.0.184.16",
        client=client,
    )
    assert len(results) == 1
    assert results[0]["id"] == "Document/РеализацияТоваровУслуг"
