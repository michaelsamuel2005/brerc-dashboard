The data profiling and validation module inspects, cleans, and diagnoses raw incoming source datasets before they hit the core ETL safety gates and aggregation steps. It standardises column headers, flags sensitive observations, and runs deep health checks on identifiers and scientific names.

Key Responsibilities
- Header Standardisation: Cleans raw input columns by stripping whitespace, lowercasing text, and formatting spaces into underscores.

- Sensitivity Classification: Cross-references records against protected species lists, NBN numbers, specific record types, and fail-closed rules to accurately identify sensitive rows.

- Identifier & Uniqueness Audits: Profiles primary tracking numbers (unique_no) for missing values, duplicates, and uniqueness health.

- Name Format Verification: Validates scientific name structures using regex patterns (Genus species) and tracks missing entries.

- Dictionary Matching & Coverage: Compares source species against the master species dictionary to output match rates and spot unmatched anomalies.

- Regional & Categorical Profiling: Inspects regional flags (outofavon), verification statuses, and record types to ensure data consistency.

File-by-File Breakdown
1. cleaning.py (Column Standardisation)
- Strips whitespace, converts strings to lowercase, and replaces spaces with underscores across all raw headers.

2. classify.py (Sensitive Species Detection)
- Evaluates records against master sensitive lists, record type rules, and fail-closed unresolved species markers, appending an is_sensitive boolean flag.

3. validation.py (Validation & Profiling Utilities (Diagnostic Scripts))
- Provides command-line / logging diagnostics for unique numbers, scientific name formats, outofavon regional flags, dictionary match rates, and verified record types.