from __future__ import annotations

from .db import upsert_lead


LEADS = [
    {
        "name": "Demo Greenhouse Builder",
        "phone": "+17165550101",
        "category": "greenhouse_builder",
        "source_url": "https://example.com/greenhouses",
        "origin_address": "Exampletown, NY",
        "distance_miles": 8.0,
        "drive_minutes": 15,
        "service_area": "Example County",
        "notes": "Demo nearby greenhouse builder. Replace with real researched leads before outreach.",
        "priority": 100,
    },
    {
        "name": "Demo Shed Company",
        "phone": "+17165550102",
        "category": "shed_greenhouse_referral",
        "source_url": "https://example.com/sheds",
        "origin_address": "Exampleville, NY",
        "distance_miles": 12.0,
        "drive_minutes": 22,
        "service_area": "Nearby counties",
        "notes": "Demo shed company that might refer greenhouse or outdoor-structure installers.",
        "priority": 95,
    },
    {
        "name": "Demo General Contractor",
        "phone": "+17165550103",
        "category": "general_contractor",
        "source_url": "https://example.com/contractor",
        "origin_address": "Sample City, NY",
        "distance_miles": 20.0,
        "drive_minutes": 35,
        "service_area": "Regional",
        "notes": "Demo general contractor. Ask whether they handle customer-owned kit assembly.",
        "priority": 90,
    },
    {
        "name": "Demo Handyman",
        "phone": "+17165550104",
        "category": "handyman_assembly",
        "source_url": "https://example.com/handyman",
        "origin_address": "Sample Junction, NY",
        "distance_miles": 28.0,
        "drive_minutes": 45,
        "service_area": "Regional",
        "notes": "Demo handyman lead for outdoor assembly work.",
        "priority": 85,
    },
    {
        "name": "Demo Landscape Contractor",
        "phone": "+17165550105",
        "category": "landscape_construction",
        "source_url": "https://example.com/landscape",
        "origin_address": "Sample Falls, NY",
        "distance_miles": 32.0,
        "drive_minutes": 50,
        "service_area": "Regional",
        "notes": "Demo landscape contractor for jobs involving site prep or outdoor structures.",
        "priority": 80,
    },
    {
        "name": "Demo Referral Source",
        "phone": "+17165550106",
        "category": "manufacturer_referral",
        "source_url": "https://example.com/manufacturer",
        "origin_address": "Remote Office",
        "service_area": "Manufacturer referral",
        "notes": "Demo manufacturer/referral source. Ask for local installer referrals.",
        "priority": 75,
    },
    {
        "name": "Demo Backup Contractor",
        "phone": "+17165550107",
        "category": "general_contractor",
        "source_url": "https://example.com/backup",
        "origin_address": "Far Sample, NY",
        "distance_miles": 55.0,
        "drive_minutes": 82,
        "service_area": "Regional",
        "notes": "Demo backup lead inside the default drive-time cap.",
        "priority": 70,
    },
    {
        "name": "Demo Too-Far Contractor",
        "phone": "+17165550108",
        "category": "general_contractor",
        "source_url": "https://example.com/too-far",
        "origin_address": "Distant Sample, NY",
        "distance_miles": 95.0,
        "drive_minutes": 125,
        "service_area": "Distant region",
        "notes": "Demo lead outside the default drive-time cap.",
        "priority": 10,
        "status": "too_far",
    },
]


def main() -> None:
    for lead in LEADS:
        upsert_lead(**lead)
    print(f"seeded {len(LEADS)} leads")


if __name__ == "__main__":
    main()
