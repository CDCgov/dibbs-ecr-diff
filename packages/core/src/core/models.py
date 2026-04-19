from typing import Final

from pydantic import BaseModel

type NamespaceMap = dict[str, str]

HL7_NAMESPACE: Final[str] = "urn:hl7-org:v3"

HL7_NS: Final[NamespaceMap] = {"hl7": HL7_NAMESPACE}

HL7_XSI_NS: Final[NamespaceMap] = {
    "hl7": HL7_NAMESPACE,
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


class DiffingOptions(BaseModel):
    """Diffing options model."""

    file1: str
    file2: str
    out1: str
    out2: str
    out3: str
    out5: str
    no_prefer_updates: bool
    debug_match: bool
    no_huge: bool
