"""Teste pentru learning_core.bootstrap — confirmă idempotența register_default_algorithms()."""
from learning_core import model_registry
from learning_core.bootstrap import register_default_algorithms


def test_register_default_algorithms_idempotent():
    model_registry._clear_registry_for_tests()
    try:
        register_default_algorithms()
        register_default_algorithms()  # nu trebuie să arunce a doua oară
        assert ("xgboost_v1", "1") in model_registry.list_available()
    finally:
        model_registry._clear_registry_for_tests()
