from __future__ import annotations

from app.prompts import contractor_prompt
from app.config import get_settings


class FakeLead(dict):
    def __getitem__(self, key: str) -> str:
        return str(super().__getitem__(key))


def test_prompt_mentions_project_and_privacy() -> None:
    get_settings.cache_clear()
    prompt = contractor_prompt(
        FakeLead(
            name="Test Contractor",
            category="handyman",
            notes="test notes",
        )
    )
    assert "10 by 10 Janssens/Exaco Modern greenhouse" in prompt
    assert "You may provide the customer's phone number and full project address" in prompt
    get_settings.cache_clear()


def test_prompt_sticks_to_the_brief() -> None:
    prompt = contractor_prompt(
        FakeLead(
            name="Test Contractor",
            category="handyman",
            notes="test notes",
        )
    )

    assert "Follow the job brief exactly" in prompt
    assert "Ask whether they are insured" not in prompt
    assert "insurance" not in prompt.lower()
