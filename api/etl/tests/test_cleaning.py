# Run via python -m etl.tests.test_cleaning

import pandas as pd
from etl.cleaning import clean_data,calculate_dictionary_match

print("========== dropdown.csv ==========")

drop_down = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/drop_down.csv")
cleaned_drop_down = clean_data(drop_down)

print("========== dictionary.csv ==========")

full_dictionary = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/full_dictionary.csv")
cleaned_dictionary = clean_data(full_dictionary)

print("========== reptile.csv ==========")

repile_sample = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/reptile_sample.csv")
cleaned_reptile = clean_data(repile_sample)

print("========== sensitive.csv ==========")

sensitive_species = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/sensitive_species.csv")
cleaned_sensitive = clean_data(sensitive_species)

print("========== varied.csv ==========")

varied_sample = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv")
cleaned_varied = clean_data(varied_sample)

calculate_dictionary_match(
    cleaned_reptile,
    cleaned_dictionary
)

