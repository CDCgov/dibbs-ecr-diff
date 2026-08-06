from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree
from lxml.etree import _Element

ASSETS_DIR = Path(__file__).parent.parent / "assets"


def load_asset_str(path_from_assets_dir: str) -> str:
    """
    Loads an asset file as a raw string.
    """
    file_path: Path = ASSETS_DIR / path_from_assets_dir
    if not file_path.exists():
        raise FileNotFoundError(f"Asset file not found: {file_path}")

    with open(file_path, encoding="utf-8") as file:
        return file.read()


def load_asset_xml(path_from_assets_dir: str) -> etree._Element:
    """
    Loads and parses an XML asset file into an `lxml` `_Element`.
    """
    xml_string: bytes = load_asset_str(path_from_assets_dir).encode("utf-8")
    # using a parser that removes blank text for cleaner test assertions
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.fromstring(xml_string, parser=parser)


@pytest.fixture(scope="session")
def eicr_1_cached_v3_1_1() -> _Element:
    """
    Loads the CDA_refined_eICR_1 document once per session.
    """
    return load_asset_xml("eicr_v3_1_1/CDA_refined_eICR_1.xml")


@pytest.fixture
def eicr_1_root_v3_1_1(eicr_1_cached_v3_1_1: _Element) -> _Element:
    """
    Mutable deep copy of the CDA_refined_eICR_1 root.
    """
    return deepcopy(eicr_1_cached_v3_1_1)


@pytest.fixture(scope="session")
def rr_1_cached_v1_1() -> _Element:
    """
    Loads the CDA_refined_RR_1 document once per session.
    """
    return load_asset_xml("eicr_v3_1_1/CDA_refined_RR_1.xml")


@pytest.fixture
def rr_1_root_v1_1(rr_1_cached_v1_1: _Element) -> _Element:
    """
    Mutable deep copy of the CDA_refined_RR_1 root.
    """
    return deepcopy(rr_1_cached_v1_1)
