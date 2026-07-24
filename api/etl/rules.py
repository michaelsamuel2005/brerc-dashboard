import pandas as pd

from etl.cleaning import clean_data

sensitive_species_df = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/sensitive_species.csv")
sensitive_species_df_clean = clean_data(sensitive_species_df)

SENSITIVE_SPECIES_NOS = set(
    sensitive_species_df_clean["species_no"].dropna()
)

SENSITIVE_NBN_NUMBERS = set(
    sensitive_species_df_clean["nbn_number"].dropna()
)

FLAGGED_RECORD_TYPES = frozenset({
    "trapped at actinic light",
    "trapped at light",
    "trapped at mercury vapour light",
    "night roost",
    "tagged night roost",
    "plant count",
    "maternity roost",
    "flower count",
    "photographed",
    "summer roost",
    "hibernation",
    "daylight site visit",
    "day roost",
    "rosette count",
    # for bat roost and plant
    "field record"
    "field record (bat roost sensitive record)",
    "field record (plant sensitive record)",
    "bat detector",
    "box survey",
    "hibernation roost",
    "earth",
    "droppings",
    "handled",
    "burrow",
    "pre-parturition roost",
    "netted",
    "box survey",
    "breeding",
    "roost",
    "emergence count",
    "tagged day roost ",
    "grounded",
    "possibly breeding",
    "nest",
    "field record",
    "holt",
    "bedding",
    "bat roost",
    "lie-up",
    "DNA or eDNA testing",
    "AI or programme analysis",
    "Beaver Lodge",
    "Acoustic audio recording",
    "Acoustic audio record",
    "found dead",
    "found dead",
    "dam",
    "gnawed timber"
})
