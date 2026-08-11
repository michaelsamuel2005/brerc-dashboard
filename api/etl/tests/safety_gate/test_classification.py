import pandas as pd

from etl.safety_gate.classification import (
    classify_chunk,
)


FAKE_SENSITIVE_SPECIES_NOS = {101}
FAKE_FLAGGED_RECORD_TYPES = {"roost"}
FAKE_DEFAULT_RESOLUTION_M = 10000
FAKE_D0_FLOOR_M = 100
FAKE_SPECIES_RESOLUTIONS_M = {}


def _patch_rules(monkeypatch):
    """
    Patch safety rules used by classify_chunk so tests
    do not depend on the real configuration or sensitive
    species CSV.
    """

    monkeypatch.setattr(
        "etl.safety_gate.classification.load_sensitive_species",
        lambda: (
            FAKE_SENSITIVE_SPECIES_NOS,
            set(),
        ),
    )

    monkeypatch.setattr(
        "etl.safety_gate.classification.FLAGGED_RECORD_TYPES",
        FAKE_FLAGGED_RECORD_TYPES,
    )

    monkeypatch.setattr(
        "etl.safety_gate.classification.DEFAULT_SENSITIVE_RESOLUTION_M",
        FAKE_DEFAULT_RESOLUTION_M,
    )

    monkeypatch.setattr(
        "etl.safety_gate.classification.D0_FLOOR_M",
        FAKE_D0_FLOOR_M,
    )

    monkeypatch.setattr(
        "etl.safety_gate.classification.SPECIES_RESOLUTIONS_M",
        FAKE_SPECIES_RESOLUTIONS_M,
    )


def test_classify_chunk_flags_source_sensitive_record(monkeypatch):
    # Confirms a source record explicitly marked sensitive
    # is flagged sensitive + blurred.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
        "sensitive": ["Yes"],
    })

    result = classify_chunk(df)

    assert result["is_sensitive"].iloc[0] == True
    assert result["blurred"].iloc[0] == True
    assert result["sensitivity_reason"].iloc[0] == [
        "source_sensitive"
    ]


def test_classify_chunk_source_sensitive_gets_default_resolution(
    monkeypatch,
):
    # Confirms a source record marked sensitive gets the sensitive
    # resolution rather than the D0 100m floor.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
        "sensitive": ["Yes"],
    })

    result = classify_chunk(df)

    assert (
        result["resolution_m"].iloc[0]
        == FAKE_DEFAULT_RESOLUTION_M
    )


def test_classify_chunk_source_not_sensitive_remains_ordinary(
    monkeypatch,
):
    # Confirms a source record explicitly marked "No" is not made
    # sensitive when none of the other sensitivity rules apply.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
        "sensitive": ["No"],
    })

    result = classify_chunk(df)

    assert result["is_sensitive"].iloc[0] == False
    assert result["blurred"].iloc[0] == False
    assert (
        result["resolution_m"].iloc[0]
        == FAKE_D0_FLOOR_M
    )
    assert (
        result["sensitivity_reason"].iloc[0]
        == "not_sensitive"
    )


def test_classify_chunk_source_sensitive_is_case_insensitive(
    monkeypatch,
):
    # Confirms common source representations of "Yes" are all
    # treated as sensitive.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [999, 999, 999],
        "record_type": ["sighting", "sighting", "sighting"],
        "species_unresolved": [False, False, False],
        "sensitive": ["Yes", "yes", " YES "],
    })

    result = classify_chunk(df)

    assert result["is_sensitive"].tolist() == [
        True,
        True,
        True,
    ]

    assert result["blurred"].tolist() == [
        True,
        True,
        True,
    ]

    assert result["resolution_m"].tolist() == [
        FAKE_DEFAULT_RESOLUTION_M,
        FAKE_DEFAULT_RESOLUTION_M,
        FAKE_DEFAULT_RESOLUTION_M,
    ]


def test_classify_chunk_handles_missing_sensitive_column(
    monkeypatch,
):
    # Confirms supplied CSV data can still be processed when the
    # source does not provide a "sensitive" column.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [999],
        "record_type": ["sighting"],
        "species_unresolved": [False],
    })

    result = classify_chunk(df)

    assert result["is_sensitive"].iloc[0] == False
    assert result["blurred"].iloc[0] == False
    assert (
        result["resolution_m"].iloc[0]
        == FAKE_D0_FLOOR_M
    )
    assert (
        result["sensitivity_reason"].iloc[0]
        == "not_sensitive"
    )


def test_classify_chunk_records_multiple_reasons_including_source_sensitive(
    monkeypatch,
):
    # Confirms the source sensitivity flag is added alongside
    # other sensitivity reasons rather than replacing them.
    _patch_rules(monkeypatch)

    df = pd.DataFrame({
        "species_no": [101],
        "record_type": ["roost"],
        "species_unresolved": [False],
        "sensitive": ["Yes"],
    })

    result = classify_chunk(df)

    assert result["sensitivity_reason"].iloc[0] == [
        "sensitive_record_type",
        "sensitive_species",
        "source_sensitive",
    ]