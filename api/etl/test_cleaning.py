import pandas as pd

from cleaning import clean_data

    data = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv")

cleaned_data = clean_data(data)