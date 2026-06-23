from core.cda.key_models import (
    DirectChildIdElementSetKey,
    DirectChildTemplateIdElementSetKey,
    DirectIdAttributeKey,
    NestedClinicalStatementIdAttributeKey,
    NestedClinicalStatementIdElementSetKey,
    NestedSectionIdElementSetKey,
    RootExtension,
)


def test_id_attribute_key_classes_are_distinct_key_variants():
    assert DirectIdAttributeKey(name="ID", value="same-id") != (
        NestedClinicalStatementIdAttributeKey(name="ID", value="same-id")
    )


def test_root_extension_set_key_classes_are_distinct_key_variants():
    root_extensions = (RootExtension(root="same-root", extension="same-extension"),)

    assert DirectChildIdElementSetKey(root_extensions=root_extensions) != (
        NestedClinicalStatementIdElementSetKey(root_extensions=root_extensions)
    )
    assert DirectChildIdElementSetKey(root_extensions=root_extensions) != (
        NestedSectionIdElementSetKey(root_extensions=root_extensions)
    )
    assert DirectChildTemplateIdElementSetKey(root_extensions=root_extensions) != (
        DirectChildIdElementSetKey(root_extensions=root_extensions)
    )
