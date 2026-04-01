from types import SimpleNamespace

from onec_help import metadata_graph


class _DummyClient:
    def __init__(self, pages):
        self._pages = pages
        self._index = 0

    def scroll(self, **kwargs):
        if self._index >= len(self._pages):
            return [], None
        points = self._pages[self._index]
        self._index += 1
        offset = self._index if self._index < len(self._pages) else None
        return points, offset


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
                _point("1", object_type="Document", name="SalesOrder", full_name="Документ.ЗаказПокупателя"),
                _point("2", object_type="Document", name="Sales", full_name="Document.Sales"),
                _point("3", object_type="Document", name="MySalesArchive", full_name="ArchiveSales"),
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
