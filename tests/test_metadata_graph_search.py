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
