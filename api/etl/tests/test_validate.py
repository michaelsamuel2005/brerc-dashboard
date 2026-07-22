from pathlib import Path
import pandas as pd
from etl.validation import validate_unique_no, validate_species_name, validate_avon_flag, validate_record_type, calculate_dictionary_match, get_sensitive_record_types
from etl.cleaning import clean_data 

DATA_DIR = Path(
    "/Users/tingtinghe/Documents/brerc-dashboard/data"
)

# df = pd.read_csv(
#     DATA_DIR / "reptile_sample.csv"
# )

df = pd.read_csv(
    DATA_DIR / "drop_down.csv"
)

# df = pd.read_csv(
#     DATA_DIR / "sensitive_species.csv"
# )

# Clean the column names then 
cleaned_df = clean_data(df)

# validate_unique_no(cleaned_df)
# validate_species_name(cleaned_df)
# validate_avon_flag(cleaned_df)
# validate_record_type(cleaned_df)
get_sensitive_record_types(cleaned_df)

def main() -> None:

    print("===== TEST: DICTIONARY MATCH =====")

    records_df = pd.read_csv(
        DATA_DIR / "reptile_sample.csv"
    )

    dictionary_df = pd.read_csv(
        DATA_DIR / "full_dictionary.csv"
    )

    cleaned_records = clean_data(
        records_df
    )

    cleaned_dictionary = clean_data(
        dictionary_df
    )

    calculate_dictionary_match(
        cleaned_records,
        cleaned_dictionary
    )

if __name__ == "__main__":
    main()