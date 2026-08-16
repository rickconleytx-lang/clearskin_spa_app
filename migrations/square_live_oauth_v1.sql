BEGIN;


-- ==========================================================
-- PEACH SUITE PRO
-- SQUARE LIVE OAUTH V1
--
-- Additive only.
--
-- Connecting a production Square account does NOT
-- automatically enable live outbound synchronization.
-- ==========================================================


ALTER TABLE square_connections
    ADD COLUMN IF NOT EXISTS
        live_sync_enabled BOOLEAN NOT NULL DEFAULT FALSE;


ALTER TABLE square_connections
    ADD COLUMN IF NOT EXISTS
        oauth_token_refreshed_at TIMESTAMPTZ;


ALTER TABLE square_connections
    ADD COLUMN IF NOT EXISTS
        oauth_token_last_verified_at TIMESTAMPTZ;


-- live_sync_enabled is meaningful only for production.
-- Sandbox continues to use its existing explicit sandbox
-- controls and does not use this production enablement flag.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'chk_square_connections_live_sync_environment'
          AND conrelid =
            'square_connections'::regclass
    ) THEN
        ALTER TABLE square_connections
            ADD CONSTRAINT
                chk_square_connections_live_sync_environment
            CHECK (
                live_sync_enabled = FALSE
                OR environment = 'production'
            );
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_square_connections_live_enabled
ON square_connections (
    spa_id,
    business_unit_id,
    connection_status
)
WHERE
    environment = 'production'
    AND live_sync_enabled = TRUE;


COMMENT ON COLUMN
    square_connections.live_sync_enabled
IS
    'Explicit workspace-level safety switch for production '
    'Square outbound synchronization. OAuth connection alone '
    'must never enable live writes.';


COMMENT ON COLUMN
    square_connections.oauth_token_refreshed_at
IS
    'Timestamp when the stored production Square OAuth token '
    'pair was last successfully refreshed.';


COMMENT ON COLUMN
    square_connections.oauth_token_last_verified_at
IS
    'Timestamp when the stored production Square OAuth access '
    'token was last successfully verified against Square.';


COMMIT;
