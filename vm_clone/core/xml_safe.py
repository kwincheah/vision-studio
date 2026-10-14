"""Safe XML parsing utility rejecting entity expansion and DTDs."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Union

_DANGEROUS_XML_PATTERN = re.compile(r"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


class DefusedXMLError(ValueError):
    """Raised when XML contains forbidden DTD or entity declarations."""
    pass


def safe_fromstring(xml_str: Union[str, bytes]) -> ET.Element:
    """Parse XML string securely, rejecting DOCTYPE/ENTITY declarations.

    Empty, blank and non-text input is rejected with an actionable message rather
    than the parser's bare "no element found", because the realistic causes are an
    empty project file and a file of the wrong type - both of which a user needs to
    be told about.  Malformed *non-empty* XML still raises `ET.ParseError`, which
    callers already handle.
    """
    if xml_str is None:
        raise ValueError("No XML content to parse (the file is empty or missing).")
    if not isinstance(xml_str, (str, bytes)):
        raise ValueError(
            f"Expected XML text, got {type(xml_str).__name__}.")

    if isinstance(xml_str, bytes):
        if not xml_str.strip():
            raise ValueError("No XML content to parse (the file is empty).")
        text = xml_str.decode("utf-8", errors="replace")
    else:
        if not xml_str.strip():
            raise ValueError("No XML content to parse (the file is empty).")
        text = xml_str

    if _DANGEROUS_XML_PATTERN.search(text):
        raise DefusedXMLError("XML contains forbidden DOCTYPE or ENTITY declaration.")

    try:
        return ET.fromstring(xml_str)
    except ET.ParseError:
        # Distinguish "this is not XML at all" from a damaged document: the first is
        # a wrong file type, the second is corruption, and they need different advice.
        head = text.lstrip()[:1]
        if head and head != "<":
            raise ValueError(
                "The selected file is not XML (it does not start with '<'); "
                "is it a project file from another application?")
        raise


def safe_parse_file(filepath: str) -> ET.ElementTree:
    """Parse XML file securely, rejecting DOCTYPE/ENTITY declarations."""
    with open(filepath, "rb") as f:
        content = f.read()
    text = content.decode("utf-8", errors="replace")
    if _DANGEROUS_XML_PATTERN.search(text):
        raise DefusedXMLError("XML file contains forbidden DOCTYPE or ENTITY declaration.")
    return ET.ElementTree(ET.fromstring(content))
