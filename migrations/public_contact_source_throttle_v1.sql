BEGIN;

CREATE TABLE IF NOT EXISTS public_contact_source_requests (
    public_contact_source_request_id SERIAL PRIMARY KEY,

    source_hash CHAR(64) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT public_contact_source_requests_hash_check
        CHECK (
            source_hash ~ '^[0-9a-f]{64}$'
        )
);

CREATE INDEX IF NOT EXISTS
    idx_public_contact_source_requests_source_created
ON public_contact_source_requests (
    source_hash,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS
    idx_public_contact_source_requests_created
ON public_contact_source_requests (
    created_at
);

COMMENT ON TABLE public_contact_source_requests IS
    'Privacy-preserving source-rate records for public '
    'Contact Us abuse protection. Stores only an '
    'HMAC-SHA256 source fingerprint, never a raw IP address.';

COMMENT ON COLUMN
    public_contact_source_requests.source_hash IS
    'HMAC-SHA256 fingerprint of the validated request source.';

COMMIT;
