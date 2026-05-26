"""
core/xml_utils.py

Low-level XML utility functions with no dependency on diffing logic.
Covers text normalisation, XPath helpers, element construction,
fingerprinting, and self-contained XML snippet serialisation.
"""

from copy import deepcopy
from typing import List, Optional, Set, Tuple, Dict

from lxml import etree

from core.constants import NAMESPACES, XSI_TYPE_ATTR


# ---------------------------------------------------------------------------
# Text and tag helpers
# ---------------------------------------------------------------------------

def normalize_text(text: Optional[str]) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    if text is None:
        return ""
    return " ".join(text.split())


def localname(elem: etree._Element) -> str:
    """Return the local part of an element's tag, stripping any namespace URI."""
    return etree.QName(elem).localname


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def fingerprint(elem: etree._Element) -> tuple:
    """
    Order-insensitive recursive fingerprint for an element subtree.

    Two elements with identical fingerprints are considered unchanged.
    Child fingerprints are sorted before returning the parent fingerprint.
    Any reordering of child fingerprints is not considered a change.

    Note: elem.tail is included so that tail-text differences in mixed-content
    narrative (e.g. text between inline <content> elements) are detected. 
    e.g. two elem.tail in the following are "and chills, as well as" and "."
    <text>
      <paragraph>The patient presented with 
        <content styleCode="Bold">fever</content>
         and chills, as well as 
        <content styleCode="Bold">cough</content>
        .
      </paragraph>
    </text>
    """
    tag      = elem.tag
    text     = normalize_text(elem.text)
    tail     = normalize_text(elem.tail)
    attrs    = tuple(sorted(elem.attrib.items()))
    children = sorted(fingerprint(child) for child in elem if isinstance(child.tag, str))
    return (tag, text, tail, attrs, tuple(children))


# ---------------------------------------------------------------------------
# XPath query helpers (all use the hl7: namespace prefix)
# ---------------------------------------------------------------------------

def _xpath_first_attribute_value(
        element: etree._Element,
        xpath_expression: str,
) -> Optional[str]:
    """
    Return the first attribute value matched by an XPath expression. 

    Returns None when there are no matches. If multiple values match, the first
    value in document order is returned. 

    The expression should select a node-set, such as './hl7:id/@root'. Scalar
    XPath expressions such as string(...), count(...), or boolean(...) are not
    accepted.
    """
    attribute_values = element.xpath(xpath_expression, namespaces=NAMESPACES)

    if not isinstance(attribute_values, list):
        raise TypeError(
            f"XPath expression {xpath_expression!r} returned "
            f"{type(attribute_values).__name__}, expected a list of attribute values."
        )

    if not attribute_values:
        return None

    first_attribute_value = attribute_values[0]

    if not isinstance(first_attribute_value, str):
        raise TypeError(
            f"XPath expression {xpath_expression!r} returned "
            f"{type(first_attribute_value).__name__}, expected an attribute string."
        )

    return str(first_attribute_value)


def _collect_subtree_attribute_values(elem: etree._Element, node_path: str, attribute_name: str, limit: int = 6) -> List[str]:
    """
    Used when collecting several attribute values from a subtree, such as
    gathering all templateId/@root values from nested elements to build a
    composite identity key.
    
    Collect up to `limit` values of `attribute_name` from elements matched by
    the ElementPath `node_path`, relative to `elem`.

    Matching nodes that do not have `attribute_name` are skipped.

    Uses iterfind() so iteration can stop as soon as enough values are found,
    unlike xpath(), which evaluates the full result set first. This guards 
    against large subtree evaluation.
    """
    if limit <= 0:
        return []
    
    attribute_values: List[str] = []
    for node in elem.iterfind(node_path, namespaces=NAMESPACES):
        attribute_value = node.get(attribute_name)
        if attribute_value is not None:
            attribute_values.append(attribute_value)
            if len(attribute_values) >= limit:
                break
    return attribute_values


def _xpath_first_element(
        element: etree._Element,
        xpath_expression: str,
) -> Optional[etree._Element]:
    """
    Return the first element matched by an XPath expression.

    Returns None when there are no matches. If multiple elements match, the
    first element in document order is returned.
    """
    elements = element.xpath(xpath_expression, namespaces=NAMESPACES)
    
    if not isinstance(elements, list):
        raise TypeError(
            f"XPath expression {xpath_expression!r} returned "
            f"{type(elements).__name__}, expected a list of elements."
        )

    if not elements:
        return None
    
    first_element = elements[0]
    
    if not isinstance(first_element, etree._Element):
        raise TypeError(
            f"XPath expression {xpath_expression!r} returned "
            f"{type(first_element).__name__}, expected an XML element."
        )
    
    return first_element


