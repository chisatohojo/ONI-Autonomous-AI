-- Schema 1. SQL NULL with status UNKNOWN means absent evidence, never zero/none.
PRAGMA application_id = 1330530625;
PRAGMA user_version = 1;

CREATE TABLE source (
    source_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('UPSTREAM_CODE', 'UPSTREAM_DOC', 'OFFICIAL', 'RUNTIME')),
    url TEXT NOT NULL CHECK (url LIKE 'https://%'),
    revision TEXT NOT NULL,
    accessed_on TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    note TEXT NOT NULL
) STRICT;

CREATE TABLE building_variant (
    variant_id TEXT PRIMARY KEY,
    building_id TEXT NOT NULL,
    game_version TEXT NOT NULL DEFAULT 'UNKNOWN',
    dlc_scope TEXT NOT NULL DEFAULT 'UNKNOWN',
    identity_status TEXT NOT NULL CHECK (identity_status IN ('SOURCE_REVIEWED', 'GAME_VERIFIED')),
    identity_source_id TEXT NOT NULL REFERENCES source(source_id),
    identity_locator TEXT NOT NULL,
    UNIQUE (building_id, game_version, dlc_scope)
) STRICT;

CREATE TABLE fact (
    variant_id TEXT NOT NULL REFERENCES building_variant(variant_id),
    field TEXT NOT NULL CHECK (field IN (
        'name', 'purpose', 'construction_materials', 'power_consumption_w', 'power_generation_w',
        'inputs', 'outputs', 'temperature_constraints', 'environment_constraints', 'research'
    )),
    value_json TEXT CHECK (value_json IS NULL OR json_valid(value_json)),
    unit TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'UNKNOWN', 'SOURCE_REVIEWED', 'GAME_VERIFIED', 'CONFLICTED'
    )),
    source_id TEXT REFERENCES source(source_id),
    locator TEXT,
    note TEXT NOT NULL,
    PRIMARY KEY (variant_id, field),
    CHECK (
        (status = 'UNKNOWN' AND value_json IS NULL AND unit IS NULL)
        OR (status <> 'UNKNOWN' AND value_json IS NOT NULL AND source_id IS NOT NULL
            AND locator IS NOT NULL AND length(locator) > 0)
    ),
    CHECK (value_json IS NULL OR CASE
        WHEN field IN ('name', 'purpose') THEN json_type(value_json) = 'text'
        WHEN field IN ('power_consumption_w', 'power_generation_w') THEN
            json_type(value_json) IN ('integer', 'real')
            AND json_extract(value_json, '$') >= 0 AND unit = 'W' AND unit IS NOT NULL
        ELSE json_type(value_json) = 'array' AND unit IS NULL
    END)
) STRICT;

CREATE INDEX building_id_index ON building_variant(building_id);
CREATE INDEX fact_field_index ON fact(field, status);
