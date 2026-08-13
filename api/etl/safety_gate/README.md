The safety rules module serves as the central configuration gateway for the entire safety pipeline. It bridges organization-specific YAML settings (config/safety_rules.yaml) with the safety gate modules, supplying spatial generalisation floors, restricted record types, and cached sensitive species lists.

Key Responsibilities
- Spatial Generalisation Constants: Exposes core blur rules, including the mandatory 100m minimum safety floor (D0_FLOOR_M), default sensitive blur distances, and custom species-specific resolutions.

- Restricted Record Types (FLAGGED_RECORD_TYPES): Compiles an immutable frozen set of sensitive record types that automatically trigger privacy shielding.

- Sensitive Species Caching (load_sensitive_species): Reads, cleans, and caches protected species numbers and NBN numbers from disk using @lru_cache(maxsize=1) for high performance across pipeline runs.

- Graceful File Fallbacks: Automatically attempts to load primary sensitive lists, falls back to .example configuration files if missing, or safely returns empty sets to prevent pipeline crashes during local development and testing.

How It Works
1. YAML Loading:
- Upon import, the module loads global configuration parameters via the core loader to establish spatial thresholds and file paths.

2. On-Demand Caching (@lru_cache):
- When the safety gate requests sensitive species lists, load_sensitive_species() processes the CSV file once, standardises the headers through the cleaning utility, and caches the resulting sets of species IDs and NBN numbers in memory.

3. Fail-Safe Operation:
- If configuration or CSV files cannot be found on disk, the module logs/falls back safely to prevent hard exceptions, ensuring that test suites and offline runs complete smoothly.