def _complete_attribute_pair(node: Optional[etree._Element],
                             attr1: str, attr2: str) -> Optional[Tuple[str, str]]:
    """
    Return the values of two related attributes only when both are present.

    This is useful when the two attributes are meaningful as a single
    composite value, such as `root` + `extension` or `code` + `codeSystem`.
    Returning None for partial data lets callers treat the pair as one
    atomic value for matching, identity checks, or key construction.
    """
    if node is None:
        return None
    value1 = node.get(attr1)
    value2 = node.get(attr2)
    return (value1, value2) if value1 is not None and value2 is not None else None


# ---------------------------------------------------------------------------
# Self-contained XML snippet serialisation
# ---------------------------------------------------------------------------

def _collect_standalone_namespace_requirements(snippet_root_elem: etree._Element) -> tuple[Set[str], Dict[str, str]]:
    """
    Return the namespace data needed to serialize `snippet_root_elem`
    as a standalone snippet.

    Returns:
    - `self_and_subtree_tag_and_attr_namespaces`: namespace URIs referenced 
      by element names and attribute names in the self and subtree
    - `attribute_value_prefix_namespace_dict`: prefix-to-URI bindings used 
      lexically in QName-valued attribute values that should be declared on 
      the snippet root when it is safe to do so

    Currently, QName-valued attribute handling is limited to prefixed
    `xsi:type` values, which are common in CDA.
    
    Currently, QName-valued attribute handling is limited to prefixed
    `xsi:type` values, which is the main QName-valued attribute pattern 
    seen in CDA.
    """
    self_and_subtree_tag_and_attr_namespaces: Set[str] = set()
    attribute_value_prefix_namespace_dict: Dict[str, str] = {}
    
    # snippet_root_elem.iter() walks the entire descendant tree 
    # recursively and includes snippet_root_elem itself
    for current_node in snippet_root_elem.iter(tag=etree.Element):
        namespace = etree.QName(current_node.tag).namespace
        if namespace:
            self_and_subtree_tag_and_attr_namespaces.add(namespace)
        for attr_name, attr_value in current_node.attrib.items():
            attr_qname = etree.QName(attr_name)
            if attr_qname.namespace:
                self_and_subtree_tag_and_attr_namespaces.add(attr_qname.namespace)

            # Preserve prefixes used lexically in QName-valued attribute values,
            # e.g. `cda` inside of xsi:type="cda:CD". 
            # lxml will preserve namespaces in element and attribute names, but 
            # it does not understand that the string value "cda:CD" also depends 
            # on the lexical prefix `cda` remaining bound.
            if attr_name != XSI_TYPE_ATTR:
                continue

            attr_value_text = attr_value.strip()
            attr_value_prefix, separator, _ = attr_value_text.partition(":")
            if not separator:
                continue

            # Resolve the prefix used inside the xsi:type value against the namespace
            # bindings that are in scope on this node. For xsi:type="cda:CD", this finds
            # the URI for "cda".
            current_node_namespace_for_attr_value_prefix = current_node.nsmap.get(attr_value_prefix)
            # If the prefix is not actually declared in this node's namespace context,
            # there is no safe namespace binding to hoist onto the standalone root.
            if not current_node_namespace_for_attr_value_prefix:
                continue
            
            root_namespace_for_prefix = snippet_root_elem.nsmap.get(attr_value_prefix)
            # If the snippet root already binds this prefix to a different URI,
            # do not hoist the current node's binding to the root. A single root
            # namespace map cannot bind the same prefix to two different URIs.
            #
            # The conflicting binding is expected to remain local to the descendant
            # subtree when children are deep-copied.
            if (root_namespace_for_prefix is not None
                    and root_namespace_for_prefix != current_node_namespace_for_attr_value_prefix
            ):
                continue

            existing_namespace_for_prefix = attribute_value_prefix_namespace_dict.get(
                attr_value_prefix
            )

            # First safe binding seen for this prefix: add it to the snippet root.
            if existing_namespace_for_prefix is None:
                attribute_value_prefix_namespace_dict[attr_value_prefix] = current_node_namespace_for_attr_value_prefix
                continue

            # Same prefix and same URI: already handled.
            if existing_namespace_for_prefix == current_node_namespace_for_attr_value_prefix:
                continue

            # The same prefix resolves to another URI somewhere else in the snippet.
            # A single root namespace map cannot declare both meanings for the same prefix.
            #
            # Keep the binding we already chose for the standalone root. The conflicting
            # binding should remain local to the descendant subtree when children are
            # deep-copied into the rebuilt root.
            continue
   
    return self_and_subtree_tag_and_attr_namespaces, attribute_value_prefix_namespace_dict


