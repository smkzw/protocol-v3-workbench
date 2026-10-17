"""Synthetic study records for the offline self-test.

These are TEST DATA (the synthetic profile named in the WP-M2-CORPUS contract),
not product logic and not real study records. They intentionally mirror the
ClinicalTrials.gov API v2 study JSON shape so that the exact same parser
(``retrieve.parse_study``) runs in offline and online modes.

Fixture plan (3 fake studies, per contract):
1. NCT00000001 — same-drug + same-target Phase 3 registration study with
   protocol+SAP files (the B12 case: a registered study of the profile's own
   drug must NOT be auto-excluded; it should rank highest).
2. NCT00000002 — same-indication study of a different drug, Phase 2, protocol
   file only, older start date (mid score).
3. NCT00000003 — adjacent study: shares only the molecule-class vocabulary
   (antibody), different indication, no route term, no target, no protocol
   file (lowest score).
"""
from __future__ import annotations

import copy
from typing import Any

# Fixture strategy pre-assignment: which retrieval strategy "found" each record
# (offline mode has no live query to match against).
FIXTURE_STRATEGY_HINTS = {
    "NCT00000001": ["same_target", "same_drug"],
    "NCT00000002": ["same_indication"],
    "NCT00000003": ["same_class_route"],
}


def fixture_study_same_drug_target() -> dict[str, Any]:
    """Fake CT.gov study: same drug, same target, Phase 3, protocol + SAP."""
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "briefTitle": "Phase 3 Study of 测试靶点X Inhibitor 测试药物A Tablets in Adult Subjects",
                "officialTitle": "A Randomized, Double-Blind, Placebo-Controlled Phase 3 Study of 测试药物A "
                "(测试靶点X Inhibitor) Oral Tablets",
            },
            "conditionsModule": {"conditions": ["类风湿关节炎"]},
            "designModule": {
                "phases": ["PHASE3"],
                "studyType": "INTERVENTIONAL",
                "enrollmentInfo": {"count": 600},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Fake Sponsor Pharma"},
                "collaborators": [{"name": "Fake CRO Corp"}],
            },
            "statusModule": {
                "overallStatus": "RECRUITING",
                "studyFirstPostDateStruct": {"date": "2024-01-15"},
                "studyLastUpdatePostDateStruct": {"date": "2026-08-01"},
            },
            "descriptionModule": {
                "briefSummary": "A Phase 3 oral small molecule study evaluating the safety and efficacy of "
                "测试药物A, an oral 测试靶点X inhibitor, compared with placebo."
            },
            "armsInterventionsModule": {
                "interventions": [
                    {"name": "测试药物A", "type": "DRUG"},
                    {"name": "Placebo oral tablet", "type": "DRUG"},
                ]
            },
        },
        "documentSection": {
            "largeDocumentModule": {
                "largeDocs": [
                    {"filename": "prot_0001.pdf", "hasProtocol": True, "hasSap": True,
                     "label": "Study Protocol", "typeAbbrev": "Prot"},
                ]
            }
        },
    }


def fixture_study_same_indication() -> dict[str, Any]:
    """Fake CT.gov study: same indication, different mechanism, Phase 2."""
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000002",
                "briefTitle": "Phase 2 Study of 对照药物B Injection in Adult Subjects with 类风湿关节炎",
            },
            "conditionsModule": {"conditions": ["类风湿关节炎"]},
            "designModule": {
                "phases": ["PHASE2"],
                "studyType": "INTERVENTIONAL",
                "enrollmentInfo": {"count": 240},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Another Fake Biotech"}},
            "statusModule": {
                "overallStatus": "COMPLETED",
                "studyFirstPostDateStruct": {"date": "2019-06-01"},
            },
            "descriptionModule": {
                "briefSummary": "A Phase 2 subcutaneous study of 对照药物B in adult subjects."
            },
            "armsInterventionsModule": {
                "interventions": [{"name": "对照药物B subcutaneous injection", "type": "DRUG"}]
            },
        },
        "documentSection": {
            "largeDocumentModule": {
                "largeDocs": [
                    {"filename": "prot_0002.pdf", "hasProtocol": True, "hasSap": False,
                     "label": "Study Protocol", "typeAbbrev": "Prot"},
                ]
            }
        },
    }


def fixture_study_adjacent() -> dict[str, Any]:
    """Fake CT.gov study: shares only molecule-class vocabulary, different indication."""
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000003",
                "briefTitle": "Phase 3 Study of MAB-017 Monoclonal Antibody in Plaque Disease",
            },
            "conditionsModule": {"conditions": ["Plaque Disease"]},
            "designModule": {
                "phases": ["PHASE3"],
                "studyType": "INTERVENTIONAL",
                "enrollmentInfo": {"count": 500},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Third Fake Institute"}},
            "statusModule": {
                "overallStatus": "ACTIVE_NOT_RECRUITING",
                "studyFirstPostDateStruct": {"date": "2022-03-20"},
            },
            "descriptionModule": {
                "briefSummary": "A Phase 3 intramuscular study of MAB-017, a monoclonal antibody."
            },
            "armsInterventionsModule": {
                "interventions": [{"name": "MAB-017 intramuscular injection", "type": "DRUG"}]
            },
        },
    }


def fixture_studies() -> list[dict[str, Any]]:
    """All three synthetic study records in CT.gov API v2 shape."""
    return [
        fixture_study_same_drug_target(),
        fixture_study_same_indication(),
        fixture_study_adjacent(),
    ]


def fixture_studies_copy() -> list[dict[str, Any]]:
    """Deep copies, so callers mutating records cannot corrupt the fixtures."""
    return copy.deepcopy(fixture_studies())
