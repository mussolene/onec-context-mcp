"""Metadata graph for 1C configuration objects.

This module is responsible for turning `CrawlResult` from `metadata_models` / KD2 parsing
into Qdrant collections and providing a small search/read API for MCP tools.

Design goals:
- Keep responsibilities separate from help index (`indexer.py`) and memory.
- Store per‑configuration metadata (config_name, config_version, platform_version).
- Allow simple name/typed search and lookup of a single object with its relations.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any, cast

from ..shared import env_config
from .metadata_ids import make_metadata_object_id
from .metadata_models import ConfigObject, ConfigRelation, CrawlResult

METADATA_FIELDS_COLLECTION_NAME = "onec_config_metadata_fields"

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
    "DocumentJournal": "Журнал документов",
    "Constant": "Константа",
    "ConstantsSet": "Набор констант",
    "ScheduledJob": "Регламентное задание",
    "ChartOfCharacteristicTypes": "План видов характеристик",
    "RegisterAccumulation": "Регистр накопления",  # old-style export alias
    "RegisterInformation": "Регистр сведений",  # old-style export alias
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
                    length = (
                        req.get("length")
                        if "string" in t.lower() and isinstance(req.get("length"), int)
                        else None
                    )
                    inner.append(
                        format_type_readable(t, length=length, append_raw_in_brackets=False)
                    )
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


def _build_children_index(crawl: CrawlResult) -> dict[str, list[str]]:
    """Build parent_id → [child object ids] index once for the whole crawl (avoids O(n²) scans)."""
    idx: dict[str, list[str]] = {}
    for o in crawl.objects:
        pid = (o.attributes or {}).get("parent_id")
        if pid:
            idx.setdefault(pid, []).append(o.id)
    return idx


def _node_payload_from_object(
    obj: ConfigObject,
    crawl: CrawlResult,
    children_index: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build Qdrant payload for a single configuration object.

    This helper encapsulates the schema used by the metadata graph collection.
    Qdrant returns 400 if payload contains null; we strip None and use empty string.
    children_index: pre-built parent_id → [child ids] dict (avoids O(n²) per-object scan).
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
    if children_index is not None:
        form_ids = children_index.get(obj.id) or []
    else:
        form_ids = [o.id for o in crawl.objects if (o.attributes or {}).get("parent_id") == obj.id]
    if form_ids:
        payload["form_ids"] = form_ids
    # Markdown для эмбеддинга: все поля, без лимитов, по-русски — единообразно со справкой.
    payload["text"] = _object_to_markdown(obj, crawl, children_index=children_index)
    return payload


def _object_to_markdown(
    obj: ConfigObject,
    crawl: CrawlResult,
    children_index: dict[str, list[str]] | None = None,
) -> str:
    """Собирает один markdown-документ по объекту метаданных (для эмбеддинга, как страницы справки).
    Все поля, без ограничений по количеству; подписи по-русски для понимания конфигурации.
    children_index: pre-built parent_id → [child ids] dict (avoids O(n²) per-object scan).
    """
    lines: list[str] = []
    type_ru = _OBJECT_TYPE_RU.get(obj.object_type, obj.object_type)
    lines.append(f"# {type_ru}: {obj.name}")
    if obj.full_name:
        lines.append(f"\n**Представление:** {obj.full_name}")
    attrs = obj.attributes or {}
    if obj.object_type == "Constant" and attrs.get("constant_bsl_hint"):
        lines.append(f"\n**Доступ:** {attrs['constant_bsl_hint']}")
    if obj.object_type == "ConstantsSet":
        lines.append(
            "\n**Константы:** в дереве метаданных набор только группирует имена; "
            "каждая строка ниже — отдельная константа (как объект **Метаданные.Константы**). "
            "В коде доступ без префикса набора: `Константы.<Имя>.Получить()` / `Установить(...)`."
        )
    if attrs.get("kd2_source_constants_set"):
        lines.append(
            f"\n**Примечание (выгрузка KD):** строка из набора «{attrs['kd2_source_constants_set']}»; "
            "в конфигураторе это корневая коллекция **Метаданные.Константы**."
        )
    obj_config_name = attrs.get("config_name") or crawl.config_name
    obj_config_version = attrs.get("config_version") or crawl.config_version
    lines.append(f"\n**Конфигурация:** {obj_config_name} (версия {obj_config_version})")
    if obj.path:
        lines.append(f"**Путь:** {obj.path}")
    parent_id = attrs.get("parent_id")
    if parent_id:
        lines.append(f"\n**Родительский объект:** `{parent_id}`")
    if children_index is not None:
        form_ids = children_index.get(obj.id) or []
    else:
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
                hint = (r.get("constant_bsl_hint") or "").strip()
                suffix = f" — {hint}" if hint else ""
                if disp:
                    lines.append(f"- {name}: {disp}{suffix}")
                else:
                    lines.append(f"- {name}{suffix}")

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
_METADATA_BATCH_SIZE = 500  # объектов за один цикл embed → upsert (как batch_size в build_index)
_METADATA_INDEXED_FIELDS: tuple[str, ...] = (
    "config_version",
    "object_type",
    "id",
    "name",
    "full_name",
    "path",
)
_METADATA_FIELDS_INDEXED_FIELDS: tuple[str, ...] = (
    "config_version",
    "object_id",
    "object_type",
    "object_name",
    "field_name",
    "field_name_norm",
    "synonym",
    "synonym_norm",
    "field_kind",
    "group_name",
    "tabular_section",
)


def _metadata_field_point_id(
    *,
    object_id: str,
    config_version: str,
    field_name: str,
    field_kind: str,
    group_name: str,
    tabular_section: str,
) -> int:
    key = "|".join(
        (
            str(config_version or "").strip(),
            str(object_id or "").strip(),
            str(group_name or "").strip(),
            str(tabular_section or "").strip(),
            str(field_kind or "").strip(),
            str(field_name or "").strip(),
        )
    )
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:14], 16) % (2**63)


def _ensure_collection(
    client: Any,
    collection_name: str,
    dim: int,
    recreate: bool,
    *,
    qmodels: Any,
) -> None:
    """Create or recreate collection. Called once before first upsert (dim known from first embed)."""
    vectors_cfg = qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
    create_kw: dict[str, Any] = {"collection_name": collection_name, "vectors_config": vectors_cfg}

    collection_exists = False
    try:
        collection_exists = bool(client.collection_exists(collection_name))
    except Exception:
        pass

    if not recreate and collection_exists:
        _ensure_payload_indexes(client, collection_name, qmodels=qmodels)
        print(
            f"metadata-graph-build: collection {collection_name!r} exists, will upsert",
            file=sys.stderr,
            flush=True,
        )
        return

    if hasattr(client, "create_collection"):
        try:
            client.create_collection(**create_kw)
            print(
                f"metadata-graph-build: collection {collection_name!r} created",
                file=sys.stderr,
                flush=True,
            )
        except Exception as e:
            err = str(e).lower()
            if "already exist" in err or "already exists" in err:
                client.delete_collection(collection_name=collection_name)
                client.create_collection(**create_kw)
                print(
                    f"metadata-graph-build: collection {collection_name!r} recreated",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                raise
    else:
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name=collection_name)
        client.create_collection(**create_kw)
        print(
            f"metadata-graph-build: collection {collection_name!r} recreated",
            file=sys.stderr,
            flush=True,
        )
    _ensure_payload_indexes(client, collection_name, qmodels=qmodels)


def _ensure_payload_indexes(
    client: Any,
    collection_name: str,
    *,
    qmodels: Any,
) -> None:
    """Create payload indexes for exact metadata lookup.

    Missing payload indexes force Qdrant to scan payloads even for exact filters.
    Metadata search relies heavily on config_version/object_type/id/name/full_name/path filters,
    so these indexes are part of the collection contract.
    """
    if not hasattr(client, "create_payload_index"):
        return
    for field in _METADATA_INDEXED_FIELDS:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except Exception:
            # Qdrant may report "already exists" or reject duplicate create; indexing is best-effort.
            continue


def _ensure_metadata_fields_payload_indexes(
    client: Any,
    collection_name: str,
    *,
    qmodels: Any,
) -> None:
    if not hasattr(client, "create_payload_index"):
        return
    for field in _METADATA_FIELDS_INDEXED_FIELDS:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except Exception:
            continue


def _iter_metadata_snapshot_dirs(base: str | Any) -> list[Any]:
    from pathlib import Path

    root = Path(base).expanduser().resolve()
    if not root.exists():
        return []
    if (root / "manifest.json").is_file():
        return [root]
    snapshots = root / "snapshots"
    if snapshots.is_dir():
        return sorted(path.parent for path in snapshots.glob("*/manifest.json") if path.is_file())
    return sorted(path.parent for path in root.glob("*/manifest.json") if path.is_file())


def _metadata_field_payload_from_snapshot_row(
    item: dict[str, Any],
    *,
    config_name: str,
    config_version: str,
) -> dict[str, Any]:
    field_name = str(item.get("name") or "").strip()
    synonym = str(item.get("synonym") or "").strip()
    object_id = str(item.get("object_id") or "").strip()
    object_name = str(item.get("object_name") or "").strip()
    object_type = str(item.get("object_type") or "").strip()
    group_name = str(item.get("group") or "").strip()
    field_kind = str(item.get("kind") or "").strip()
    tabular_section = str(item.get("tabular_section") or "").strip()
    types = item.get("types") if isinstance(item.get("types"), list) else []
    types_short = [str(raw).strip() for raw in types if str(raw).strip()][:20]
    payload: dict[str, Any] = {
        "object_id": object_id,
        "config_name": config_name,
        "config_version": str(item.get("config_version") or config_version).strip(),
        "object_type": object_type,
        "object_name": object_name,
        "field_name": field_name,
        "field_name_norm": field_name.lower(),
        "synonym": synonym,
        "synonym_norm": synonym.lower(),
        "field_kind": field_kind,
        "group_name": group_name,
        "tabular_section": tabular_section,
        "usage": str(item.get("usage") or "").strip(),
        "types_short": types_short,
    }
    if item.get("defined_type"):
        payload["defined_type"] = str(item.get("defined_type") or "").strip()
    payload["text"] = "\n".join(
        part
        for part in (
            object_id,
            object_name,
            field_name,
            synonym,
            field_kind,
            group_name,
            tabular_section,
            " ".join(types_short),
            payload.get("usage") or "",
        )
        if part
    )
    return payload


def build_metadata_fields_from_snapshot(
    snapshot_base: str | Any,
    *,
    client: Any,
    collection_name: str = METADATA_FIELDS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 500,
) -> int:
    from pathlib import Path

    from qdrant_client import models as qmodels  # type: ignore[import-not-found]

    total = 0
    dim = 1
    if recreate or not client.collection_exists(collection_name):
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )
    _ensure_metadata_fields_payload_indexes(client, collection_name, qmodels=qmodels)

    all_points: list[Any] = []
    for snapshot_dir in _iter_metadata_snapshot_dirs(Path(snapshot_base)):
        manifest_path = snapshot_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
        config_name = str(manifest.get("config_name") or "").strip()
        config_version = str(manifest.get("config_version") or "").strip()
        fields_path = snapshot_dir / "fields.jsonl"
        if not fields_path.is_file():
            continue
        with fields_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                row = cast(dict[str, Any], json.loads(line))
                payload = _metadata_field_payload_from_snapshot_row(
                    row,
                    config_name=config_name,
                    config_version=config_version,
                )
                point_id = _metadata_field_point_id(
                    object_id=payload.get("object_id", ""),
                    config_version=payload.get("config_version", ""),
                    field_name=payload.get("field_name", ""),
                    field_kind=payload.get("field_kind", ""),
                    group_name=payload.get("group_name", ""),
                    tabular_section=payload.get("tabular_section", ""),
                )
                all_points.append(
                    qmodels.PointStruct(
                        id=point_id, vector=[0.0], payload=_payload_no_none(payload)
                    )
                )
                if len(all_points) >= batch_size:
                    client.upsert(collection_name=collection_name, points=all_points)
                    total += len(all_points)
                    all_points = []
    if all_points:
        client.upsert(collection_name=collection_name, points=all_points)
        total += len(all_points)
    return total


def build_metadata_graph_from_crawl(
    crawl: CrawlResult,
    *,
    client: Any,
    embed_batch: Any,
    collection_name: str = "onec_config_metadata",
    recreate: bool = True,
    use_bm25: bool = False,
    upsert_progress_callback: Any = None,
    on_embed_done: Any = None,  # kept for API compatibility, ignored in batch mode
    batch_size: int = _METADATA_BATCH_SIZE,
) -> int:
    """Write `CrawlResult` into Qdrant in batches: embed batch → upsert → next batch.

    Identical pipeline to build_index: data appears in Qdrant progressively after each batch,
    memory usage is bounded to batch_size objects at a time instead of all N at once.
    upsert_progress_callback(written, total): called after each batch is written to Qdrant.
    """
    from qdrant_client import models as qmodels  # type: ignore[import-not-found]

    from ..search_store.indexer import _upsert_batch_with_retry

    if not crawl.objects:
        return 0

    # children_index строим один раз — O(N), иначе каждый объект сканирует весь crawl O(N²).
    children_index = _build_children_index(crawl)
    total = len(crawl.objects)
    written = 0
    collection_ready = False
    dim: int = 0

    for batch_start in range(0, total, batch_size):
        batch_objects = crawl.objects[batch_start : batch_start + batch_size]

        # Payload + text только для текущего батча — не держим все N в памяти одновременно.
        batch_payloads = [
            _node_payload_from_object(obj, crawl, children_index=children_index)
            for obj in batch_objects
        ]
        batch_texts = [p.get("text", "") for p in batch_payloads]

        batch_vectors = embed_batch(batch_texts)
        if not batch_vectors:
            print(
                f"metadata-graph-build: embedding returned 0 vectors at offset {batch_start}, skipping batch",
                file=sys.stderr,
                flush=True,
            )
            continue

        # Создаём коллекцию по размерности первого батча (dim известен только после embed).
        if not collection_ready:
            dim = len(batch_vectors[0])
            _ensure_collection(client, collection_name, dim, recreate, qmodels=qmodels)
            collection_ready = True

        batch_points: list[Any] = [
            qmodels.PointStruct(
                id=batch_start + i,
                vector=list(vec),
                payload=_payload_no_none(payload),
            )
            for i, (payload, vec) in enumerate(zip(batch_payloads, batch_vectors, strict=False))
        ]

        _upsert_batch_with_retry(client, collection_name, batch_points)
        written += len(batch_points)
        print(
            f"metadata-graph-build: {written}/{total} → {collection_name}",
            file=sys.stderr,
            flush=True,
        )
        if upsert_progress_callback:
            try:
                upsert_progress_callback(written, total)
            except Exception:
                pass

    return written


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


def get_metadata_config_summaries(
    *,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    max_points: int = 500,
) -> list[dict[str, str]]:
    """Return distinct (config_name, config_version) pairs from the metadata collection.

    Used to show which configurations are loaded in get_1c_help_index_status.
    """
    client = client or _get_default_client()
    try:
        if not client.collection_exists(collection_name):
            return []
    except Exception:
        return []
    seen: dict[str, str] = {}  # version -> name
    offset: Any | None = None
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
            n = payload.get("config_name") or ""
            if v is not None and str(v).strip():
                seen[str(v).strip()] = str(n).strip()
        if offset is None:
            break
    return [{"config_name": n, "config_version": v} for v, n in sorted(seen.items())]


_RRF_K = 60


# Макс. точек при scroll в substring-поиске.
# Крупные конфигурации содержат 6000+ объектов; лимит 512 скрывал ~90% из них.
# 30000 покрывает все текущие конфигурации; batch_size увеличен для сокращения числа API-вызовов.
_SEARCH_METADATA_SUBSTRING_MAX_POINTS = 5_000

_TYPE_FILTER_HINTS: dict[str, tuple[str, ...]] = {
    "Constant": ("констант", "constant", "constants"),
    "Document": ("документ", "document"),
    "Catalog": ("справочник", "catalog"),
    "InformationRegister": ("регистр сведений", "informationregister"),
    "AccumulationRegister": ("регистр накопления", "accumulationregister"),
    "Report": ("отчет", "отчёт", "report"),
    "DataProcessor": ("обработка", "dataprocessor"),
    "Enumeration": ("перечисление", "enumeration", "enum"),
}


def _build_metadata_nl_stopwords() -> frozenset[str]:
    """Words stripped from NL metadata queries before token substring matching."""
    words: set[str] = set()
    for object_type, hints in _TYPE_FILTER_HINTS.items():
        words.add(object_type.lower())
        for h in hints:
            for part in h.replace("_", " ").split():
                pl = part.strip().lower()
                if len(pl) >= 3:
                    words.add(pl)
    words.update(
        {
            "метаданные",
            "metadata",
            "объект",
            "object",
            "найти",
            "нужен",
            "нужна",
            "нужно",
            "where",
            "find",
            "the",
            "and",
            "for",
        }
    )
    return frozenset(words)


_METADATA_NL_STOPWORDS: frozenset[str] = _build_metadata_nl_stopwords()


def _metadata_nl_word_variants(query: str) -> list[str]:
    """Significant tokens from a multi-word phrase for name/full_name substring match.

    Vector search often ranks the wrong «товарный» document; matching e.g. «реализация»
    inside **РеализацияТоваровУслуг** fixes NL queries like «документ реализация товаров».
    """
    q = (query or "").strip().lower()
    if not q or " " not in q:
        return []
    raw_tokens = re.findall(r"[\w\dА-Яа-яЁё]+", q)
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        t = tok.strip().lower()
        if len(t) < 4 or t in _METADATA_NL_STOPWORDS:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _guess_type_filter(query: str, type_filter: str | None) -> str | None:
    if type_filter:
        return type_filter
    q = (query or "").strip().lower()
    for object_type, hints in _TYPE_FILTER_HINTS.items():
        if any(hint in q for hint in hints):
            return object_type
    return None


def _metadata_query_variants(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    no_spaces = q.replace(" ", "")
    variants = [q]
    if no_spaces != q:
        variants.append(no_spaces)
    if "/" in q:
        variants.extend(part for part in q.split("/") if part)
    return list(dict.fromkeys(variants))


def _metadata_match_priority(payload: dict[str, Any], variants: list[str]) -> int:
    fields = [
        str(payload.get("id") or "").lower(),
        str(payload.get("name") or "").lower(),
        str(payload.get("full_name") or "").lower(),
    ]
    if not variants:
        return 2
    if any(field == variant for field in fields for variant in variants):
        return 0
    if any(field.startswith(variant) for field in fields for variant in variants):
        return 1
    if any(variant in field for field in fields for variant in variants):
        return 2
    return 3


# Русские/английские префиксы → канонический id в графе KD2/Qdrant (Document.Имя).
# Единственное число — как в языке запросов (вирт. таблицы: Документ.Имя, Справочник.Имя).
# Множественное — как коллекции в BSL (Метаданные.Документы.Имя, Метаданные.Справочники.Имя, …).
_METADATA_DOT_PREFIX_TO_ID_PREFIX: dict[str, str] = {
    "Документ": "Document",
    "Документы": "Document",
    "Справочник": "Catalog",
    "Справочники": "Catalog",
    "Перечисление": "Enum",
    "Перечисления": "Enum",
    "РегистрСведений": "InformationRegister",
    "РегистрыСведений": "InformationRegister",
    "РегистрНакопления": "AccumulationRegister",
    "РегистрыНакопления": "AccumulationRegister",
    "РегистрБухгалтерии": "AccountingRegister",
    "РегистрыБухгалтерии": "AccountingRegister",
    "РегистрРасчета": "CalculationRegister",
    "РегистрыРасчета": "CalculationRegister",
    "ПланСчетов": "ChartOfAccounts",
    "ПланыСчетов": "ChartOfAccounts",
    "ПланВидовХарактеристик": "ChartOfCharacteristicTypes",
    "ПланыВидовХарактеристик": "ChartOfCharacteristicTypes",
    "ПланВидовРасчета": "ChartOfCalculationTypes",
    "ПланыВидовРасчета": "ChartOfCalculationTypes",
    "ПланОбмена": "ExchangePlan",
    "ПланыОбмена": "ExchangePlan",
    "БизнесПроцесс": "BusinessProcess",
    "БизнесПроцессы": "BusinessProcess",
    "Задача": "Task",
    "Задачи": "Task",
    "Отчет": "Report",
    "Отчёт": "Report",
    "Отчеты": "Report",
    "Отчёты": "Report",
    "Обработка": "DataProcessor",
    "Обработки": "DataProcessor",
    "ОбщийМодуль": "CommonModule",
    "ОбщиеМодули": "CommonModule",
    # Английские коллекции (как в дереве метаданных / синтакс-помощнике на EN-клиенте)
    "Documents": "Document",
    "Catalogs": "Catalog",
    "Enums": "Enum",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "ExchangePlans": "ExchangePlan",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "CommonModules": "CommonModule",
    "Константы": "Constant",
    "Константа": "Constant",
    "Constants": "Constant",
}

_ENGLISH_METADATA_ID_PREFIXES: frozenset[str] = frozenset(
    {
        "Document",
        "Catalog",
        "Enum",
        "InformationRegister",
        "AccumulationRegister",
        "AccountingRegister",
        "CalculationRegister",
        "ChartOfAccounts",
        "ChartOfCharacteristicTypes",
        "ChartOfCalculationTypes",
        "ExchangePlan",
        "BusinessProcess",
        "Task",
        "Report",
        "DataProcessor",
        "CommonModule",
        "Form",
        "Constant",
        "ConstantsSet",
    }
)


def _looks_like_english_dot_metadata_id(query: str) -> bool:
    """True if query looks like canonical ``EnglishType.ObjectName`` (or ``Form.…``) for exact-first."""
    q = (query or "").strip()
    if "." not in q:
        return False
    prefix, _, rest = q.partition(".")
    if not prefix or not rest:
        return False
    return prefix in _ENGLISH_METADATA_ID_PREFIXES


def _collapse_dotted_path_segments(path: str) -> str:
    """Убирает пустые сегменты и пробелы вокруг точек: 'Документы . Авансы' → 'Документы.Авансы'."""
    parts = [p.strip() for p in (path or "").split(".") if p.strip()]
    return ".".join(parts)


def _strip_leading_metadata_roots(path: str) -> str:
    """Снимает повторяющиеся корни Метаданные. / Metadata. (копипаста из BSL)."""
    q = (path or "").strip()
    while True:
        if q.startswith("Метаданные."):
            q = q[len("Метаданные.") :].strip()
            continue
        if q.startswith("Metadata."):
            q = q[len("Metadata.") :].strip()
            continue
        if q.startswith("ГлобальныйКонтекст."):
            q = q[len("ГлобальныйКонтекст.") :].strip()
            continue
        if q.startswith("Глобальный контекст."):
            q = q[len("Глобальный контекст.") :].strip()
            continue
        if q.startswith("Global context."):
            q = q[len("Global context.") :].strip()
            continue
        break
    return q


def _metadata_object_name_from_accessor_rest(rest: str) -> str:
    """Имя объекта метаданных — первый идентификатор после типа.

    В типовой конфигурации имя объекта не содержит точку. Дальнейшие сегменты — вызовы методов менеджера,
    обращения к коллекциям свойств, значения перечисления и т.д. (см. справку по типу *Менеджер.<…> в
    structured help); для графа конфигурации нужен только сегмент имени объекта.
    """
    rest = _collapse_dotted_path_segments(rest)
    if not rest:
        return ""
    first = rest.split(".", 1)[0].strip()
    if "(" in first:
        first = first.split("(", 1)[0].strip()
    return first


def _metadata_canonical_id_aliases_from_query(query: str) -> list[str]:
    """Префикс типа (до первой точки) → канонический id ``EnglishType.ObjectName``.

    Поддерживаются: язык запросов (Документ.Имя), коллекции BSL (Документы.Имя, Справочники.Имя),
    Метаданные.*/Metadata.*, EN-коллекции (Documents.Имя). Все сегменты после имени объекта (методы,
    свойства, значения перечисления) отбрасываются — в индексе один объект на пару тип+имя.
    """
    q = _collapse_dotted_path_segments(query or "")
    if not q:
        return []
    q = _strip_leading_metadata_roots(q)
    q = _collapse_dotted_path_segments(q)
    if "." not in q:
        return []
    prefix, _, rest = q.partition(".")
    prefix = prefix.strip()
    rest = rest.strip()
    if not prefix or not rest:
        return []
    object_name = _metadata_object_name_from_accessor_rest(rest)
    if not object_name:
        return []
    out: list[str] = []
    mapped = _METADATA_DOT_PREFIX_TO_ID_PREFIX.get(prefix)
    if mapped:
        out.append(make_metadata_object_id(mapped, object_name))
    if prefix in _ENGLISH_METADATA_ID_PREFIXES:
        out.append(make_metadata_object_id(prefix, object_name))
    return list(dict.fromkeys(out))


def _metadata_query_prefers_exact_first(query: str) -> bool:
    """Семантика шумит на коротких именах объектов — сначала exact/id."""
    q = (query or "").strip()
    if not q:
        return False
    if "/" in q:
        return True
    if _looks_like_english_dot_metadata_id(q):
        return True
    if _metadata_canonical_id_aliases_from_query(q):
        return True
    if " " in q:
        return False
    return bool(re.fullmatch(r"[\wА-Яа-яЁё][\wА-Яа-яЁё0-9]*", q))


def _normalized_metadata_exact_values(query: str) -> list[str]:
    raw = (query or "").strip()
    variants: list[str] = []
    if raw:
        variants.append(raw)
        lowered = raw.lower()
        if lowered != raw:
            variants.append(lowered)
    for value in _metadata_query_variants(query):
        if value not in variants:
            variants.append(value)
    for alias in _metadata_canonical_id_aliases_from_query(raw):
        variants.append(alias)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in variants:
        value_clean = str(value or "").strip()
        if value_clean and value_clean not in seen:
            seen.add(value_clean)
            deduped.append(value_clean)
    return deduped


def _match_filter(field: str, value: str, *, qmodels: Any) -> Any:
    return qmodels.FieldCondition(key=field, match=qmodels.MatchValue(value=value))


def _base_metadata_filter(
    *,
    config_version: str,
    type_filter: str | None,
    qmodels: Any,
) -> Any:
    must: list[Any] = [_match_filter("config_version", config_version, qmodels=qmodels)]
    if type_filter:
        must.append(_match_filter("object_type", type_filter, qmodels=qmodels))
    return qmodels.Filter(must=must)


def _scroll_points(
    client: Any,
    *,
    collection_name: str,
    filt: Any,
    limit: int,
) -> list[Any]:
    points, _ = client.scroll(
        collection_name=collection_name,
        scroll_filter=filt,
        limit=limit,
        offset=None,
    )
    return list(points or [])


def _payload_from_point(point: Any) -> dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    if "id" not in payload:
        payload["id"] = getattr(point, "id", None)
    return payload


def _unique_metadata_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        oid = str(item.get("id") or "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _exact_field_matches(
    *,
    client: Any,
    collection_name: str,
    base_filter: Any,
    field_name: str,
    values: list[str],
    limit: int,
    qmodels: Any,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in values:
        filt = qmodels.Filter(
            must=[
                *list(getattr(base_filter, "must", []) or []),
                _match_filter(field_name, value, qmodels=qmodels),
            ]
        )
        points = _scroll_points(
            client,
            collection_name=collection_name,
            filt=filt,
            limit=max(1, limit),
        )
        items.extend(_payload_from_point(point) for point in points)
    return _unique_metadata_items(items, limit)


def _collect_field_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten attributes for search_metadata_fields (aligned with kd2 fields.jsonl groups)."""
    attributes = payload.get("attributes") or {}
    values: list[dict[str, Any]] = []
    for group_name in (
        "requisites",
        "dimensions",
        "resources",
        "properties",
        "constants",
        "commands",
    ):
        group = attributes.get(group_name)
        if not isinstance(group, list):
            continue
        for item in group:
            if isinstance(item, dict):
                values.append({"group": group_name, **item})
    tabs = attributes.get("tabular_sections")
    if isinstance(tabs, list):
        for section in tabs:
            if not isinstance(section, dict):
                continue
            values.append(
                {
                    "group": "tabular_sections",
                    "name": section.get("name", ""),
                    "synonym": section.get("synonym", ""),
                    "kind": "ТабличнаяЧасть",
                }
            )
            ts_name = section.get("name", "")
            for field in section.get("requisites") or []:
                if isinstance(field, dict):
                    values.append(
                        {"group": "tabular_section_requisites", "tabular_section": ts_name, **field}
                    )
    return values


