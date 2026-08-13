The species reconciliation module is responsible for bridging raw occurrence records with the official master species dictionary. It standardises names, matches identifiers, validates format integrity, and enforces a strict fail-closed policy for ambiguous or malformed data to protect sensitive species records.

Key Responsibilities
- Name Normalisation: Cleans and standardises scientific names by stripping whitespace, converting text to lowercase, and collapsing irregular spacing.

- Dictionary Matching: Merges occurrence records with the species dictionary using unique scientific keys, pulling in critical metadata like common names and taxonomies.

- Collision Detection: Scans the dictionary for duplicate scientific keys and logs explicit warnings if naming conflicts occur.

- Format & Structure Validation: Ensures resolved species numbers conform to expected patterns (either plain numeric IDs or masked BRERC-prefixed sensitive IDs).

- Fail-Closed Flagging: Automatically flags missing, ambiguous, or malformed species numbers as unresolved so they follow safe blurred pathways.

- Coverage Reporting: Calculates and outputs a match coverage percentage to audit resolution health per run.