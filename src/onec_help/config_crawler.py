"""Utilities for crawling 1C configuration files into a structured model.

This module is responsible only for *reading* configuration metadata from a
directory with an exported 1C configuration (EDT project or \"Выгрузка в файлы\").

High‑level responsibilities:
- Detect configuration root inside a given directory.
- Read configuration‑level metadata (name, config_version, optional platform_version).
- Enumerate configuration objects (documents, catalogs, registers, etc.) with stable ids.
- Read object-level metadata from XML when present (full_name/synonym, requisites, tabular sections).
- Produce an in‑memory `CrawlResult` that downstream code can index into Qdrant.

Actual persistence (Qdrant upserts) is handled by `metadata_graph`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Optional XML parsing for object metadata (full_name, requisites, tabular sections)
try:
    import defusedxml.ElementTree as _ET
except ImportError:
    import xml.etree.ElementTree as _ET  # noqa: S405


@dataclass(slots=True)
class ConfigObject:
    """Single configuration object (document, catalog, register, form, etc.).

    Fields are intentionally generic so that we can support both EDT projects and
    \"Выгрузка конфигурации в файлы\" без привязки к конкретной структуре каталогов.
    """

    id: str
    """Stable identifier within one configuration version.

    Should be unique inside a single `config_version`. The concrete scheme
    (e.g. `<object_type>/<name>` or GUID from metadata) is decided by crawler.
    """

    object_type: str
    """High‑level type: e.g. 'Document', 'Catalog', 'RegisterAccumulation', 'Enum', 'Form'."""

    name: str
    """Technical name of the object (internal identifier in configuration)."""

    full_name: str | None = None
    """Human‑readable name (presentation) if доступно в метаданных."""

    path: str | None = None
    """Relative path to the primary file/folder of the object inside configuration root."""

    attributes: dict[str, Any] = field(default_factory=dict)
    """Additional attributes taken from configuration files (e.g. subtype, dimensions)."""


@dataclass(slots=True)
class ConfigRelation:
    """Directed relation between configuration objects.

    Examples:
    - Document -> RegisterAccumulation (writes_to / reads_from)
    - Catalog -> Form (has_form)
    - Any -> Subsystem (belongs_to_subsystem)
    """

    from_id: str
    to_id: str
    relation_type: str


@dataclass(slots=True)
class CrawlResult:
    """Result of crawling a configuration directory.

    This object is the canonical bridge between file system representation of a
    configuration and the Qdrant metadata index.
    """

    root_dir: Path
    """Absolute path to configuration root that was crawled."""

    config_name: str
    """Human‑readable configuration name (e.g. 'Бухгалтерия предприятия, редакция 3.0')."""

    config_version: str
    """Full configuration version string as reported in metadata (e.g. '3.0.123.45')."""

    platform_version: str | None = None
    """Optional 1C platform version (e.g. '8.5.1.1150') if available in metadata."""

    objects: list[ConfigObject] = field(default_factory=list)
    relations: list[ConfigRelation] = field(default_factory=list)

    def iter_objects(self, object_type: str | None = None) -> Iterable[ConfigObject]:
        """Iterate over objects, optionally filtered by `object_type`."""
        if object_type is None:
            return iter(self.objects)
        return (o for o in self.objects if o.object_type == object_type)

    def iter_relations(self, relation_type: str | None = None) -> Iterable[ConfigRelation]:
        """Iterate over relations, optionally filtered by `relation_type`."""
        if relation_type is None:
            return iter(self.relations)
        return (r for r in self.relations if r.relation_type == relation_type)


def _strip_ns(tag: str) -> str:
    """Return local name of XML tag (strip namespace)."""
    return tag.split("}")[-1] if "}" in tag else tag


def _text_el(el: Any) -> str:
    """First non-empty direct text or tail, or from first child."""
    if el is None:
        return ""
    t = (el.text or "").strip()
    if t:
        return t
    for c in el:
        t = _text_el(c) or (c.tail or "").strip()
        if t:
            return t
    return ""


def _attr_type_str(el: Any, local: Any) -> str:
    """Extract single type string from Attribute element (backward compat)."""
    data = _attr_type_data(el, local)
    return data.get("type") or ""


def _attr_type_data(el: Any, local: Any) -> dict[str, Any]:
    """Extract type from Attribute element: single, multiple (union), or defined type.

    Returns dict with:
    - type: main/first type string (always set if any type found)
    - types: list of all type strings (if union or defined type with several)
    - defined_type: name of ОпределяемыйТип if present
    """
    out: dict[str, Any] = {"type": "", "types": [], "defined_type": None}
    direct = (el.get("type") or el.get("Type") or "").strip()
    if direct:
        out["type"] = direct
        out["types"] = [direct]
        return out

    collected: list[str] = []
    defined_name: str | None = None

    for c in el.iter():
        if local(c.tag) in ("DefinedType", "definedtype"):
            # Определяемый тип: имя типа и ниже — состав типов
            for sub in c.iter():
                if sub is c:
                    continue
                if local(sub.tag) in ("Name", "name"):
                    defined_name = _text_el(sub).strip() or (sub.get("value") or sub.get("Value") or "").strip()
                    if defined_name:
                        break
            if not defined_name and (c.text or "").strip():
                defined_name = (c.text or "").strip()
            continue
        if local(c.tag) not in ("Type", "type", "Types", "types"):
            continue
        if local(c.tag).lower() == "types":
            for child in c:
                if local(child.tag) in ("Type", "type"):
                    t = _text_el(child).strip()
                    if not t:
                        for sub in child.iter():
                            if sub is not child and (sub.text or "").strip():
                                t = (sub.text or "").strip()
                                break
                    if t and t not in collected:
                        collected.append(t)
            continue
        # Single Type element
        t = _text_el(c).strip()
        if not t:
            for sub in c.iter():
                if sub is not c and (sub.text or "").strip():
                    t = (sub.text or "").strip()
                    break
        if t and t not in collected:
            collected.append(t)

    if not collected:
        return out
    out["type"] = collected[0]
    out["types"] = collected
    if defined_name:
        out["defined_type"] = defined_name
    return out


def _parse_object_metadata_root(root: Any) -> dict[str, Any]:
    """Parse Document/Catalog/... root element into full_name, requisites, tabular_sections.

    Used by both _read_object_metadata_xml (dir) and _read_object_metadata_from_file (sibling xml).
    """
    result: dict[str, Any] = {"full_name": None, "requisites": [], "tabular_sections": []}

    def local(tag: str) -> str:
        return _strip_ns(tag) if isinstance(tag, str) else ""

    # Synonym / full_name (prefer v8:content over v8:lang in item)
    for el in root.iter():
        if local(el.tag) == "Synonym":
            val = (el.get("value") or el.get("Value") or "").strip()
            if not val and len(el) > 0:
                for c in el:
                    if local(c.tag).lower() == "content":
                        val = _text_el(c).strip()
                        if val:
                            break
                if not val:
                    for c in el:
                        if local(c.tag).lower() in ("value", "item"):
                            for sub in c:
                                if local(sub.tag).lower() == "content":
                                    val = _text_el(sub).strip()
                                    break
                            if val:
                                break
                if not val:
                    val = _text_el(el)
            if val and isinstance(val, str):
                result["full_name"] = val.strip()
                break
            # Plain text inside Synonym (no v8:item)
            if not val:
                val = _text_el(el)
            if val and isinstance(val, str):
                result["full_name"] = val.strip()
                break
    if result["full_name"] is None:
        for el in root.iter():
            if local(el.tag) == "FullName":
                result["full_name"] = _text_el(el).strip() or None
                break
    if result["full_name"] is None:
        for el in root.iter():
            if local(el.tag) == "Property" and (el.get("name") or el.get("Name")) in (
                "Synonym",
                "FullName",
                "Presentation",
            ):
                result["full_name"] = _text_el(el).strip() or None
                break

    # Attributes (requisites): from ChildObjects/Attributes under Document/Catalog/...
    top_level: list[Any] = (
        [root]
        if local(root.tag)
        in (
            "Document",
            "Catalog",
            "InformationRegister",
            "AccumulationRegister",
            "Enum",
            "BusinessProcess",
            "Task",
        )
        else list(root)
    )
    for top in top_level:
        if local(top.tag) not in (
            "Document",
            "Catalog",
            "InformationRegister",
            "AccumulationRegister",
            "Enum",
            "BusinessProcess",
            "Task",
        ):
            continue
        for attrs_container in top:
            if local(attrs_container.tag) not in ("Attributes", "ChildObjects"):
                continue
            for el in attrs_container:
                if local(el.tag) != "Attribute":
                    continue
                name = el.get("name") or el.get("Name") or ""
                if not name:
                    for c in el.iter():
                        if local(c.tag) == "Name":
                            name = _text_el(c)
                            if name:
                                break
                    if not name:
                        for c in el:
                            if local(c.tag) == "Name":
                                name = _text_el(c)
                                break
                if name:
                    type_data = _attr_type_data(el, local)
                    req: dict[str, Any] = {
                        "name": name.strip(),
                        "type": type_data.get("type") or "",
                    }
                    if type_data.get("types") and len(type_data["types"]) > 1:
                        req["types"] = type_data["types"]
                    if type_data.get("defined_type"):
                        req["defined_type"] = type_data["defined_type"]
                    length_val = el.get("Length") or el.get("length")
                    if length_val is not None:
                        try:
                            req["length"] = int(length_val)
                        except (TypeError, ValueError):
                            pass
                    for c in el:
                        if local(c.tag) in ("Length", "length") and (c.text or "").strip():
                            try:
                                req["length"] = int((c.text or "").strip())
                            except (TypeError, ValueError):
                                pass
                            break
                    result["requisites"].append(req)
            break
        break
    seen_r: set[str] = set()
    uniq_r: list[dict] = []
    for r in result["requisites"]:
        n = (r.get("name") or "").strip()
        if n and n not in seen_r:
            seen_r.add(n)
            uniq_r.append(r)
    result["requisites"] = uniq_r

    # TabularSections: name + requisites (Attribute children with types)
    seen_ts: set[str] = set()
    for el in root.iter():
        if local(el.tag) != "TabularSection":
            continue
        name = el.get("name") or el.get("Name") or ""
        if not name:
            for c in el.iter():
                if local(c.tag) == "Name":
                    name = _text_el(c)
                    if name:
                        break
            if not name:
                for c in el:
                    if local(c.tag) == "Name":
                        name = _text_el(c)
                        break
        if not name or name.strip() in seen_ts:
            continue
        seen_ts.add(name.strip())
        ts_entry: dict[str, Any] = {"name": name.strip(), "requisites": []}
        # Child Attributes: ChildObjects/Attributes/Attribute or Attributes/Attribute
        for cont in el:
            if local(cont.tag) not in ("Attributes", "ChildObjects"):
                continue
            for attrs_container in [cont] if local(cont.tag) == "Attributes" else cont:
                if local(attrs_container.tag) != "Attributes":
                    continue
                for attr_el in attrs_container:
                    if local(attr_el.tag) != "Attribute":
                        continue
                    aname = attr_el.get("name") or attr_el.get("Name") or ""
                    if not aname:
                        for c in attr_el.iter():
                            if local(c.tag) == "Name":
                                aname = _text_el(c)
                                if aname:
                                    break
                    if aname:
                        type_data = _attr_type_data(attr_el, local)
                        req: dict[str, Any] = {"name": aname.strip(), "type": type_data.get("type") or ""}
                        if type_data.get("types") and len(type_data["types"]) > 1:
                            req["types"] = type_data["types"]
                        if type_data.get("defined_type"):
                            req["defined_type"] = type_data["defined_type"]
                        length_val = attr_el.get("Length") or attr_el.get("length")
                        if length_val is not None:
                            try:
                                req["length"] = int(length_val)
                            except (TypeError, ValueError):
                                pass
                        ts_entry["requisites"].append(req)
                break
        result["tabular_sections"].append(ts_entry)
    # Dedupe by name (keep first)
    by_name: dict[str, dict[str, Any]] = {}
    for t in result["tabular_sections"]:
        n = t.get("name") if isinstance(t, dict) else str(t)
        if n and n not in by_name:
            by_name[n] = t if isinstance(t, dict) else {"name": n, "requisites": []}
    result["tabular_sections"] = list(by_name.values())

    return result


def _read_object_metadata_from_file(xml_path: Path) -> dict[str, Any]:
    """Parse object metadata from a single XML file (e.g. sibling Documents/ИмяОбъекта.xml).

    Same structure as _read_object_metadata_xml result; used for hierarchical export where
    the object definition is in a file next to the object folder, with full types in v8:Type.
    """
    result: dict[str, Any] = {"full_name": None, "requisites": [], "tabular_sections": []}
    if not xml_path.is_file():
        return result
    try:
        tree = _ET.parse(xml_path)  # noqa: S314
        root = tree.getroot()
    except Exception:
        return result
    return _parse_object_metadata_root(root)


def _read_object_metadata_xml(obj_dir: Path) -> dict[str, Any]:
    """Parse object metadata from XML in object directory (full_name, requisites, tabular_sections).

    Supports hierarchical \"выгрузка в файлы\" and EDT-style exports. Looks for Object.xml,
    Document.xml, Catalog.xml, etc. and extracts Synonym/full_name, Attributes, TabularSections.
    Returns dict: full_name (str|None), requisites (list of {name, type?}), tabular_sections (list of str).
    """
    result: dict[str, Any] = {"full_name": None, "requisites": [], "tabular_sections": []}
    if not obj_dir.is_dir():
        return result
    # Prefer main object description file; skip Form.xml, Template.xml, etc.
    skip = {"Form.xml", "Template.xml", "Help.xml", "Rights.xml", "Schedule.xml", "Predefined.xml"}
    candidates: list[Path] = []
    for p in obj_dir.iterdir():
        if p.suffix.lower() == ".xml" and p.name not in skip:
            candidates.append(p)
    # Prefer Object.xml, then type-specific names
    for name in (
        "Object.xml",
        "Document.xml",
        "Catalog.xml",
        "InformationRegister.xml",
        "AccumulationRegister.xml",
        "Enum.xml",
    ):
        p = obj_dir / name
        if p in candidates or p.exists():
            path = p
            break
    else:
        path = candidates[0] if candidates else None
    if not path or not path.is_file():
        return result
    try:
        tree = _ET.parse(path)  # noqa: S314
        root = tree.getroot()
    except Exception:
        return result
    return _parse_object_metadata_root(root)


# Map ConfigDumpInfo object type prefix to our object_type (folder name)
_DUMPINFO_TYPE_TO_OBJECT_TYPE: dict[str, str] = {
    "Document": "Document",
    "Catalog": "Catalog",
    "DocumentRef": "Document",
    "AccumulationRegister": "RegisterAccumulation",
    "InformationRegister": "RegisterInformation",
    "Enum": "Enum",
    "BusinessProcess": "BusinessProcess",
    "Task": "Task",
    "Report": "Report",
    "DataProcessor": "DataProcessor",
    "CommonAttribute": "CommonAttribute",
    "CommonForm": "Form",
    "CommonCommand": "CommonCommand",
    "CommonModule": "CommonModule",
}


def _read_config_dump_info(root_dir: Path) -> dict[str, dict[str, Any]]:
    """Parse ConfigDumpInfo.xml (hierarchical export from configurator).

    Returns dict: object_id (e.g. 'Document/РеализацияТоваровУслуг') -> {
        requisites: [{"name": "..."}],
        tabular_sections: [{"name": "Товары", "attributes": ["Номенклатура", ...]}],
    }.
    Metadata name format: Document.РеализацияТоваровУслуг.Attribute.Имя,
    Document.РеализацияТоваровУслуг.TabularSection.Товары,
    Document.РеализацияТоваровУслуг.TabularSection.Товары.Attribute.Номенклатура.
    """
    result: dict[str, dict[str, Any]] = {}
    path = root_dir / "ConfigDumpInfo.xml"
    if not path.is_file():
        return result
    try:
        tree = _ET.parse(path)  # noqa: S314
        root = tree.getroot()
    except Exception:
        return result
    ns = _strip_ns  # local name

    def obj_id(otype: str, oname: str) -> str:
        ot = _DUMPINFO_TYPE_TO_OBJECT_TYPE.get(otype, otype)
        return f"{ot}/{oname}"

    for el in root.iter():
        tag = ns(el.tag) if hasattr(el, "tag") else ""
        if tag != "Metadata":
            continue
        name_attr = el.get("name")
        if not name_attr or not isinstance(name_attr, str):
            continue
        parts = name_attr.split(".")
        if len(parts) < 2:
            continue
        otype, oname = parts[0], parts[1]
        if otype not in (
            "Document",
            "Catalog",
            "AccumulationRegister",
            "InformationRegister",
            "Enum",
            "BusinessProcess",
            "Task",
            "Report",
            "DataProcessor",
            "CommonAttribute",
        ):
            continue
        oid = obj_id(otype, oname)
        if oid not in result:
            result[oid] = {"requisites": [], "tabular_sections": []}
        data = result[oid]

        if len(parts) == 2:
            continue  # just object reference
        if len(parts) >= 4 and parts[2] == "Attribute":
            req_name = parts[3]
            if req_name:
                existing = {r["name"] for r in data["requisites"]}
                if req_name not in existing:
                    data["requisites"].append({"name": req_name, "type": ""})
        if len(parts) >= 4 and parts[2] == "TabularSection":
            ts_name = parts[3]
            if not ts_name:
                continue
            # tabular_sections: list of {name, requisites: [{name}, ...]}
            tabs = data["tabular_sections"]
            if len(parts) == 4:
                # Document.X.TabularSection.Товары — только имя секции
                if not any(isinstance(t, dict) and t.get("name") == ts_name for t in tabs):
                    tabs.append({"name": ts_name, "requisites": []})
            elif len(parts) >= 6 and parts[4] == "Attribute":
                # Document.X.TabularSection.Товары.Attribute.Номенклатура
                attr_name = parts[5]
                if not attr_name:
                    continue
                ts_entry = next((t for t in tabs if isinstance(t, dict) and t.get("name") == ts_name), None)
                if ts_entry is None:
                    ts_entry = {"name": ts_name, "requisites": []}
                    tabs.append(ts_entry)
                reqs = ts_entry.setdefault("requisites", [])
                if not any(r.get("name") == attr_name for r in reqs if isinstance(r, dict)):
                    reqs.append({"name": attr_name, "type": ""})
    return result


def _read_configuration_xml(root_dir: Path) -> dict[str, Any]:
    """Read Configuration.xml (root) for config name, version, synonym.

    Returns dict with config_name, config_version, config_synonym (presentation)
    when Configuration.xml exists and has Configuration/Properties.
    """
    out: dict[str, Any] = {}
    path = root_dir / "Configuration.xml"
    if not path.is_file():
        return out
    try:
        tree = _ET.parse(path)  # noqa: S314
        root = tree.getroot()
    except Exception:
        return out
    ns = _strip_ns
    for conf in root.iter():
        if ns(conf.tag) != "Configuration":
            continue
        for props in conf:
            if ns(props.tag) != "Properties":
                continue
            for c in props:
                local_name = ns(c.tag)
                if local_name == "Name":
                    out["config_name"] = _text_el(c).strip() or None
                elif local_name == "Version":
                    out["config_version"] = _text_el(c).strip() or None
                elif local_name == "Synonym":
                    for item in c:
                        if ns(item.tag) == "item":
                            lang = ""
                            content = ""
                            for sub in item:
                                sn = ns(sub.tag)
                                if sn == "lang":
                                    lang = _text_el(sub).strip().lower()
                                elif sn == "content":
                                    content = _text_el(sub).strip()
                            if content and (lang == "ru" or not out.get("config_synonym")):
                                out["config_synonym"] = content
            break
        break
    return out


def _looks_like_config_root(path: Path) -> bool:
    """True if path looks like the root of an exported 1C configuration."""
    if not path.is_dir():
        return False
    if (path / "config.json").is_file():
        return True
    if (path / "Configuration.xml").is_file():
        return True
    for name in (
        "Documents",
        "Catalogs",
        "Document",
        "Catalog",
        "Enums",
        "CommonModules",
        "RegistersAccumulation",
        "RegistersInformation",
    ):
        if (path / name).is_dir():
            return True
    return False


def find_config_root(base_dir: Path) -> Path | None:
    """Resolve one config export root from a base directory (first found).

    Prefer find_config_roots() to index all exports in the directory.
    """
    roots = find_config_roots(base_dir)
    return roots[0] if roots else None


def find_config_roots(base_dir: Path) -> list[Path]:
    """Return all config export roots under base_dir.

    When ONEC_CONFIG_SOURCE_DIR points to a container dir (e.g. data/config) that
    holds several export subdirs (e.g. AccountingCorp30_latest, Enterprise20_latest),
    returns all such subdirs in sorted order. If base_dir itself is a config root,
    returns [base_dir]. Otherwise returns the list of all child dirs that look like
    export roots, so that all configs in the folder get into the index.
    """
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    base_dir = base_dir.resolve()
    if _looks_like_config_root(base_dir):
        return [base_dir]
    return [
        child
        for child in sorted(base_dir.iterdir())
        if child.is_dir() and not child.name.startswith(".") and _looks_like_config_root(child)
    ]


def crawl_config(root_dir: Path) -> CrawlResult:
    """Crawl 1C configuration exported to `root_dir` and return structured result.

    This function is intentionally kept simple in the initial implementation and
    is expanded in subsequent iterations:
    - For now we only support synthetic test fixtures used in unit tests.
    - Later it will be extended to understand real export formats (EDT / 1C Configurator),
      guided by 1C documentation and live examples.
    """

    if not root_dir.exists() or not root_dir.is_dir():
        raise FileNotFoundError(f"Configuration root not found: {root_dir}")

    # Config-level metadata: config.json first, then Configuration.xml (hierarchical export)
    meta: dict[str, Any] = {}
    json_path = root_dir / "config.json"
    if json_path.is_file():
        import json

        meta = json.loads(json_path.read_text(encoding="utf-8"))
    config_name = str(meta.get("config_name") or root_dir.name)
    config_version = str(meta.get("config_version") or "0.0.0.0")
    platform_version = meta.get("platform_version")
    cfg_xml = _read_configuration_xml(root_dir)
    if cfg_xml.get("config_name"):
        config_name = cfg_xml["config_name"]
    if cfg_xml.get("config_version"):
        config_version = cfg_xml["config_version"]
    if cfg_xml.get("config_synonym"):
        config_name = cfg_xml["config_synonym"] or config_name

    # ConfigDumpInfo.xml (hierarchical export): object requisites and tabular section names
    dump_info = _read_config_dump_info(root_dir)

    # Discover basic objects from well-known top-level folders.
    objects: list[ConfigObject] = []
    type_by_folder = {
        "Documents": "Document",
        "Document": "Document",
        "Catalogs": "Catalog",
        "Catalog": "Catalog",
        "DataProcessors": "DataProcessor",
        "Reports": "Report",
        "CommonModules": "CommonModule",
        "InformationRegisters": "InformationRegister",
        "AccumulationRegisters": "AccumulationRegister",
        "AccountingRegisters": "AccountingRegister",
        "CalculationRegisters": "CalculationRegister",
        "RegistersAccumulation": "RegisterAccumulation",  # old-style export
        "RegistersInformation": "RegisterInformation",    # old-style export
        "ExchangePlans": "ExchangePlan",
        "BusinessProcesses": "BusinessProcess",
        "Tasks": "Task",
        "ChartsOfAccounts": "ChartOfAccounts",
        "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
        "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
        "DocumentJournals": "DocumentJournal",
        "ScheduledJobs": "ScheduledJob",
        "Sequences": "Sequence",
        "Enums": "Enum",
        "Enum": "Enum",
        "Forms": "Form",
        "CommonAttributes": "CommonAttribute",
    }
    for child in root_dir.iterdir():
        if not child.is_dir():
            continue
        object_type = type_by_folder.get(child.name)
        if not object_type:
            continue
        for obj_dir in child.iterdir():
            if not obj_dir.is_dir():
                continue
            name = obj_dir.name
            rel_path = obj_dir.relative_to(root_dir).as_posix()
            obj_id = f"{object_type}/{name}"
            obj_meta = _read_object_metadata_xml(obj_dir)
            # Hierarchical export: object definition often in sibling file Documents/Имя.xml
            sibling_xml = obj_dir.parent / (name + ".xml")
            if sibling_xml.is_file():
                sibling_meta = _read_object_metadata_from_file(sibling_xml)
                if sibling_meta.get("full_name"):
                    obj_meta["full_name"] = sibling_meta["full_name"]
                if sibling_meta.get("requisites"):
                    obj_meta["requisites"] = sibling_meta["requisites"]
                if sibling_meta.get("tabular_sections"):
                    obj_meta["tabular_sections"] = sibling_meta["tabular_sections"]
            full_name = obj_meta.get("full_name")
            attrs: dict[str, Any] = {}
            if obj_meta.get("requisites"):
                attrs["requisites"] = obj_meta["requisites"]
            if obj_meta.get("tabular_sections"):
                attrs["tabular_sections"] = obj_meta["tabular_sections"]
            # Merge from ConfigDumpInfo (hierarchical export) if still missing
            if obj_id in dump_info:
                di = dump_info[obj_id]
                if not attrs.get("requisites") and di.get("requisites"):
                    attrs["requisites"] = di["requisites"]
                if not attrs.get("tabular_sections") and di.get("tabular_sections"):
                    attrs["tabular_sections"] = di["tabular_sections"]
                elif attrs.get("tabular_sections") and di.get("tabular_sections"):
                    # Дополнить реквизиты ТЧ из dump, если в XML секция без реквизитов
                    dump_tabs = {t["name"]: t for t in di["tabular_sections"] if isinstance(t, dict) and t.get("name")}
                    for tab in attrs["tabular_sections"]:
                        if not isinstance(tab, dict) or tab.get("requisites"):
                            continue
                        name_ts = tab.get("name")
                        if name_ts and name_ts in dump_tabs and dump_tabs[name_ts].get("requisites"):
                            tab["requisites"] = list(dump_tabs[name_ts]["requisites"])
            attrs["config_name"] = config_name
            attrs["config_version"] = config_version
            objects.append(
                ConfigObject(
                    id=obj_id,
                    object_type=object_type,
                    name=name,
                    full_name=full_name,
                    path=rel_path,
                    attributes=attrs,
                )
            )

    # Forms under each object: object_dir/Forms/FormName/Ext/Form.xml (requisites, commands).
    # Связь объект → форма: parent_id у формы, relations для графа.
    relations: list[ConfigRelation] = []
    try:
        from .form_metadata import get_form_metadata as _get_form_metadata
    except ImportError:
        _get_form_metadata = None

    if _get_form_metadata:
        for obj in list(objects):
            if not obj.path:
                continue
            forms_dir = root_dir / obj.path / "Forms"
            if not forms_dir.is_dir():
                continue
            parent_id_flat = obj.id.replace("/", ".")
            for form_dir in forms_dir.iterdir():
                if not form_dir.is_dir():
                    continue
                form_name = form_dir.name
                ext_form = form_dir / "Ext" / "Form.xml"
                if not ext_form.is_file():
                    continue
                form_meta = _get_form_metadata(ext_form)
                if form_meta.get("error"):
                    continue
                form_attrs: dict[str, Any] = {}
                if form_meta.get("attributes"):
                    form_attrs["form_requisites"] = form_meta["attributes"]
                if form_meta.get("commands"):
                    form_attrs["form_commands"] = form_meta["commands"]
                form_id = f"Form/{parent_id_flat}.{form_name}"
                form_attrs["parent_id"] = obj.id
                form_attrs["config_name"] = config_name
                form_attrs["config_version"] = config_version
                form_full_name = None
                form_sibling = forms_dir / (form_name + ".xml")
                if form_sibling.is_file():
                    try:
                        tree = _ET.parse(form_sibling)  # noqa: S314
                        root = tree.getroot()
                        for el in root.iter():
                            if _strip_ns(el.tag) == "Synonym":
                                for sub in el.iter():
                                    if _strip_ns(sub.tag).lower() == "content":
                                        form_full_name = _text_el(sub).strip()
                                        if form_full_name:
                                            break
                                if not form_full_name:
                                    form_full_name = _text_el(el).strip()
                                if form_full_name:
                                    break
                    except Exception:
                        pass
                form_path = f"{obj.path}/Forms/{form_name}"
                objects.append(
                    ConfigObject(
                        id=form_id,
                        object_type="Form",
                        name=form_name,
                        full_name=form_full_name or None,
                        path=form_path,
                        attributes=form_attrs,
                    )
                )
                relations.append(
                    ConfigRelation(from_id=obj.id, to_id=form_id, relation_type="has_form")
                )

    # Пустая конфигурация (только Configuration.xml, без объектов): одна синтетическая точка,
    # чтобы версия и имя конфигурации попали в индекс и отображались в списке версий.
    if not objects and (config_name or config_version or cfg_xml):
        objects.append(
            ConfigObject(
                id="Configuration",
                object_type="Configuration",
                name="",
                full_name=cfg_xml.get("config_synonym") or config_name or "",
                path="",
                attributes={
                    "requisites": [],
                    "tabular_sections": [],
                    "config_name": config_name,
                    "config_version": config_version,
                },
            )
        )

    return CrawlResult(
        root_dir=root_dir.resolve(),
        config_name=config_name,
        config_version=config_version,
        platform_version=platform_version,
        objects=objects,
        relations=relations,
    )
