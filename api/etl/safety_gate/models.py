from dataclasses import dataclass 
from typing import Optional

# Result of matching species to species dictionary
# Result is stored in object SpeciesMatch
@dataclass(frozen=True)
class SpeciesMatch:
    species_no: int 
    nbn_number: Optional[str]

# Represents safety classification
# Will tell us what should happen to the species before frontend
# If its sensitive
# If the locatio should be generalised or blurred
# Resolution used 
# Reason for result 
@dataclass(frozen=True)
class Classification:
    is_sensitive: bool
    blurred: bool
    resolution_m: Optional[int]
    reason: str