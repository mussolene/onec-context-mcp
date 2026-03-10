"""Metadata graph for 1C configuration objects.

This module is responsible for turning `CrawlResult` from `config_crawler`
into Qdrant collections and providing a small search/read API for MCP tools.

Design goals:
- Keep responsibilities separate from help index (`indexer.py`) and memory.
- Store per‑configuration metadata (config_name, config_version, platform_version).
- Allow simple name/typed search and lookup of a single object with its relations.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from typing import Any, cast

from . import env_config
from .config_crawler import ConfigObject, ConfigRelation, CrawlResult

# Типы объектов метаданных по-русски (для понимания конфигурации и единообразия с справкой).
_OBJECT_TYPE_RU: dict[str, str] = {
    "Document": "Документ",
    "Catalog": "Справочник",
    "Report": "Отчёт",
    "DataProcessor": "Обработка",
    "Form": "Форма",
    "Command": "Команда",
    "Subsystem": "Подсистема",
    "CommonModule": "Общий модуль",
    "SessionParameter": "Параметр сеанса",
    "Role": "Роль",
    "AccumulationRegister": "Регистр накопления",
    "InformationRegister": "Регистр сведений",
    "AccountingRegister": "Регистр бухгалтерии",
    "CalculationRegister": "Регистр расчёта",
    "Enum": "Перечисление",
    "ChartOfAccounts": "План счетов",
    "ChartOfCalculationTypes": "План видов расчёта",
    "ChartOfAccountsCharacteristicTypes": "План видов характеристик",
    "BusinessProcess": "Бизнес-процесс",
    "Task": "Задача",
    "ExchangePlan": "План обмена",
    "FilterCriterion": "Критерий отбора",
    "SettingsStorage": "Хранилище настроек",
    "CommonAttribute": "Общий реквизит",
    "CommonForm": "Общая форма",
    "Template": "Макет",
    "WebService": "Веб-сервис",
    "HTTPService": "HTTP-сервис",
    "WSReference": "WS-ссылка",
    "EventSubscription": "Подписка на событие",
    "ExternalDataSource": "Внешний источник данных",
    "Interface": "Интерфейс",
    "FunctionalOption": "Функциональная опция",
    "DefinedType": "Определяемый тип",
    "Configuration": "Конфигурация",
    "Language": "Язык",
    "Style": "Стиль",
    "Sequence": "Последовательность",
}

# Префиксы типов из выгрузки (cfg:/xs:) → читаемое название по справке 1С (СправочникСсылка, Строка, Число и т.д.).
# Ref = ссылка: CatalogRef → СправочникСсылка, DocumentRef → ДокументСсылка, EnumRef → ПеречислениеСсылка.
_TYPE_REF_PREFIX_RU: dict[str, str] = {
    "cfg:CatalogRef.": "СправочникСсылка.",
    "cfg:DocumentRef.": "ДокументСсылка.",
    "cfg:EnumRef.": "ПеречислениеСсылка.",
    "cfg:ChartOfAccountsRef.": "ПланСчетовСсылка.",
    "cfg:DataProcessorRef.": "ОбработкаСсылка.",
    "cfg:ReportRef.": "ОтчетСсылка.",
    "CatalogRef.": "СправочникСсылка.",
    "DocumentRef.": "ДокументСсылка.",
    "EnumRef.": "ПеречислениеСсылка.",
    "ChartOfAccountsRef.": "ПланСчетовСсылка.",
    "DataProcessorRef.": "ОбработкаСсылка.",
    "ReportRef.": "ОтчетСсылка.",
}
_XS_TYPE_RU: dict[str, str] = {
    "xs:string": "Строка",
    "xs:decimal": "Число",
    "xs:boolean": "Булево",
    "xs:dateTime": "Дата и время",
    "xs:date": "Дата",
    "xs:integer": "Целое число",
}


def format_type_readable(
    raw_type: str,
    *,
    length: int | None = None,
    precision: tuple[int, int] | None = None,
    append_raw_in_brackets: bool = False,
) -> str:
    """Преобразует сырой тип из выгрузки (cfg:..., xs:...) в читаемый вид на русском.

    - Ref-типы: CatalogRef.Организации → СправочникСсылка.Организации (по справке 1С).
    - xs:string → Строка; при length — Строка(N). xs:decimal → Число; при precision — Число(N,M).
    - append_raw_in_brackets: добавить в скобках исходный тип для индексирования.
    """
    if not raw_type or not isinstance(raw_type, str):
        return ""
    t = raw_type.strip()
    out: str = ""
    for prefix, ru_prefix in _TYPE_REF_PREFIX_RU.items():
        if t.startswith(prefix):
            name = t[len(prefix) :].strip()
            out = f"{ru_prefix}{name}" if name else ru_prefix.rstrip(".")
            break
    if not out and t in _XS_TYPE_RU:
        out = _XS_TYPE_RU[t]
        if out == "Строка" and length is not None and length > 0:
            out = f"Строка({length})"
        elif out == "Число" and precision is not None and len(precision) >= 2:
            out = f"Число({precision[0]},{precision[1]})"
    if not out:
        # Попытка извлечь длину/точность из выгрузки (String(150), Number(10,2) и т.д.)
        if "string" in t.lower() or "String" in t:
            m = re.search(r"\((\d+)\)", t)
            out = f"Строка({m.group(1)})" if m else "Строка"
        elif "decimal" in t.lower() or "Number" in t.lower():
            m = re.search(r"\((\d+)\s*,\s*(\d+)\)", t)
            out = f"Число({m.group(1)},{m.group(2)})" if m else "Число"
        else:
            out = t
    if append_raw_in_brackets and t and out != t:
        out = f"{out} ({t})"
    return out


def format_requisite_type_display(
    req: dict[str, Any],
    *,
    append_raw_in_brackets: bool = True,
) -> str:
    """Форматирует тип реквизита для вывода: один тип, несколько (union) или определяемый тип.

    req: словарь реквизита с полями type, опционально types, defined_type, length.
    Возвращает строку на русском: «Строка(100)», «Тип1 или Тип2», «Определяемый тип: Имя (Тип1, Тип2)».
    """
    if not isinstance(req, dict):
        return ""
    defined = req.get("defined_type") if isinstance(req.get("defined_type"), str) else None
    types_list = req.get("types")
    if isinstance(types_list, list) and len(types_list) > 1:
        parts = []
        for t in types_list:
            if t and isinstance(t, str):
                disp = format_type_readable(
                    t,
                    length=req.get("length") if isinstance(req.get("length"), int) else None,
                    append_raw_in_brackets=False,
                )
                if disp:
                    parts.append(disp)
        if defined:
            return f"Определяемый тип: {defined} ({', '.join(parts)})"
        return " или ".join(parts)
    if defined:
        inner: list[str] = []
        if types_list:
            for t in types_list:
                if t and isinstance(t, str):
                    length = req.get("length") if "string" in t.lower() and isinstance(req.get("length"), int) else None
                    inner.append(format_type_readable(t, length=length, append_raw_in_brackets=False))
        if not inner and (req.get("type") or "").strip():
            length = req.get("length") if isinstance(req.get("length"), int) else None
            inner.append(
                format_type_readable(
                    (req.get("type") or "").strip(),
                    length=length,
                    append_raw_in_brackets=False,
                )
            )
        if inner:
            return f"Определяемый тип: {defined} ({', '.join(inner)})"
    main = (req.get("type") or "").strip()
    if not main:
        return ""
    length = req.get("length") if isinstance(req.get("length"), int) else None
    out = format_type_readable(
        main,
        length=length,
        append_raw_in_brackets=append_raw_in_brackets,
    )
    return out


def _payload_no_none(val: Any) -> Any:
    """Recursively replace None with empty string for Qdrant (400 on null in payload)."""
    if val is None:
        return ""
    if isinstance(val, dict):
        return {k: _payload_no_none(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_payload_no_none(v) for v in val]
    return val


def _node_payload_from_object(obj: ConfigObject, crawl: CrawlResult) -> dict[str, Any]:
    """Build Qdrant payload for a single configuration object.

    This helper encapsulates the schema used by the metadata graph collection.
    Qdrant returns 400 if payload contains null; we strip None and use empty string.
    """

    # При слиянии нескольких выгрузок у каждого объекта в attributes лежат config_name/config_version
    obj_attrs = obj.attributes or {}
    payload: dict[str, Any] = {
        "id": obj.id,
        "config_name": obj_attrs.get("config_name") or crawl.config_name,
        "config_version": obj_attrs.get("config_version") or crawl.config_version,
        "object_type": obj.object_type,
        "name": obj.name,
        "full_name": obj.full_name or "",
        "path": obj.path or "",
    }
    if obj_attrs.get("platform_version") or crawl.platform_version:
        payload["platform_version"] = obj_attrs.get("platform_version") or crawl.platform_version
    if obj.attributes:
        payload["attributes"] = _payload_no_none(obj.attributes)
    # Ссылки графа: форма → родительский объект; объект → список форм.
    parent_id = (obj.attributes or {}).get("parent_id")
    if parent_id:
        payload["parent_id"] = parent_id
    form_ids = [o.id for o in crawl.objects if (o.attributes or {}).get("parent_id") == obj.id]
    if form_ids:
        payload["form_ids"] = form_ids
    # Markdown для эмбеддинга: все поля, без лимитов, по-русски — единообразно со справкой.
    payload["text"] = _object_to_markdown(obj, crawl)
    return payload


def _object_to_markdown(obj: ConfigObject, crawl: CrawlResult) -> str:
    """Собирает один markdown-документ по объекту метаданных (для эмбеддинга, как страницы справки).
    Все поля, без ограничений по количеству; подписи по-русски для понимания конфигурации.
    """
    lines: list[str] = []
    type_ru = _OBJECT_TYPE_RU.get(obj.object_type, obj.object_type)
    lines.append(f"# {type_ru}: {obj.name}")
    if obj.full_name:
        lines.append(f"\n**Представление:** {obj.full_name}")
    lines.append(f"\n**Конфигурация:** {crawl.config_name} (версия {crawl.config_version})")
    if obj.path:
        lines.append(f"**Путь:** {obj.path}")

    attrs = obj.attributes or {}
    parent_id = attrs.get("parent_id")
    if parent_id:
        lines.append(f"\n**Родительский объект:** `{parent_id}`")
    form_ids = [o.id for o in crawl.objects if (o.attributes or {}).get("parent_id") == obj.id]
    if form_ids:
        lines.append("\n**Формы:**")
        for fid in form_ids:
            lines.append(f"- `{fid}`")

    reqs = attrs.get("requisites") or []
    if reqs:
        lines.append("\n## Реквизиты")
        for r in reqs:
            if isinstance(r, dict):
                name = r.get("name") or ""
                disp = format_requisite_type_display(r, append_raw_in_brackets=True)
                if disp:
                    lines.append(f"- {name}: {disp}")
                else:
                    lines.append(f"- {name}")

    tabs = attrs.get("tabular_sections") or []
    if tabs:
        lines.append("\n## Табличные части")
        for t in tabs:
            name = (t.get("name") if isinstance(t, dict) else None) or (str(t) if t else "")
            if not name:
                continue
            lines.append(f"\n### {name}")
            reqs_ts = (t.get("requisites") or []) if isinstance(t, dict) else []
            for r in reqs_ts:
                if isinstance(r, dict):
                    rname = r.get("name") or ""
                    disp = format_requisite_type_display(r, append_raw_in_brackets=True)
                    if disp:
                        lines.append(f"- {rname}: {disp}")
                    else:
                        lines.append(f"- {rname}")
                else:
                    lines.append(f"- {r}")
            if not reqs_ts:
                lines.append("- (реквизиты не извлечены)")

    form_reqs = attrs.get("form_requisites") or []
    if form_reqs:
        lines.append("\n## Реквизиты формы")
        for r in form_reqs:
            if isinstance(r, dict):
                name = r.get("name") or ""
                disp = format_requisite_type_display(r, append_raw_in_brackets=True)
                if disp:
                    lines.append(f"- {name}: {disp}")
                else:
                    lines.append(f"- {name}")

    form_cmds = attrs.get("form_commands") or []
    if form_cmds:
        lines.append("\n## Команды формы")
        for c in form_cmds:
            if isinstance(c, dict):
                name = c.get("name") or ""
                action = (c.get("action") or "").strip()
                if action and action != name:
                    lines.append(f"- {name} → {action}")
                else:
                    lines.append(f"- {name}")

    return "\n".join(lines).strip() or f"{type_ru} {obj.name}"


def _edge_payload_from_relation(rel: ConfigRelation, crawl: CrawlResult) -> dict[str, Any]:
    """Build payload for an edge collection (relations between objects)."""

    payload: dict[str, Any] = {
        "config_name": crawl.config_name,
        "config_version": crawl.config_version,
        "from_id": rel.from_id,
        "to_id": rel.to_id,
        "relation_type": rel.relation_type,
    }
    if crawl.platform_version:
        payload["platform_version"] = crawl.platform_version
    return payload


# Sparse vector name for BM25; must match indexer.SPARSE_VECTOR_NAME for add-bm25 / search.
_METADATA_SPARSE_VECTOR_NAME = "text-bm25"

# Батч меньше 500, чтобы один upsert не упирался в QDRANT_TIMEOUT при крупных payload.
_METADATA_UPSERT_BATCH_SIZE = 200


def build_metadata_graph_from_crawl(
    crawl: CrawlResult,
    *,
    client: Any,
    embed_batch: Any,
    collection_name: str = "onec_config_metadata",
    recreate: bool = True,
    use_bm25: bool = False,
    upsert_progress_callback: Any = None,
    on_embed_done: Any = None,
) -> int:
    """Write `CrawlResult` into Qdrant using provided client and embedding batch function.

    on_embed_done: optional callback called once embedding is finished (so CLI can stop heartbeat).
    By default creates dense-only collection (same as ingest for onec_help). To add BM25
    sparse vectors, run afterward: add-bm25 --collection onec_config_metadata.
    Set use_bm25=True to build dense+sparse in one go (requires Qdrant with sparse support).
    """
    from qdrant_client import models as qmodels  # type: ignore[import-not-found]

    if not crawl.objects:
        return 0

    payloads: list[dict[str, Any]] = [
        _node_payload_from_object(obj, crawl) for obj in crawl.objects
    ]
    texts: list[str] = [p.get("text", "") for p in payloads]
    vectors: Sequence[Sequence[float]] = embed_batch(texts) if texts else []
    if not vectors:
        print(
            "metadata-graph-build: embedding returned 0 vectors, skipping (check EMBEDDING_API_URL / backend)",
            file=sys.stderr,
            flush=True,
        )
        return 0
    if on_embed_done:
        try:
            on_embed_done()
        except Exception:
            pass
    dim = len(vectors[0])

    vectors_bm25: list[dict[str, Any]] = []
    sparse_config: Any = None
    if use_bm25 and texts:
        try:
            from .sparse_bm25 import bm25_vocab_path, build_bm25_vectors, save_vocab

            vectors_bm25, vocab_bm25, doc_freq_bm25 = build_bm25_vectors(texts)
            if vectors_bm25 and len(vectors_bm25) == len(payloads):
                path = bm25_vocab_path(collection_name)
                save_vocab(str(path), vocab_bm25, doc_freq_bm25, len(texts))
                if hasattr(qmodels, "SparseVector") and hasattr(qmodels, "SparseVectorParams"):
                    try:
                        from qdrant_client.models import Modifier  # type: ignore[import-not-found]

                        sparse_config = {
                            _METADATA_SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                                modifier=Modifier.IDF
                            )
                        }
                    except Exception:
                        sparse_config = None
        except Exception:
            vectors_bm25 = []
            sparse_config = None

    use_bm25_final = bool(sparse_config and vectors_bm25 and len(vectors_bm25) == len(payloads))

    # Сначала собираем точки; recreate делаем только когда есть что писать (иначе при сбое остаётся пустая коллекция).
    # Целиком убираем None из payload (Qdrant даёт 400 на null), как в memory/indexer.
    points: list[Any] = []
    for idx, (payload, vec) in enumerate(zip(payloads, vectors, strict=True)):
        clean_payload = _payload_no_none(payload)
        if use_bm25_final and idx < len(vectors_bm25):
            sv = vectors_bm25[idx]
            vec_for_point: Any = {
                "": list(vec),
                _METADATA_SPARSE_VECTOR_NAME: qmodels.SparseVector(
                    indices=sv.get("indices", []),
                    values=sv.get("values", []),
                ),
            }
        else:
            vec_for_point = list(vec)
        points.append(
            qmodels.PointStruct(
                id=idx,
                vector=vec_for_point,
                payload=clean_payload,
            )
        )

    total = len(points)
    print(
        f"metadata-graph-build: built {total} points, writing to Qdrant ({collection_name})...",
        file=sys.stderr,
        flush=True,
    )
    # Recreate только когда точки готовы — не оставляем пустую коллекцию при сбое до upsert.
    if recreate:
        vectors_cfg = qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
        sparse_cfg = sparse_config if (use_bm25_final and sparse_config) else None
        create_kw: dict[str, Any] = {
            "collection_name": collection_name,
            "vectors_config": vectors_cfg,
        }
        if sparse_cfg is not None:
            create_kw["sparse_vectors_config"] = sparse_cfg
        if hasattr(client, "create_collection"):
            try:
                client.create_collection(**create_kw)
            except Exception as e:
                err = str(e).lower()
                if "already exist" in err or "already exists" in err:
                    if sparse_cfg is not None:
                        client.recreate_collection(
                            collection_name=collection_name,
                            vectors_config=vectors_cfg,
                            sparse_vectors_config=sparse_cfg,
                        )
                    else:
                        client.recreate_collection(
                            collection_name=collection_name,
                            vectors_config=vectors_cfg,
                        )
                else:
                    raise
        else:
            if sparse_cfg is not None:
                client.recreate_collection(
                    collection_name=collection_name,
                    vectors_config=vectors_cfg,
                    sparse_vectors_config=sparse_cfg,
                )
            else:
                client.recreate_collection(
                    collection_name=collection_name,
                    vectors_config=vectors_cfg,
                )
        print(
            f"metadata-graph-build: collection {collection_name!r} recreated, upserting {total} points",
            file=sys.stderr,
            flush=True,
        )

    from .indexer import _upsert_batch_with_retry

    written = 0
    for start in range(0, total, _METADATA_UPSERT_BATCH_SIZE):
        batch = points[start : start + _METADATA_UPSERT_BATCH_SIZE]
        _upsert_batch_with_retry(client, collection_name, batch)
        written += len(batch)
        print(
            f"metadata-graph-build: upserted {written}/{total} → {collection_name}",
            file=sys.stderr,
            flush=True,
        )
        if upsert_progress_callback:
            try:
                upsert_progress_callback(written, total)
            except Exception:
                pass
    return total


def _get_default_client() -> Any:
    """Return QdrantClient instance using env_config host/port.

    Separated into a helper so tests can inject fake clients without importing qdrant_client.
    """

    from qdrant_client import QdrantClient  # type: ignore[import-not-found]

    return QdrantClient(
        host=env_config.get_qdrant_host(),
        port=env_config.get_qdrant_port(),
        check_compatibility=False,
    )


def get_metadata_config_versions(
    *,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    max_points: int = 500,
) -> list[str]:
    """Return distinct config_version values in the metadata collection.

    Used to auto-fill config_version when the collection has only one version.
    """
    client = client or _get_default_client()
    try:
        if not client.collection_exists(collection_name):
            return []
    except Exception:
        return []
    seen: set[str] = set()
    offset: Any | None = None
    try:
        pass  # type: ignore[import-not-found]
    except Exception:
        return []
    while len(seen) < 100:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=min(64, max_points),
            offset=offset,
        )
        if not points:
            break
        for pt in points:
            payload = getattr(pt, "payload", None) or {}
            v = payload.get("config_version")
            if v is not None and str(v).strip():
                seen.add(str(v).strip())
        if offset is None:
            break
    return sorted(seen)


_RRF_K = 60


def _search_metadata_substring(
    client: Any,
    collection_name: str,
    q: str,
    type_filter: str | None,
    filt: Any,
    limit: int,
) -> list[dict[str, Any]]:
    """Scroll + substring match by name/full_name. Used as fallback or for hybrid merge."""
    results: list[dict[str, Any]] = []
    offset: Any | None = None
    while len(results) < limit:
        points, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=filt,
            limit=min(64, limit * 2),
            offset=offset,
        )
        if not points:
            break
        for pt in points:
            payload = getattr(pt, "payload", None) or {}
            if type_filter and payload.get("object_type") != type_filter:
                continue
            name = str(payload.get("name") or "").lower()
            full = str(payload.get("full_name") or "").lower()
            if q and (q not in name and q not in full):
                continue
            if "id" not in payload:
                payload["id"] = getattr(pt, "id", None)
            results.append(cast(dict[str, Any], dict(payload)))
            if len(results) >= limit:
                break
        if offset is None:
            break
    return results


def search_metadata_by_name(
    query: str,
    type_filter: str | None,
    config_version: str,
    *,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    limit: int = 20,
    use_semantic: bool = True,
    use_hybrid: bool = True,
) -> list[dict[str, Any]]:
    """Search configuration objects by semantic (vector) and/or substring within a given config_version.

    When use_semantic is True, the query is embedded and vector search is performed; when use_hybrid
    is True, substring results are merged with vector results via RRF. Falls back to substring-only
    if the collection does not exist or embedding is unavailable.
    """

    if not config_version:
        return []
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return []

    client = client or _get_default_client()
    q = (query or "").strip().lower()
    filt = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="config_version", match=qmodels.MatchValue(value=config_version)
            )
        ]
    )

    vector_results: list[dict[str, Any]] = []
    if use_semantic and (query or "").strip():
        try:
            from . import embedding
            from .indexer import get_collection_vector_size

            coll_dim = get_collection_vector_size(
                collection=collection_name,
                qdrant_host=env_config.get_qdrant_host(),
                qdrant_port=env_config.get_qdrant_port(),
            )
            if client.collection_exists(collection_name) and coll_dim is not None:
                vector = embedding.get_embedding(
                    query.strip(),
                    target_dimension=coll_dim,
                )
                kwargs: dict[str, Any] = {
                    "collection_name": collection_name,
                    "limit": limit * 2 if use_hybrid else limit,
                    "query": vector,
                    "query_filter": filt,
                }
                if hasattr(client, "query_points"):
                    response = client.query_points(**kwargs)
                    hits = getattr(response, "points", [])
                else:
                    kwargs["query_vector"] = vector
                    hits = client.search(**kwargs)
                for h in hits:
                    payload = getattr(h, "payload", None) or {}
                    if type_filter and payload.get("object_type") != type_filter:
                        continue
                    out = dict(payload)
                    if "id" not in out:
                        out["id"] = getattr(h, "id", None)
                    out["_score"] = getattr(h, "score", None)
                    vector_results.append(out)
        except Exception:
            vector_results = []

    if not use_hybrid:
        return (
            vector_results[:limit]
            if vector_results
            else _search_metadata_substring(client, collection_name, q, type_filter, filt, limit)
        )

    substring_results: list[dict[str, Any]] = []
    if q or not vector_results:
        substring_results = _search_metadata_substring(
            client,
            collection_name,
            q,
            type_filter,
            filt,
            limit * 2,
        )

    if not vector_results and not substring_results:
        return []
    if not vector_results:
        return substring_results[:limit]
    if not substring_results:
        return vector_results[:limit]

    rrf_scores: dict[str, float] = {}
    id_to_doc: dict[str, dict[str, Any]] = {}
    for rank, r in enumerate(vector_results, 1):
        oid = str(r.get("id") or "")
        if oid:
            rrf_scores[oid] = rrf_scores.get(oid, 0) + 1 / (_RRF_K + rank)
            id_to_doc[oid] = r
    for rank, r in enumerate(substring_results, 1):
        oid = str(r.get("id") or "")
        if oid:
            rrf_scores[oid] = rrf_scores.get(oid, 0) + 1 / (_RRF_K + rank)
            if oid not in id_to_doc:
                id_to_doc[oid] = r
    merged = sorted(
        id_to_doc.values(),
        key=lambda x: -rrf_scores.get(str(x.get("id") or ""), 0),
    )
    for d in merged:
        d.pop("_score", None)
    return merged[:limit]


def get_metadata_object(
    object_id: str,
    *,
    config_version: str | None = None,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
) -> dict[str, Any] | None:
    """Return single metadata object payload by its id.

    If config_version is given, only the object from that configuration is returned.
    """
    if not object_id:
        return None
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return None

    client = client or _get_default_client()
    must: list[Any] = [qmodels.FieldCondition(key="id", match=qmodels.MatchValue(value=object_id))]
    if config_version and str(config_version).strip():
        must.append(
            qmodels.FieldCondition(
                key="config_version",
                match=qmodels.MatchValue(value=str(config_version).strip()),
            )
        )
    filt = qmodels.Filter(must=must)
    points, _ = client.scroll(
        collection_name=collection_name,
        scroll_filter=filt,
        limit=1,
        offset=None,
    )
    if not points:
        return None
    pt = points[0]
    payload = getattr(pt, "payload", None) or {}
    if "id" not in payload:
        payload["id"] = getattr(pt, "id", None)
    return cast(dict[str, Any], payload)


# Note: search/read helpers (e.g. search_metadata_by_name, get_metadata_object)
# are added in later iterations and will reuse the same payload schema.
