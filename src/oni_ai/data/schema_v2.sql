-- Additive migration. Existing source/building_variant/fact rows stay unchanged.
CREATE TABLE source_review (
    source_id TEXT PRIMARY KEY REFERENCES source(source_id),
    target_version TEXT NOT NULL,
    locator TEXT NOT NULL,
    redistribution TEXT NOT NULL CHECK (redistribution IN (
        'UNKNOWN', 'REFERENCE_ONLY', 'LICENSED'
    )),
    rights_note TEXT NOT NULL,
    hash_scope TEXT NOT NULL
) STRICT;

CREATE TABLE game_rule (
    rule_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain IN ('oxygen', 'food', 'power', 'water', 'research')),
    game_version TEXT NOT NULL,
    dlc_scope TEXT NOT NULL,
    statement TEXT NOT NULL,
    parameters_json TEXT NOT NULL CHECK (json_valid(parameters_json)),
    status TEXT NOT NULL CHECK (status IN ('SOURCE_REVIEWED', 'GAME_VERIFIED', 'CONFLICTED')),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    locator TEXT NOT NULL
) STRICT;

CREATE TABLE catalog_import (
    catalog_id TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL
) STRICT;

CREATE TABLE resource_identifier (
    material_id TEXT PRIMARY KEY
) STRICT;

CREATE TABLE rule_binding (
    variant_id TEXT NOT NULL REFERENCES building_variant(variant_id),
    rule_id TEXT NOT NULL REFERENCES game_rule(rule_id),
    PRIMARY KEY (variant_id, rule_id)
) STRICT;

INSERT INTO source_review
SELECT source_id, 'UNKNOWN', 'Phase 0 source; see each fact locator', 'REFERENCE_ONLY',
       'Original text/code redistribution not granted by this record; references and labels only.',
       'UTF-8 source text, LF (Phase 0 evidence index)'
FROM source;

PRAGMA user_version = 2;
