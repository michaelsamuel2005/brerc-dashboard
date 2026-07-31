FOR b4

"""
Ensure it matches the expected species: DATABASE| SOURCE(CVS column names)
- species_id - species_no
- scientific_name - scientific_name
- common_name - common_name 
- species_group - Represented by TAXANB in the dictionary
- record_count
- first_year
- last_year
- has_image
"""

"""
    B4: species x cell x year aggregation, species index, D5
    low-count suppression.

    filter_accepted_records / build_species_index are used
    as-is from their own modules.

    Current BRERC rules:
      - Aggregation happens on 1km grid cells.
      - Only accepted + legacy records contribute.
      - Exact counts of 1 are suppressed.
      - Derived aggregation layer is recomputed fully each run.
"""

"""
D5:
Groups with only one record have their exact count hidden.

The row is kept so the dashboard can show that a species
exists in that grid cell, without revealing an exact single
observation.
"""

ACCEPTED_VERIFIED_VALUES = {
    "Accepted \u2013 correct",
    "Accepted \u2013 considered correct",
    "Accepted",  # deprecated older grouping, still seen in legacy data
}
