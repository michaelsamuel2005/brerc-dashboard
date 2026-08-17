"""Offline curation of species media: fetch, licence-vet, then hand to a human.

The pipeline this package feeds (see app/species_assets.py for the serving end):

    python -m curation ...  ->  candidates file ("approved": false)
                            ->  HUMAN REVIEW fills approvalReference, edits alt,
                                confirms each licence at its sourceUrl
                            ->  approved file ("approved": true)
                            ->  SPECIES_ASSETS_FILE=... and the API serves it

Nothing in the serving path calls a third party; this package is the only place
outbound species-media requests happen, and it is run by an operator, not by
web traffic.
"""
