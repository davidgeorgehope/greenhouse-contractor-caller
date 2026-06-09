from __future__ import annotations

from app.seed import LEADS


def test_seed_has_realistic_leads() -> None:
    assert len(LEADS) >= 8
    assert all(lead["phone"].startswith("+1") for lead in LEADS)
    assert LEADS[0]["category"] == "greenhouse_builder"


def test_callable_leads_have_location_gate_metadata() -> None:
    for lead in LEADS:
        if lead.get("category") == "manufacturer_referral":
            continue
        assert lead.get("distance_miles") is not None, lead["name"]
        assert lead.get("drive_minutes") is not None, lead["name"]


def test_too_far_demo_lead_is_not_in_active_call_queue() -> None:
    lead = next(lead for lead in LEADS if lead["name"] == "Demo Too-Far Contractor")
    assert lead["status"] == "too_far"
    assert lead["drive_minutes"] > 90
