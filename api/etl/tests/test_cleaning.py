# Run via python -m etl.tests.test_cleaning

from pathlib import Path
import pandas as pd
from etl.cleaning import clean_data 

DATA_DIR = Path(
    "/Users/tingtinghe/Documents/brerc-dashboard/data"
)

# Takes in a filename
def test_dataset(filename: str) -> None:
    """
    Load a CSV, clean it, and display its columns.
    """

    print(f"\n===== {filename} =====")

    filepath = DATA_DIR / filename

    df = pd.read_csv(filepath)

    print("Original columns:")
    print(df.columns.tolist())

    cleaned_df = clean_data(df)

    print("Cleaned columns:")
    print(cleaned_df.columns.tolist())

    print("Rows:", len(cleaned_df))

def main() -> None:

    test_dataset("drop_down.csv")
    test_dataset("full_dictionary.csv")
    test_dataset("reptile_sample.csv")
    test_dataset("sensitive_species.csv")
    test_dataset("varied_sample.csv")

# If this file is being run directly:
# __name__ == "__main__"
# Therefore, main() runs.

# If another file is being run and imports this file:
# this file's __name__ is its module name, not "__main__".
# Therefore, main() does not run.
if __name__ == "__main__":
    main()