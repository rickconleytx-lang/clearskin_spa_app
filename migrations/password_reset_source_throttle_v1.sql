BEGIN;

CREATE TABLE IF NOT EXISTS password_reset_source_requests (
    password_reset_source_request_id SERIAL PRIMARY KEY,

    source_hash CHAR(64) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT password_reset_source_requests_hash_check
        CHECK (
            source_hash ~ '^[0-9a-f]{64}$'
        )
);

CREATE INDEX IF NOT EXISTS
    idx_password_reset_source_requests_source_created
ON password_reset_source_requests (
    source_hash,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_password_reset_source_requests_created
ON password_reset_source_requests (
    created_at
);

COMMENT ON TABLE password_reset_source_requests IS
    'Privacy-preserving source-rate records for public '
    'Forgot Password abuse protection. Stores only an '
    'HMAC-SHA256 source fingerprint, never a raw IP address.';

COMMENT ON COLUMN
    password_reset_source_requests.source_hash IS
    'HMAC-SHA256 fingerprint of the validated request source.';

COMMIT;
