-- =============================================================================
-- END-TO-END TEST — STEP 4: invented records in BRERC's source view
-- =============================================================================
-- Every row is made up. Names are real species (they have to be, so the species
-- dictionary can resolve them), but the sightings, coordinates, recorders,
-- places and comments are all fiction.
--
-- Each row is here to prove ONE thing. If a row disappears or changes meaning,
-- something in the safety chain has broken. The "proves" note on each says what.
--
-- Coordinates are British National Grid (EPSG:27700), around Bristol.
-- =============================================================================

DELETE FROM brerc_source.occurrences;
DELETE FROM brerc_source.species_dictionary;


-- -----------------------------------------------------------------------------
-- The dictionary
-- -----------------------------------------------------------------------------
-- Columns are BRERC's real ones. OUTOFAVON is inverted: 'No' = we DO hold
-- records; 'Yes' = we do NOT.
INSERT INTO brerc_source.species_dictionary
    (species_no, authority, scientific, common_nam, family, brercstatu,
     taxanb, nbn_number, verifycode, outofavon, sensitive, verifycod2) VALUES
    -- Ordinary species, present in the NHM/NBN dictionary.
    ('6973', '(Linnaeus, 1758)', 'Erithacus rubecula', 'Robin', 'Muscicapidae',
     'Active', 'T6973', 'NBNSYS0000000001', 'A', 'No', 'No', 'A'),
    ('7101', '(Linnaeus, 1758)', 'Bufo bufo', 'Common Toad', 'Bufonidae',
     'Active', 'T7101', 'NBNSYS0000000002', 'A', 'No', 'No', 'A'),
    -- Sensitive species. Otter and badger are the textbook cases.
    ('8319', '(Linnaeus, 1758)', 'Lutra lutra', 'Otter', 'Mustelidae',
     'Active', 'T8319', 'NBNSYS0000000003', 'A', 'No', 'Yes', 'A'),
    ('8412', '(Linnaeus, 1758)', 'Meles meles', 'Badger', 'Mustelidae',
     'Active', 'T8412', 'NBNSYS0000000004', 'A', 'No', 'Yes', 'A'),
    -- BRERC-created entry: no NBN number, BRERC-prefixed id (their email).
    ('BRERC0001', '(Linnaeus, 1758)', 'Apus apus', 'Swift', 'Apodidae',
     'BRERC', 'TB0001', NULL, 'A', 'No', 'No', 'A'),
    -- In the dictionary but we hold no records: OUTOFAVON = 'Yes' means
    -- NO records. It must never appear in the public species list.
    ('9999', '(Linnaeus, 1758)', 'Alcedo atthis', 'Kingfisher', 'Alcedinidae',
     'Active', 'T9999', 'NBNSYS0000000005', 'A', 'Yes', 'No', 'A');


-- -----------------------------------------------------------------------------
-- The occurrence records
-- -----------------------------------------------------------------------------
INSERT INTO brerc_source.occurrences
    (unique_no, species_no, scientific_name, nbn_number, record_type, sensitive,
     verified, vitality, abundance, sex_stage, eastings, northings, date_of_record,
     date_mdb_modified, recorder1, place, comments) VALUES

    -- 1. Ordinary record, not sensitive.
    --    PROVES: normal records survive, and recorder/place/comments are dropped.
    ('R001', '6973', 'Erithacus rubecula', 'NBNSYS0000000001', 'field record', 'No',
     'Accepted', 'alive', '1', 'adult', 358720, 172480, DATE '2024-05-14',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'Jane Fieldworker', 'Ashton Court, by the third oak', 'Nest in hedge at rear of cottage'),

    -- 2. Ordinary record, second species.
    --    PROVES: more than one species flows through.
    ('R002', '7101', 'Bufo bufo', 'NBNSYS0000000002', 'field record', 'No',
     'Accepted', 'alive', '15', 'unknown', 360740, 174880, DATE '2024-03-02',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'A Recorder', 'Pond behind Manor Farm', 'Spawn observed in garden pond'),

    -- 3. SENSITIVE SPECIES (otter), flagged by the view's own Sensitive column.
    --    PROVES: blurring to 1 km, and that place/comments are suppressed.
    ('R003', '8319', 'Lutra lutra', 'NBNSYS0000000003', 'field record', 'Yes',
     'Accepted', 'alive', '1', 'adult', 356123, 171456, DATE '2025-06-20',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'S Watcher', 'River Avon, below the weir at Sea Mills', 'Holt entrance under bank, 20m upstream of footbridge'),

    -- 4. SENSITIVE BY RECORD TYPE (badger sett) — the feature-based sensitivity
    --    BRERC described as "not a species but relates to their home".
    --    PROVES: record_type alone triggers blurring, even where sensitive='No'.
    ('R004', '8412', 'Meles meles', 'NBNSYS0000000004', 'sett', 'No',
     'Accepted', NULL, NULL, NULL, 359001, 173002, DATE '2025-04-11',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'B Surveyor', 'Leigh Woods, main sett', 'Six-entrance sett on the north bank'),

    -- 5. BRERC-created species: no NBN number, BRERC-prefixed id.
    --    PROVES: species with no NBN number still resolve and are not lost.
    ('R005', 'BRERC0001', 'Apus apus', NULL, 'field record', 'No',
     'Accepted', 'alive', '6', 'adult', 358100, 172900, DATE '2024-07-03',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'C Observer', 'Clifton, roof of number 12', 'Screaming party overhead'),

    -- 6. Non-numeric record id, and an unverified record.
    --    PROVES: record_id being TEXT is genuinely needed, and that
    --    verification status is carried through rather than assumed.
    ('R006/A', '6973', 'Erithacus rubecula', 'NBNSYS0000000001', 'field record', 'No',
     'Unverified', 'alive', '1', 'male', 357400, 171100, DATE '2023-11-30',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'D Volunteer', 'Bedminster allotments', 'Singing from fence post'),

    -- 7. Species not in the dictionary at all.
    --    PROVES: fail-closed. An unresolvable species must be treated as
    --    sensitive and blurred, never published at full precision.
    ('R007', '404404', 'Ignotus incognitus', NULL, 'field record', 'No',
     'Accepted', NULL, NULL, NULL, 361000, 175000, DATE '2025-01-15',
     TIMESTAMPTZ '2026-08-01 09:00:00+01',
     'E Unknown', 'Somewhere precise', 'Should never be shown at fine resolution');
