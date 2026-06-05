from core import constants


def test_namespace_constants_are_internally_consistent():
    assert constants.NAMESPACES[constants.HL7_PREFIX] == constants.HL7_NS
    assert constants.NAMESPACES[constants.SDTC_PREFIX] == constants.SDTC_NS
    assert constants.NAMESPACES[constants.XSI_PREFIX] == constants.XSI_NS


def test_key_attribute_constants_preserve_grouped_key_concepts():
    assert constants.DIRECT_ID_KEY_ATTRS == ("ID", "id")
    assert constants.ROOT_EXTENSION_KEY_ATTRS == ("root", "extension")
    assert constants.CODE_KEY_ATTRS == ("code", "codeSystem")
    assert constants.WEAK_KEY_ATTRS == ("classCode", "typeCode", "use")
