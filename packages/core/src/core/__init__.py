"""Core Difference in Docs functionality."""

from lxml import etree

from .diff import diff_nodes
from .models import DiffingOptions


def diff_xml(opts: DiffingOptions) -> str:
    """Returns a XML diff string."""
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=not opts.no_huge)

    # parse xml files
    tree_1 = etree.parse(opts.file1, parser)
    tree_2 = etree.parse(opts.file2, parser)

    root_1 = tree_1.getroot()
    root_2 = tree_2.getroot()
    root_namespace_map = root_1.nsmap

    # determine if *any* changes exist (order insensitive)
    # may be able to skip the fingerprinting
    # instead canoncalize the string and do a string comparison
    # did_not_change = is_canonically_eq(root_1, root_2)

    # outputs 1 + 2: pruned diffs
    out_1, out_2 = diff_nodes(root_1, root_2, True, root_namespace_map)

    return "hello world"
