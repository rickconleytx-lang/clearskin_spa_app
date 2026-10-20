BEGIN;

-- PEACH SUITE PRO
-- COACH PEACH ASSIST FINANCIAL FOUNDATION V1
--
-- One business = one shared AI allowance.
-- AI disabled by default.
-- No provider calls or AI activation.
-- All financial values are USD.
-- Monthly accounting uses UTC calendar months.

-- =====================================================
-- 1. AI BUDGETS
-- =====================================================

CREATE TABLE psp_ai_budgets (
    ai_budget_id BIGSERIAL PRIMARY KEY,

    scope VARCHAR(16) NOT NULL
        CHECK (scope IN ('platform', 'business')),

    spa_id INTEGER
        REFERENCES spas(spa_id) ON DELETE RESTRICT,

    ai_enabled BOOLEAN NOT NULL DEFAULT FALSE,

    monthly_limit_usd NUMERIC(18,8),

    warning_threshold_percent INTEGER
        NOT NULL DEFAULT 75,

    created_by INTEGER
        REFERENCES users(user_id) ON DELETE SET NULL,

    updated_by INTEGER
        REFERENCES users(user_id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_ai_budget_scope CHECK (
        (scope = 'platform' AND spa_id IS NULL)
        OR
        (scope = 'business' AND spa_id IS NOT NULL)
    ),

    CONSTRAINT chk_ai_budget_limit CHECK (
        monthly_limit_usd IS NULL
        OR monthly_limit_usd > 0
    ),

    CONSTRAINT chk_ai_budget_enabled CHECK (
        NOT ai_enabled
        OR monthly_limit_usd IS NOT NULL
    ),

    CONSTRAINT chk_ai_budget_warning CHECK (
        warning_threshold_percent BETWEEN 1 AND 99
    ),

    CONSTRAINT chk_ai_budget_timestamps CHECK (
        updated_at >= created_at
    )
);

CREATE UNIQUE INDEX uq_psp_ai_platform_budget
ON psp_ai_budgets (scope)
WHERE scope = 'platform';

CREATE UNIQUE INDEX uq_psp_ai_business_budget
ON psp_ai_budgets (spa_id)
WHERE scope = 'business';


-- =====================================================
-- 2. VERSIONED MODEL PRICING
-- =====================================================

CREATE TABLE psp_ai_model_pricing (
    ai_model_pricing_id BIGSERIAL PRIMARY KEY,

    provider VARCHAR(64) NOT NULL,
    model_name VARCHAR(128) NOT NULL,

    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,

    input_usd_per_million_tokens NUMERIC(18,8)
        NOT NULL CHECK (
            input_usd_per_million_tokens >= 0
        ),

    cached_input_usd_per_million_tokens NUMERIC(18,8)
        CHECK (
            cached_input_usd_per_million_tokens >= 0
        ),

    output_usd_per_million_tokens NUMERIC(18,8)
        NOT NULL CHECK (
            output_usd_per_million_tokens >= 0
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_psp_ai_model_pricing_version
        UNIQUE (provider, model_name, effective_from),

    CONSTRAINT chk_psp_ai_pricing_dates CHECK (
        effective_to IS NULL
        OR effective_to > effective_from
    )
);

-- Initial pricing is for token-billed text models.
-- Other pricing structures require explicit support.
-- No provider prices are seeded automatically.


-- =====================================================
-- 3. AI REQUEST USAGE LEDGER
-- =====================================================

CREATE TABLE psp_ai_usage (
    ai_usage_id BIGSERIAL PRIMARY KEY,

    request_key UUID NOT NULL UNIQUE,

    spa_id INTEGER NOT NULL
        REFERENCES spas(spa_id) ON DELETE RESTRICT,

    business_unit_id INTEGER,

    requested_by_user_id INTEGER
        REFERENCES users(user_id) ON DELETE SET NULL,

    feature_key VARCHAR(64) NOT NULL,

    provider VARCHAR(64),
    model_name VARCHAR(128),

    ai_model_pricing_id BIGINT
        REFERENCES psp_ai_model_pricing(
            ai_model_pricing_id
        ) ON DELETE RESTRICT,

    status VARCHAR(20) NOT NULL DEFAULT 'reserved'
        CHECK (
            status IN (
                'reserved',
                'submitted',
                'completed',
                'failed',
                'uncertain'
            )
        ),

    input_tokens BIGINT NOT NULL DEFAULT 0
        CHECK (input_tokens >= 0),

    cached_input_tokens BIGINT NOT NULL DEFAULT 0
        CHECK (
            cached_input_tokens >= 0
            AND cached_input_tokens <= input_tokens
        ),

    output_tokens BIGINT NOT NULL DEFAULT 0
        CHECK (output_tokens >= 0),

    estimated_cost_usd NUMERIC(18,8)
        NOT NULL DEFAULT 0
        CHECK (estimated_cost_usd >= 0),

    provider_request_id VARCHAR(256),

    error_code VARCHAR(64),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_psp_ai_usage_business_unit
        FOREIGN KEY (spa_id, business_unit_id)
        REFERENCES business_units(
            spa_id, business_unit_id
        ) ON DELETE RESTRICT,

    CONSTRAINT chk_psp_ai_usage_completed CHECK (
        completed_at IS NULL
        OR completed_at >= created_at
    )
);

CREATE INDEX idx_psp_ai_usage_business_month
ON psp_ai_usage (spa_id, created_at DESC);

CREATE INDEX idx_psp_ai_usage_platform_month
ON psp_ai_usage (created_at DESC);

CREATE INDEX idx_psp_ai_usage_business_unit
ON psp_ai_usage (spa_id, business_unit_id);

CREATE INDEX idx_psp_ai_usage_status
ON psp_ai_usage (status);


-- =====================================================
-- 4. AI BUDGET RESERVATIONS
-- =====================================================

CREATE TABLE psp_ai_budget_reservations (
    ai_budget_reservation_id BIGSERIAL PRIMARY KEY,

    ai_usage_id BIGINT NOT NULL UNIQUE
        REFERENCES psp_ai_usage(ai_usage_id)
        ON DELETE RESTRICT,

    billing_month DATE NOT NULL,

    reserved_usd NUMERIC(18,8) NOT NULL
        CHECK (reserved_usd > 0),

    settled_usd NUMERIC(18,8)
        CHECK (
            settled_usd IS NULL
            OR settled_usd >= 0
        ),

    state VARCHAR(20) NOT NULL DEFAULT 'held'
        CHECK (
            state IN (
                'held',
                'settled',
                'released',
                'uncertain'
            )
        ),

    reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    CONSTRAINT chk_psp_ai_reservation_month CHECK (
        EXTRACT(DAY FROM billing_month) = 1
    ),

    CONSTRAINT chk_psp_ai_reservation_dates CHECK (
        resolved_at IS NULL
        OR resolved_at >= reserved_at
    ),

    CONSTRAINT chk_psp_ai_reservation_resolution CHECK (
        (state IN ('settled', 'released'))
        = (resolved_at IS NOT NULL)
    ),

    CONSTRAINT chk_psp_ai_reservation_settlement CHECK (
        (state = 'settled' AND settled_usd IS NOT NULL)
        OR
        (state = 'released' AND settled_usd = 0)
        OR
        (state IN ('held', 'uncertain')
         AND settled_usd IS NULL)
    )
);

CREATE INDEX idx_psp_ai_reservations_month_state
ON psp_ai_budget_reservations (
    billing_month, state
);

CREATE INDEX idx_psp_ai_reservations_reserved_at
ON psp_ai_budget_reservations (
    reserved_at DESC
);

COMMENT ON TABLE psp_ai_budgets IS
'Platform and per-business Coach Peach AI spending limits.';

COMMENT ON TABLE psp_ai_usage IS
'AI usage metadata and estimated costs. No prompts or responses.';

COMMENT ON TABLE psp_ai_budget_reservations IS
'Spending holds and reconciliation for AI requests.';

COMMIT;
