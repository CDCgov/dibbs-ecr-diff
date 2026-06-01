from core import constants


def test_namespace_constants_are_internally_consistent():
    assert constants.NAMESPACES[constants.HL7_PREFIX] == constants.HL7_NS
    assert constants.NAMESPACES[constants.SDTC_PREFIX] == constants.SDTC_NS
    assert constants.NAMESPACES[constants.XSI_PREFIX] == constants.XSI_NS
    assert constants.HL7_NAMESPACE == {constants.HL7_PREFIX: constants.HL7_NS}
    assert constants.XSI_TYPE_ATTR == f"{{{constants.XSI_NS}}}type"


def test_identity_key_constants_separate_strong_and_weak_attributes():
    assert constants.DIRECT_ID_IDENTITY_ATTRS == ("ID", "id")
    assert constants.ROOT_EXTENSION_KEY_ATTRS == ("root", "extension")
    assert constants.CODE_KEY_ATTRS == ("code", "codeSystem")
    assert constants.STRONG_KEY_ATTRS == (
        "ID",
        "id",
        "root",
        "extension",
        "code",
        "codeSystem",
    )
    assert constants.WEAK_KEY_ATTRS == ("classCode", "typeCode", "use")
