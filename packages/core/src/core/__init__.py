"""Core Difference in Docs functionality."""

from lxml import etree

from .models import DiffingOptions


def diff_xml(opts: DiffingOptions) -> str:
    """Returns a hello world string."""
    return "hello world"
