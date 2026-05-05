from core.rule_configuration import Configuration


def test_rule_configuration(sample_rule_configuration_json: dict) -> None:
    rule_config = Configuration.model_validate(sample_rule_configuration_json)
    assert isinstance(rule_config, Configuration)