def _field_match_priority(field_payload: dict[str, Any], variants: list[str]) -> int:
    field_name = str(field_payload.get("name") or "").lower()
    field_synonym = str(field_payload.get("synonym") or "").lower()
    values = [field_name, field_synonym]
    if any(value == variant for value in values for variant in variants):
        return 0
    if any(value.startswith(variant) for value in values for variant in variants):
        return 1
    if any(variant in value for value in values for variant in variants):
        return 2
    return 3


def search_metadata_exact(
    query: str,
    type_filter: str | None,
    config_version: str,
    *,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Indexed exact lookup by id/name/full_name/path within a config_version."""
    if not config_version:
        return []
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return []

    client = client or _get_default_client()
    q = (query or "").strip()
    if not q:
        return []
    effective_type_filter = _guess_type_filter(q, type_filter)
    variants = _normalized_metadata_exact_values(q)
    base_filter = _base_metadata_filter(
        config_version=config_version,
        type_filter=effective_type_filter,
        qmodels=qmodels,
    )
    ranked: list[dict[str, Any]] = []
    for field_name in ("id", "name", "full_name", "path"):
        ranked.extend(
            _exact_field_matches(
                client=client,
                collection_name=collection_name,
                base_filter=base_filter,
                field_name=field_name,
                values=variants,
                limit=limit,
                qmodels=qmodels,
            )
        )
    return _unique_metadata_items(ranked, limit)


def search_metadata_semantic(
    query: str,
    type_filter: str | None,
    config_version: str,
    *,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    limit: int = 20,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Semantic lookup over metadata vectors within a config_version."""
    if not config_version:
        return []
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return []

    client = client or _get_default_client()
    q = (query or "").strip()
    if not q and not query_vector:
        return []
    effective_type_filter = _guess_type_filter(q, type_filter)
    exact_first: list[dict[str, Any]] = []
    if q and _metadata_query_prefers_exact_first(q):
        exact_first = search_metadata_exact(
            q,
            type_filter,
            config_version,
            client=client,
            collection_name=collection_name,
            limit=limit,
        )
    filt = _base_metadata_filter(
        config_version=config_version,
        type_filter=effective_type_filter,
        qmodels=qmodels,
    )
    # NL phrases: prepend token-based substring hits so embedding order does not hide the right object.
    substring_prepend: list[dict[str, Any]] = []
    if q and " " in q:
        try:
            substring_prepend = _search_metadata_substring(
                client,
                collection_name,
                q,
                effective_type_filter,
                filt,
                limit=min(limit, 30),
                max_points=min(_SEARCH_METADATA_SUBSTRING_MAX_POINTS, 6000),
            )
        except Exception:
            substring_prepend = []
    try:
        from ..search_store import embedding
        from ..search_store.indexer import get_collection_vector_size

        coll_dim = get_collection_vector_size(
            collection=collection_name,
            qdrant_host=env_config.get_qdrant_host(),
            qdrant_port=env_config.get_qdrant_port(),
        )
        if not client.collection_exists(collection_name) or coll_dim is None:
            return _unique_metadata_items(exact_first + substring_prepend, limit)
        vector = query_vector
        if vector is None or len(vector) != coll_dim:
            vector = embedding.get_embedding(q, target_dimension=coll_dim)
        kwargs: dict[str, Any] = {
            "collection_name": collection_name,
            "limit": limit,
            "query": vector,
            "query_filter": filt,
        }
        if hasattr(client, "query_points"):
            response = client.query_points(**kwargs)
            hits = getattr(response, "points", [])
        else:
            kwargs["query_vector"] = vector
            hits = client.search(**kwargs)
        semantic = [_payload_from_point(hit) for hit in hits]
        return _unique_metadata_items(exact_first + substring_prepend + semantic, limit)
    except Exception:
        return _unique_metadata_items(exact_first + substring_prepend, limit)


def search_metadata_fields(
    object_query: str,
    field_query: str,
    *,
    config_version: str,
    type_filter: str | None = None,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
    limit: int = 10,
    exact_object_first: bool = True,
) -> list[dict[str, Any]]:
    """Search requisites/tabular sections/commands inside matched metadata objects."""
    if not config_version or not object_query or not field_query:
        return []
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        qmodels = None
    object_matches = (
        search_metadata_exact(
            object_query,
            type_filter,
            config_version,
            client=client,
            collection_name=collection_name,
            limit=max(limit, 5),
        )
        if exact_object_first
        else []
    )
    if not object_matches:
        object_matches = search_metadata_semantic(
            object_query,
            type_filter,
            config_version,
            client=client,
            collection_name=collection_name,
            limit=max(limit, 5),
        )
    variants = _metadata_query_variants(field_query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    if qmodels is not None:
        client = client or _get_default_client()
        try:
            if client.collection_exists(METADATA_FIELDS_COLLECTION_NAME):
                for obj in object_matches:
                    object_id = str(obj.get("id") or "").strip()
                    if not object_id:
                        continue
                    filt = qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="config_version",
                                match=qmodels.MatchValue(value=config_version),
                            ),
                            qmodels.FieldCondition(
                                key="object_id",
                                match=qmodels.MatchValue(value=object_id),
                            ),
                        ]
                    )
                    points = _scroll_points(
                        client,
                        collection_name=METADATA_FIELDS_COLLECTION_NAME,
                        filt=filt,
                        limit=max(limit * 8, 50),
                    )
                    for point in points:
                        payload = _payload_from_point(point)
                        field_payload = {
                            "name": payload.get("field_name", ""),
                            "synonym": payload.get("synonym", ""),
                            "group": payload.get("group_name", ""),
                            "kind": payload.get("field_kind", ""),
                            "tabular_section": payload.get("tabular_section", ""),
                            "type": "",
                            "types": payload.get("types_short") or [],
                            "defined_type": payload.get("defined_type") or "",
                        }
                        priority = _field_match_priority(field_payload, variants)
                        if priority > 2:
                            continue
                        ranked.append(
                            (
                                priority,
                                {
                                    "object_id": object_id,
                                    "object_name": obj.get("name", ""),
                                    "object_type": obj.get("object_type", ""),
                                    "config_name": payload.get(
                                        "config_name", obj.get("config_name", "")
                                    ),
                                    "config_version": payload.get("config_version", config_version),
                                    "field_group": payload.get("group_name", ""),
                                    "field_name": payload.get("field_name", ""),
                                    "field_synonym": payload.get("synonym", ""),
                                    "field_type": format_requisite_type_display(field_payload),
                                    "field_tabular_section": payload.get("tabular_section") or "",
                                },
                            )
                        )
        except Exception:
            ranked = []
    if not ranked:
        for obj in object_matches:
            for field_payload in _collect_field_values(obj):
                priority = _field_match_priority(field_payload, variants)
                if priority > 2:
                    continue
                ranked.append(
                    (
                        priority,
                        {
                            "object_id": obj.get("id", ""),
                            "object_name": obj.get("name", ""),
                            "object_type": obj.get("object_type", ""),
                            "config_name": obj.get("config_name", ""),
                            "config_version": obj.get("config_version", config_version),
                            "field_group": field_payload.get("group", ""),
                            "field_name": field_payload.get("name", ""),
                            "field_synonym": field_payload.get("synonym", ""),
                            "field_type": format_requisite_type_display(field_payload),
                            "field_tabular_section": field_payload.get("tabular_section") or "",
                        },
                    )
                )
    ranked.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("object_name", "")).lower(),
            str(item[1].get("field_name", "")).lower(),
        )
    )
    return [item for _, item in ranked[:limit]]


