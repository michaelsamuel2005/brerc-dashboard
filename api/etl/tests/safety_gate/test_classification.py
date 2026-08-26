import pandas as pd
import pytest

from etl.safety_gate.classification import (
    classify_chunk,
)


FAKE_SENSITIVE_SPECIES_NOS = {101}
FAKE_FLAGGED_RECORD_TYPES = {"roost"}
FAKE_DEFAULT_RESOLUTION_M = 10000
FAKE_D0_FLOOR_M = 100


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


def test_classify_chunk_flags_source_sensitive_record(monkeypatch):
    # Confirms a source record explicitly marked sensitive
    # is flagged sensitive + blurred.
    _patch_rules(monkeypatch)

    df = pd.DataFrame(
        {
            "species_no": [999],
            "record_type": ["sighting"],
            "species_unresolved": [False],
            "sensitive": ["Yes"],
        }
    )

    result = classify_chunk(df)

    assert result["is_sensitive"].iloc[0] == True
    assert result["blurred"].iloc[0] == True
    assert result["sensitivity_reason"].iloc[0] == ["source_sensitive"]


def test_classify_chunk_source_sensitive_gets_default_resolution(
    monkeypatch,
):
    # Confirms a source record marked sensitive gets the sensitive
    # resolution rather than the D0 100m floor.
    _patch_rules(monkeypatch)

    df = pd.DataFrame(
        {
            "species_no": [999],
            "record_type": ["sighting"],
            "species_unresolved": [False],
            "sensitive": ["Yes"],
        }
    )

    result = classify_chunk(df)

    assert result["resolution_m"].iloc[0] == FAKE_DEFAULT_RESOLUTION_M


def test_classify_chunk_source_not_sensitive_remains_ordinary(
    monkeypatch,
):
    # Confirms a source record explicitly marked "No" is not made
    # sensitive when none of the other sensitivity rules apply.
    _patch_rules(monkeypatch)

    df = pd.DataFrame(
        {
            "species_no": [999],
            "record_type": ["sighting"],
            "species_unresolved": [False],
            "sensitive": ["No"],
        }
    )

    result = classify_chunk(df)

    assert result["is_sensitive"].iloc[0] == False
    assert result["blurred"].iloc[0] == False
    assert result["resolution_m"].iloc[0] == FAKE_D0_FLOOR_M
    assert result["sensitivity_reason"].iloc[0] == "not_sensitive"


def test_classify_chunk_source_sensitive_is_case_insensitive(
    monkeypatch,
):
    # Confirms common source representations of "Yes" are all
    # treated as sensitive.
    _patch_rules(monkeypatch)

    df = pd.DataFrame(
        {
            "species_no": [999, 999, 999],
            "record_type": ["sighting", "sighting", "sighting"],
            "species_unresolved": [False, False, False],
            "sensitive": ["Yes", "yes", " YES "],
        }
    )

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


def _chunk_without_sensitive_column():
    return pd.DataFrame(
        {
            "species_no": [999],
            "record_type": ["sighting"],
            "species_unresolved": [False],
        }
    )


def test_classify_chunk_processes_a_source_declared_to_have_no_sensitive_column(
    monkeypatch,
):
    # This is the original test_classify_chunk_handles_missing_sensitive_column,
    # unchanged in what it asserts: supplied CSV data with no "sensitive" column
    # must still be processable, and must come out not-sensitive. The only
    # difference is that the caller now says so, rather than it being assumed.
    _patch_rules(monkeypatch)

    result = classify_chunk(
        _chunk_without_sensitive_column(),
        source_provides_sensitivity=False,
    )

    assert result["is_sensitive"].iloc[0] == False
    assert result["blurred"].iloc[0] == False
    assert result["resolution_m"].iloc[0] == FAKE_D0_FLOOR_M
    assert result["sensitivity_reason"].iloc[0] == "not_sensitive"


def test_classify_chunk_refuses_a_silently_missing_sensitive_column(
    monkeypatch,
):
    # The case the original could not distinguish: a source that DOES have a
    # sensitivity flag, where the column was renamed, dropped or misspelled
    # upstream. It arrives here looking exactly like the CSV case above, and
    # treating it as not-sensitive publishes every affected record at full
    # precision with nothing raised.
    _patch_rules(monkeypatch)

    with pytest.raises(ValueError, match="source_provides_sensitivity"):
        classify_chunk(_chunk_without_sensitive_column())


def test_classify_chunk_refuses_when_a_declared_column_is_absent(
    monkeypatch,
):
    # Declaring the source provides the flag and then not providing it is the
    # same failure wearing a different hat.
    _patch_rules(monkeypatch)

    with pytest.raises(ValueError, match="declared to provide"):
        classify_chunk(
            _chunk_without_sensitive_column(),
            source_provides_sensitivity=True,
        )


def test_classify_chunk_records_multiple_reasons_including_source_sensitive(
    monkeypatch,
):
    # Confirms the source sensitivity flag is added alongside
    # other sensitivity reasons rather than replacing them.
    _patch_rules(monkeypatch)

    df = pd.DataFrame(
        {
            "species_no": [101],
            "record_type": ["roost"],
            "species_unresolved": [False],
            "sensitive": ["Yes"],
        }
    )

    result = classify_chunk(df)

    assert result["sensitivity_reason"].iloc[0] == [
        "sensitive_record_type",
        "sensitive_species",
        "source_sensitive",
    ]