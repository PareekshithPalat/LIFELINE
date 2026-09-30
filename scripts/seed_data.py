import json
import os
import sys

# Ensure root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.enums import MemoryTier, RiskLevel
from models.schemas import EvidenceItem, PersonalProfile, IncidentObservation, compute_evidence_hash
from edge.qdrant.client import get_qdrant_manager
from edge.sync.controller import get_sync_controller

def seed_database():
    print("--- Seeding Lifeline Edge Memory ---")
    qdrant = get_qdrant_manager()
    sync = get_sync_controller()

    # 1. Seed Trusted Protocols
    trusted_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "trusted_protocols.json"))
    if os.path.exists(trusted_file):
        with open(trusted_file, "r", encoding="utf-8") as f:
            protocols = json.load(f)
            print(f"Found {len(protocols)} clinical trusted protocols. Indexing in Qdrant Edge...")
            for p in protocols:
                item = EvidenceItem.model_validate(p)
                qdrant.upsert_evidence(item)
                print(f"  + Indexed [{item.tier.value}] {item.title}")
    else:
        print("Warning: trusted_protocols.json not found!")

    # 2. Seed Personal Profile
    personal_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "default_personal.json"))
    if os.path.exists(personal_file):
        with open(personal_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
            profile = PersonalProfile.model_validate(p_data)
            
            # Create personal memory evidence item
            allergies_str = ", ".join(profile.allergies)
            meds_str = ", ".join(profile.current_medications)
            conditions_str = ", ".join(profile.chronic_conditions)
            
            content = (
                f"Personal Emergency Profile for {profile.full_name}:\n"
                f"Blood Group: {profile.blood_group}\n"
                f"Allergies: {allergies_str}\n"
                f"Current Medications: {meds_str}\n"
                f"Chronic Conditions: {conditions_str}\n"
                f"ICE Instructions: {profile.ice_instructions}\n"
                f"Notes: {profile.medical_notes}"
            )
            personal_item = EvidenceItem(
                id=f"profile-{profile.user_id}",
                tier=MemoryTier.PERSONAL,
                title=f"Emergency Profile - {profile.full_name}",
                content=content,
                tags=["profile", "personal", "allergies", "blood_group", "ice"],
                risk_level=RiskLevel.HIGH,
                contraindications=[f"Patient allergic to {a}" for a in profile.allergies],
                author="user_personal_vault",
                version=profile.version,
                verified=True
            )
            qdrant.upsert_evidence(personal_item)
            print(f"  + Indexed [{personal_item.tier.value}] {personal_item.title}")

    # 3. Seed Sample Incident Observation
    incident_item = EvidenceItem(
        id="incident-obs-01",
        tier=MemoryTier.INCIDENT,
        title="Incident Timeline: On-Scene Observation",
        content="Patient was found seated, conscious but dyspneic with audible expiratory wheeze. Vitals at scene: Pulse 108 bpm, SpO2 91% on room air. Albuterol inhaler administered 2 puffs at 12:05.",
        tags=["incident", "vitals", "wheezing", "asthma", "timeline"],
        risk_level=RiskLevel.HIGH,
        contraindications=[],
        author="first_responder_field",
        version=1,
        verified=True
    )
    qdrant.upsert_evidence(incident_item)
    print(f"  + Indexed [{incident_item.tier.value}] {incident_item.title}")

    stats = qdrant.get_stats()
    print("\n--- Edge Memory Seeded Successfully! ---")
    for k, v in stats.items():
        print(f"  Collection {k}: {v.get('points_count', 0)} items")

if __name__ == "__main__":
    seed_database()
