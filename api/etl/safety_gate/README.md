FOR B2:

Classification:
    Classify records for sensitivity using vectorised operations.

    Records are classified as sensitive if they:
    - belong to a sensitive species,
    - have a sensitive record type, or
    - contain an unresolved species.

    Fixed sites (e.g. roosts, holts, nests) are currently blurred year-round.

    Seasonal exceptions can be added in future if required by the data provider

ADD SANITY CHECKS MAYBE

Generalisation:
    Generalise record locations using a configurable spatial resolution.

    Coordinates are snapped to a resolution grid in PostGIS before being
    converted to public longitude/latitude values.

    The D0 minimum precision rule is enforced so that no location can be
    returned more precisely than the configured safety floor.

    Records with missing coordinates are retained for record counts but
    returned with null spatial outputs.

PUBLIC_OUTPUT:
    Final safety boundary before data reaches the public API.

    This module:
    - only exposes approved public columns
    - removes internal safety classification fields
    - ensures precise coordinates never leave the pipeline
    - removes records without safe coordinates

    Expected pipeline order:
        cleaning
        -> species matching
        -> safety classification
        -> location generalisation
        -> locality generation
        -> public output