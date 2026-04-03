"""Parse Form.xml from 1C EDT/XML to extract attributes and commands."""

from pathlib import Path
from xml.etree.ElementTree import Element  # for type hints; defusedxml returns compatible elements

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _text(el: Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _iter_tag(root: Element, local_name: str):
    """Yield elements whose local tag name matches."""
    for el in root.iter():
        if _strip_ns(el.tag) == local_name:
            yield el


def _type_text(el: Element) -> str:
    """Get type string from Type element: direct text or from v8:Type child."""
    t = _text(el)
    if t:
        return t
    for sub in el.iter():
        if sub is not el and (sub.text or "").strip():
            return (sub.text or "").strip()
    return ""


def _attr_type_data(attr: Element) -> dict:
    """Extract type from form Attribute: single, multiple (union), or defined type.

    Returns dict with type (str), optional types (list), optional defined_type (str).
    """
    result: dict = {"type": "", "types": [], "defined_type": None}
    collected: list[str] = []
    defined_name: str | None = None

    for el in attr.iter():
        tag = _strip_ns(el.tag)
        if tag in ("DefinedType", "definedtype"):
            for sub in el.iter():
                if sub is el:
                    continue
                if _strip_ns(sub.tag) in ("Name", "name"):
                    defined_name = (
                        _text(sub) or (sub.get("value") or sub.get("Value") or "").strip()
                    )
                    if defined_name:
                        break
            if not defined_name and _text(el):
                defined_name = _text(el)
            continue
        if tag in ("Types", "types"):
            for child in el:
                if _strip_ns(child.tag) in ("Type", "type"):
                    t = _type_text(child)
                    if t and t not in collected:
                        collected.append(t)
            continue
        if tag in ("Type", "type"):
            t = _type_text(el)
            if t and t not in collected:
                collected.append(t)

    if not collected:
        return result
    result["type"] = collected[0]
    result["types"] = collected
    if defined_name:
        result["defined_type"] = defined_name
    return result


def _parse_root(root: Element) -> dict:
    """Extract attributes and commands from Form root element (logform Form.xml)."""
    attrs: list[dict] = []
    for attr in _iter_tag(root, "Attribute"):
        name = attr.get("name", "")
        type_data = _attr_type_data(attr)
        rec: dict = {"name": name, "type": type_data.get("type") or ""}
        if type_data.get("types") and len(type_data["types"]) > 1:
            rec["types"] = type_data["types"]
        if type_data.get("defined_type"):
            rec["defined_type"] = type_data["defined_type"]
        attrs.append(rec)

    cmds: list[dict] = []
    for cmd in _iter_tag(root, "Command"):
        name = cmd.get("name", "")
        action = name
        for action_el in _iter_tag(cmd, "Action"):
            t = _text(action_el)
            if t:
                action = t
                break
        title = ""
        for title_el in _iter_tag(cmd, "Title"):
            for content_el in _iter_tag(title_el, "content"):
                title = _text(content_el)
                if title:
                    break
            if title:
                break
        cmds.append({"name": name, "action": action, "title": title})

    return {"attributes": attrs, "commands": cmds}


def parse_form_xml(xml_content: str) -> dict:
    """Parse Form.xml content and return attributes and commands.
    Expects elements with local names Attribute (form attributes: name, Type) and Command
    (form commands: name, Action). Uses defusedxml when available to prevent XXE.
    Returns {attributes: [{name, type}], commands: [{name, action}]}."""
    try:
        root = ET.fromstring(xml_content)
    except (ET.ParseError, Exception) as e:
        return {"error": str(e), "attributes": [], "commands": []}
    return _parse_root(root)


def get_form_metadata(form_xml_path: Path) -> dict:
    """Parse Form.xml file and return attributes and commands.
    Used by tests and file-based callers; MCP uses parse_form_xml(str) with in-memory content."""
    try:
        content = form_xml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": str(e), "attributes": [], "commands": []}
    return parse_form_xml(content)
