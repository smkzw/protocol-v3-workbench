"""R02: primary independent-AI unusable must terminate the chain (unit)."""
import sys

sys.path.insert(0, "services/api")

from app.main import _independent_ai_primary_unusable_reason


def test_missing_config_names_the_missing_keys():
    reason = _independent_ai_primary_unusable_reason(
        {"WORKBENCH_AI_BASE_URL": "", "WORKBENCH_AI_API_KEY": "", "WORKBENCH_AI_MODEL": "x"}
    )
    assert "WORKBENCH_AI_BASE_URL" in reason
    assert "WORKBENCH_AI_API_KEY" in reason
    assert "WORKBENCH_AI_MODEL" not in reason


def test_complete_config_is_usable():
    assert (
        _independent_ai_primary_unusable_reason(
            {
                "WORKBENCH_AI_BASE_URL": "http://127.0.0.1:8002/v1",
                "WORKBENCH_AI_API_KEY": "sk-local",
                "WORKBENCH_AI_MODEL": "mtplx-flash-next-optimized-speed",
            }
        )
        == ""
    )
