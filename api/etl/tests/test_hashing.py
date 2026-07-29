import pandas as pd

from etl.reconciliation.hashing import (
    row_content_hash,
    add_content_hash,
)


def test_same_record_values_produce_same_hash():
    row_one = pd.Series({
        "scientific_name": "Species A",
        "abundance": 5,
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": True,
        "eastings": 500000,
        "northings": 200000,
    })

    row_two = pd.Series({
        "scientific_name": "Species A",
        "abundance": 5,
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": True,
        "eastings": 500000,
        "northings": 200000,
    })

    assert row_content_hash(row_one) == row_content_hash(row_two)


def test_changed_record_value_produces_different_hash():
    row_one = pd.Series({
        "scientific_name": "Species A",
        "abundance": 5,
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": True,
        "eastings": 500000,
        "northings": 200000,
    })

    row_two = pd.Series({
        "scientific_name": "Species A",
        "abundance": 10,
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": True,
        "eastings": 500000,
        "northings": 200000,
    })

    assert row_content_hash(row_one) != row_content_hash(row_two)


def test_add_content_hash_adds_hash_column():
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "scientific_name": ["Species A", "Species B"],
        "abundance": [5, 10],
        "sex_stage": ["Adult", "Juvenile"],
        "record_type": ["Observation", "Observation"],
        "vitality": ["Alive", "Alive"],
        "verified": [True, True],
        "eastings": [500000, 501000],
        "northings": [200000, 201000],
    })

    result = add_content_hash(df)

    assert "content_hash" in result.columns
    assert len(result["content_hash"]) == 2
    assert result["content_hash"].notna().all()
    assert result["content_hash"].str.len().eq(64).all()