def _search_metadata_substring(
    client: Any,
    collection_name: str,
    q: str,
    type_filter: str | None,
    filt: Any,
    limit: int,
    max_points: int = _SEARCH_METADATA_SUBSTRING_MAX_POINTS,
) -> list[dict[str, Any]]:
    """Scroll + substring match by name/full_name. Stops after max_points to avoid slow full scan."""
    base_variants = _metadata_query_variants(q)
    if " " in (q or "").strip():
        variants = list(dict.fromkeys(base_variants + _metadata_nl_word_variants(q)))
    else:
        variants = base_variants
    exact: list[dict[str, Any]] = []
    startswith: list[dict[str, Any]] = []
    contains: list[dict[str, Any]] = []
    offset: Any | None = None
    seen = 0
    while seen < max_points:
        batch_size = min(500, limit * 4, max_points - seen)
        points, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=filt,
            limit=batch_size,
            offset=offset,
        )
        if not points:
            break
        seen += len(points)
        for pt in points:
            payload = getattr(pt, "payload", None) or {}
            if type_filter and payload.get("object_type") != type_filter:
                continue
            priority = _metadata_match_priority(payload, variants)
            if priority > 2:
                continue
            if "id" not in payload:
                payload["id"] = getattr(pt, "id", None)
            item = cast(dict[str, Any], dict(payload))
            if priority == 0:
                exact.append(item)
            elif priority == 1:
                startswith.append(item)
            else:
                contains.append(item)
        if len(exact) >= limit:
            break
        if offset is None:
            break
    return (exact + startswith + contains)[:limit]


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
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Backward-compatible metadata lookup.

    Default path is now indexed exact lookup first, semantic search second.
    Broad substring scroll is degraded fallback only and disabled by default.
    """
    exact = search_metadata_exact(
        query,
        type_filter,
        config_version,
        client=client,
        collection_name=collection_name,
        limit=limit,
    )
    if exact:
        return exact[:limit]
    if use_semantic:
        semantic = search_metadata_semantic(
            query,
            type_filter,
            config_version,
            client=client,
            collection_name=collection_name,
            limit=limit,
            query_vector=query_vector,
        )
        if semantic or not use_hybrid:
            return semantic[:limit]
    if not use_hybrid:
        return []
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return []
    client = client or _get_default_client()
    degraded = _search_metadata_substring(
        client,
        collection_name,
        (query or "").strip().lower(),
        _guess_type_filter(query, type_filter),
        _base_metadata_filter(
            config_version=config_version,
            type_filter=_guess_type_filter(query, type_filter),
            qmodels=qmodels,
        ),
        limit,
        max_points=min(limit * 100, 500),
    )
    return degraded[:limit]


def _metadata_object_id_lookup_candidates(object_id: str) -> list[str]:
    raw = (object_id or "").strip()
    if not raw:
        return []
    return [raw]


def get_metadata_object(
    object_id: str,
    *,
    config_version: str | None = None,
    client: Any | None = None,
    collection_name: str = "onec_config_metadata",
) -> dict[str, Any] | None:
    """Return single metadata object payload by its id.

    If config_version is given, only the object from that configuration is returned.
    Expects canonical ``Type.Name`` id (see payload ``id`` in Qdrant).
    """
    if not object_id:
        return None
    try:
        from qdrant_client import models as qmodels  # type: ignore[import-not-found]
    except Exception:
        return None

    client = client or _get_default_client()
    cfg = str(config_version).strip() if config_version else ""
    for candidate in _metadata_object_id_lookup_candidates(object_id):
        must: list[Any] = [
            qmodels.FieldCondition(key="id", match=qmodels.MatchValue(value=candidate))
        ]
        if cfg:
            must.append(
                qmodels.FieldCondition(
                    key="config_version",
                    match=qmodels.MatchValue(value=cfg),
                )
            )
        filt = qmodels.Filter(must=must)
        points, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=filt,
            limit=1,
            offset=None,
        )
        if points:
            pt = points[0]
            payload = getattr(pt, "payload", None) or {}
            if "id" not in payload:
                payload["id"] = getattr(pt, "id", None)
            return cast(dict[str, Any], payload)
    return None


# Note: search/read helpers (e.g. search_metadata_by_name, get_metadata_object)
# are added in later iterations and will reuse the same payload schema.
