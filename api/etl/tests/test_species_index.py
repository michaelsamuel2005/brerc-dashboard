import pandas as pd

from etl.aggregation.species_index import build_species_index


def test_build_species_index():
    df = pd.DataFrame({
        "unique_no": [1, 2, 3],
        "species_no": [100, 100, 200],
        "scientific_name": [
            "Erithacus rubecula",
            "Erithacus rubecula",
            "Bufo bufo",
        ],
        "common_name": [
            "Robin",
            "Robin",
            "Common Toad",
        ],
        "taxanb": [
            "bird",
            "bird",
            "amphibian",
        ],
        "record_date": [
            "16/11/2012",
            "20/05/2015",
            "01/03/2010",
        ],
    })

    result = build_species_index(df)

    print(result)

    assert list(result.columns) == [
        "species_id",
        "scientific_name",
        "common_name",
        "species_group",
        "record_count",
        "first_year",
        "last_year",
        "has_image",
    ]

    assert len(result) == 2

    robin = result[result["species_id"] == 100].iloc[0]

    assert robin["species_group"] == "bird"
    assert robin["record_count"] == 2
    assert robin["first_year"] == 2012
    assert robin["last_year"] == 2015