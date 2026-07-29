import pandas as pd
from etl.safety_gate import classification
from etl.safety_gate.classification import classify_chunk

FAKE_SENSITIVE_SPECIES_NOS = {101}
FAKE_FLAGGED_RECORD_TYPES = {"roost"}
FAKE_DEFAULT_RESOLUTION_M = 10000
FAKE_D0_FLOOR_M = 100
FAKE_SPECIES_RESOLUTIONS_M = {}


def _patch_rules(monkeypatch):
    monkeypatch.setattr(classification, "SENSITIVE_SPECIES_NOS", FAKE_SENSITIVE_SPECIES_NOS)
    monkeypatch.setattr(classification, "FLAGGED_RECORD_TYPES", FAKE_FLAGGED_RECORD_TYPES)
    monkeypatch.setattr(classification, "DEFAULT_SENSITIVE_RESOLUTION_M", FAKE_DEFAULT_RESOLUTION_M)
    monkeypatch.setattr(classification, "D0_FLOOR_M", FAKE_D0_FLOOR_M)
    monkeypatch.setattr(classification, "SPECIES_RESOLUTIONS_M", FAKE_SPECIES_RESOLUTIONS_M)


def test_classify_chunk_flags_sensitive_species(monkeypatch):
    # Confirms a record with a sensitive species_no is flagged sensitive + blurred.
    # Expects is_sensitive=True, blurred=True, reason="sensitive_species", else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [101],
        "record_type": ["sighting"],
        "species_unresolved": [False],
    })
    result = classify_chunk(df)
    assert result["is_sensitive"].iloc[0] == True
    assert result["blurred"].iloc[0] == True
    assert result["sensitivity_reason"].iloc[0] == [
        "sensitive_species"
    ]

def test_classify_chunk_flags_sensitive_record_type(monkeypatch):
    # Confirms a flagged record_type is sensitive even with an ordinary species.
    # Expects is_sensitive=True, reason="sensitive_record_type", else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["roost"],
        "species_unresolved": [False],
    })
    result = classify_chunk(df)
    assert result["is_sensitive"].iloc[0] == True
    assert result["sensitivity_reason"].iloc[0] == [
        "sensitive_record_type"
    ]

def test_classify_chunk_fails_closed_on_unresolved_species(monkeypatch):
    # Confirms an unresolved species is always sensitive (D1 fail-closed).
    # Expects is_sensitive=True, reason="unresolved_species", else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [True],
    })
    result = classify_chunk(df)
    assert result["is_sensitive"].iloc[0] == True
    assert result["sensitivity_reason"].iloc[0] == [
        "unresolved_species"
    ]

def test_classify_chunk_records_multiple_reasons(monkeypatch):
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [101],
        "record_type": ["roost"],
        "species_unresolved": [False],
    })

    result = classify_chunk(df)

    assert result["sensitivity_reason"].iloc[0] == [
        "sensitive_record_type",
        "sensitive_species",
    ]

def test_classify_chunk_leaves_ordinary_record_unflagged(monkeypatch):
    # Confirms a record matching none of the triggers stays not sensitive.
    # Expects is_sensitive=False, blurred=False, reason="not_sensitive", else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
    })
    result = classify_chunk(df)
    assert result["is_sensitive"].iloc[0] == False
    assert result["blurred"].iloc[0] == False
    assert result["sensitivity_reason"].iloc[0] == "not_sensitive"


def test_classify_chunk_applies_default_resolution_to_sensitive_records(monkeypatch):
    # Confirms sensitive records get the default sensitive resolution (D2),
    # not the D0 floor.
    # Expects resolution_m == 10000, else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [101],
        "record_type": ["sighting"],
        "species_unresolved": [False],
    })
    result = classify_chunk(df)
    assert result["resolution_m"].iloc[0] == FAKE_DEFAULT_RESOLUTION_M


def test_classify_chunk_applies_floor_resolution_to_ordinary_records(monkeypatch):
    # Confirms non-sensitive records get the D0 floor resolution (100m),
    # not the sensitive default.
    # Expects resolution_m == 100, else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
    })
    result = classify_chunk(df)
    assert result["resolution_m"].iloc[0] == FAKE_D0_FLOOR_M


def test_classify_chunk_preserves_row_count(monkeypatch):
    # Confirms classify_chunk never drops or adds rows — sensitive records
    # must be flagged/blurred, not removed (D5).
    # Expects all 3 rows to remain, else fails.
    _patch_rules(monkeypatch)
    df = pd.DataFrame({
        "species_no": [101, 999, 999],
        "record_type": ["sighting", "roost", "sighting"],
        "species_unresolved": [False, False, False],
    })
    result = classify_chunk(df)
    assert len(result) == 3