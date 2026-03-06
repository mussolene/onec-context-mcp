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


def _parse_root(root: Element) -> dict:
    """Extract attributes and commands from Form root element."""
    attrs: list[dict] = []
    for attr in _iter_tag(root, "Attribute"):
        name = attr.get("name", "")
        type_str = ""
        for type_el in _iter_tag(attr, "Type"):
            t = _text(type_el)
            if t:
                type_str = t
                break
        attrs.append({"name": name, "type": type_str})

    cmds: list[dict] = []
    for cmd in _iter_tag(root, "Command"):
        name = cmd.get("name", "")
        action = name
        for action_el in _iter_tag(cmd, "Action"):
            t = _text(action_el)
            if t:
                action = t
                break
        cmds.append({"name": name, "action": action})

    return {"attributes": attrs, "commands": cmds}


def parse_form_xml(xml_content: str) -> dict:
    """Parse Form.xml content and return attributes and commands.
    Uses defusedxml when available to prevent XXE/entity expansion on untrusted input.
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