def _build_standalone_xml_snippet_namespace_map(elem: etree._Element) -> Dict[Optional[str], str]:
    """
    Build the namespace map for serialising elem as a standalone XML snippet.

    The element's own namespace is always written as the default namespace
    using the `None` key. Prefixes required by QName-valued attribute strings,
    such as `xsi:type="cda:CD"`, are added next, even when they point to the
    same URI as the default namespace.

    Other in-scope prefixes are added only when their namespace URI is used by
    element names or attribute names in the subtree. Unneeded same-URI aliases
    are skipped to keep the standalone output compact.
    """
    elem_namespace = etree.QName(elem.tag).namespace
    (self_and_subtree_tag_and_attr_namespaces, 
     attribute_value_prefix_namespace_dict) = _collect_standalone_namespace_requirements(elem)

    standalone_namespace_map: Dict[Optional[str], str] = {}
    if elem_namespace:
        standalone_namespace_map[None] = elem_namespace

    standalone_namespace_map.update(attribute_value_prefix_namespace_dict)

    self_and_inherited_namespace_map = elem.nsmap
    for prefix, namespace in self_and_inherited_namespace_map.items():
        if prefix is None:
            continue
        # This prefix was already added explicitly, usually because an
        # attribute value like xsi:type="cda:CD" needs that exact prefix.
        # Do not overwrite or re-process it.
        if prefix in standalone_namespace_map:
            continue
        # The element's own namespace is already set as the default namespace.
        # Skip extra named prefixes for that same URI unless they were already
        # added above because an attribute value needs the exact prefix.
        if namespace == elem_namespace:
            continue
        if namespace in self_and_subtree_tag_and_attr_namespaces:
            standalone_namespace_map[prefix] = namespace

    return standalone_namespace_map


def build_standalone_xml_string(snippet_root_elem: etree._Element) -> str:
    """
    Serialize `snippet_root_elem` to a self-contained, namespace-correct XML string.

    Parentless elements are assumed to already be standalone; call this before
    detaching a subtree if it relies on namespace declarations from ancestors.

    When an element is extracted from inside a CDA document, some namespace
    declarations it relies on may live on ancestor elements. For attached
    subtrees, rebuild only the snippet root with a complete namespace map,
    then deep-copy the original children so subtree content, child tails, and
    child-local namespace declarations are preserved.

    Child tails are preserved by the deep copy, which keeps mixed-content text
    inside the snippet. The snippet root's own tail is intentionally excluded
    because it belongs to the surrounding parent, not to the standalone root.
    """
    if snippet_root_elem.getparent() is None:
        return etree.tostring(snippet_root_elem, encoding="unicode", pretty_print=True,
                              with_tail=False)

    standalone_namespace_map = _build_standalone_xml_snippet_namespace_map(snippet_root_elem)
    standalone_root_elem = etree.Element(
        snippet_root_elem.tag,
        attrib=dict(snippet_root_elem.attrib),
        nsmap=standalone_namespace_map,
    )
    standalone_root_elem.text = snippet_root_elem.text
    standalone_root_elem.tail = None
    for child in snippet_root_elem:
        # Deep-copy each child so its subtree content is preserved, including text,
        # child tails, attributes, and descendant-local namespace declarations.
        #
        # When the copied child is appended, lxml may suppress namespace declarations
        # that are already available on the rebuilt root. Prefix rebindings that are
        # local to a child subtree can still appear when needed.
        standalone_root_elem.append(deepcopy(child))

    return etree.tostring(standalone_root_elem, encoding="unicode", pretty_print=True,
                          with_tail=False)