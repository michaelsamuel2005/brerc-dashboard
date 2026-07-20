from cleaning import clean_data
from filtering import filter_sensitive_species


def run_pipeline(df):

    # Remove sensitive species
    df = filter_sensitive_species(df)

    # Clean the data
    df = clean_data(df)

    return df