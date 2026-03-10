from pathlib import Path
from typing import Any

from onec_help import metadata_graph
from onec_help.config_crawler import ConfigObject, CrawlResult


class FakeQdrantClient:
    # Minimal subset of QdrantClient API we rely on
    def __init__(self) -> None:
        self.recreated: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self._scroll_data: list[Any] = []

    def recreate_collection(self, collection_name: str, vectors_config: Any, **kwargs: Any) -> None:
        self.recreated.append(
            {
                "collection_name": collection_name,
                "vectors_config": vectors_config,
                "kwargs": kwargs,
            }
        )

    def upsert(self, collection_name: str, points: list[Any], **kwargs: Any) -> None:
        self.upserts.append(
            {"collection_name": collection_name, "points": points, "kwargs": kwargs}
        )

    def set_scroll_data(self, points: list[Any]) -> None:
        self._scroll_data = points

    def scroll(self, collection_name: str, scroll_filter=None, limit: int = 64, offset=None):
        # Ignore collection_name/scroll_filter in tests; return all in one batch.
        if not self._scroll_data:
            return [], None
        return self._scroll_data, None


def _dummy_crawl_for_build() -> CrawlResult:
    obj1 = ConfigObject(
        id="Document/Sales",
        object_type="Document",
        name="Sales",
        full_name="Реализация товаров и услуг",
        path="Documents/Sales",
        attributes={},
    )
    obj2 = ConfigObject(
        id="Catalog/Items",
        object_type="Catalog",
        name="Items",
        full_name="Номенклатура",
        path="Catalogs/Items",
        attributes={},
    )
    return CrawlResult(
        root_dir=Path("/cfg"),
        config_name="CfgName",
        config_version="2.0.1.0",
        platform_version="8.5.1.1150",
        objects=[obj1, obj2],
        relations=[],
    )


def test_build_metadata_graph_from_crawl_uses_embed_and_upsert() -> None:
    crawl = _dummy_crawl_for_build()
    client = FakeQdrantClient()

    def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        # Return simple 2D vectors to keep tests deterministic.
        return [[float(i), float(len(t))] for i, t in enumerate(texts)]

    inserted = metadata_graph.build_metadata_graph_from_crawl(
        crawl,
        client=client,
        embed_batch=fake_embed_batch,
        collection_name="test_metadata",
        recreate=True,
    )

    # Two objects => two points
    assert inserted == 2
    assert len(client.upserts) == 1
    upsert_call = client.upserts[0]
    assert upsert_call["collection_name"] == "test_metadata"
    points = upsert_call["points"]
    assert len(points) == 2
    # Payload should include config_version and object_type/name
    payloads = [p.payload for p in points]
    assert {p["name"] for p in payloads} == {"Sales", "Items"}
    assert all(p["config_version"] == "2.0.1.0" for p in payloads)


def test_build_metadata_graph_from_crawl_no_bm25_single_vector() -> None:
    """With use_bm25=False, points use plain list vector (no sparse)."""
    crawl = _dummy_crawl_for_build()
    client = FakeQdrantClient()

    def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0], [0.0, 1.0]]

    inserted = metadata_graph.build_metadata_graph_from_crawl(
        crawl,
        client=client,
        embed_batch=fake_embed_batch,
        collection_name="test_meta",
        recreate=True,
        use_bm25=False,
    )
    assert inserted == 2
    points = client.upserts[0]["points"]
    for p in points:
        v = getattr(p, "vector", None)
        assert isinstance(v, list), "vector should be list when use_bm25=False"
    recreated = client.recreated[0]
    assert "sparse_vectors_config" not in recreated.get("kwargs", {})


def test_search_metadata_by_name_uses_scroll_and_filters() -> None:
    """search_metadata_by_name should filter by config_version, type and substring in name/full_name."""
    crawl = _dummy_crawl_for_build()
    client = FakeQdrantClient()

    class P:
        def __init__(self, payload: dict, pid: int) -> None:
            self.payload = payload
            self.id = pid

    pts = [
        P(
            {
                "id": "Document/Sales",
                "config_name": crawl.config_name,
                "config_version": crawl.config_version,
                "object_type": "Document",
                "name": "Sales",
                "full_name": "Реализация",
            },
            1,
        ),
        P(
            {
                "id": "Catalog/Items",
                "config_name": crawl.config_name,
                "config_version": crawl.config_version,
                "object_type": "Catalog",
                "name": "Items",
                "full_name": "Номенклатура",
            },
            2,
        ),
    ]
    client.set_scroll_data(pts)

    results = metadata_graph.search_metadata_by_name(
        "Item", type_filter="Catalog", config_version=crawl.config_version, client=client
    )
    assert len(results) == 1
    assert results[0]["id"] == "Catalog/Items"


def test_get_metadata_object_uses_scroll() -> None:
    """get_metadata_object finds object by id using scroll."""
    crawl = _dummy_crawl_for_build()
    client = FakeQdrantClient()

    class P:
        def __init__(self, payload: dict, pid: int) -> None:
            self.payload = payload
            self.id = pid

    pts = [
        P(
            {
                "id": "Document/Sales",
                "config_name": crawl.config_name,
                "config_version": crawl.config_version,
                "object_type": "Document",
                "name": "Sales",
            },
            1,
        )
    ]
    client.set_scroll_data(pts)

    obj = metadata_graph.get_metadata_object("Document/Sales", client=client)
    assert obj is not None
    assert obj["name"] == "Sales"
    assert obj["id"] == "Document/Sales"
