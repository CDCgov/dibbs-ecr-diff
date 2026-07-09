from core.cda.fallback_keys import secondary_discriminator, soft_context_key
from core.cda.key_models import RootExtension
from helpers import observation


def test_soft_context_key_uses_full_direct_template_id_root_extensions():
    first = observation(
        """
        <templateId root="2" extension="b"/>
        <templateId root="1"/>
        """
    )
    second = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="b"/>
        """
    )
    different_extension = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="c"/>
        """
    )

    assert soft_context_key(first) == soft_context_key(second)
    assert soft_context_key(first) != soft_context_key(different_extension)


def test_statement_id_fallback_keys_use_root_extension_payloads():
    element = observation(
        """
        <id root="statement-id-root" extension="statement-id-ext"/>
        """
    )
    expected = (
        "id",
        (RootExtension(root="statement-id-root", extension="statement-id-ext"),),
    )

    assert secondary_discriminator(element) == expected
    assert soft_context_key(element) == expected


def test_statement_id_fallback_keys_use_all_complete_direct_id_root_extensions():
    first = observation(
        """
        <id root="statement-b" extension="2"/>
        <id root="statement-a" extension="1"/>
        <id root="statement-b" extension="2"/>
        <id root="root-only-is-ignored"/>
        <id extension="extension-only-is-ignored"/>
        """
    )
    second = observation(
        """
        <id root="statement-a" extension="1"/>
        <id root="statement-b" extension="2"/>
        """
    )
    expected = (
        "id",
        (
            RootExtension(root="statement-a", extension="1"),
            RootExtension(root="statement-b", extension="2"),
        ),
    )

    assert secondary_discriminator(first) == expected
    assert secondary_discriminator(first) == secondary_discriminator(second)
    assert soft_context_key(first) == expected
    assert soft_context_key(first) == soft_context_key(second)
