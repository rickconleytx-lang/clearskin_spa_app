-- PEACH SUITE PRO
-- CORPORATE MARKETING WEBSITE CMS FOUNDATION V1
--
-- Separate from customer PeachWeb configuration.
-- Does not change public website content.
-- Does not change Stripe pricing or subscriptions.
-- Drafts and published revisions are stored separately.

BEGIN;

CREATE TABLE IF NOT EXISTS psp_marketing_pages (
    page_key VARCHAR(80) PRIMARY KEY,
    display_name VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS psp_marketing_revisions (
    revision_id BIGSERIAL PRIMARY KEY,

    page_key VARCHAR(80) NOT NULL
        REFERENCES psp_marketing_pages(page_key)
        ON DELETE RESTRICT,

    revision_number INTEGER NOT NULL
        CHECK (revision_number > 0),

    content JSONB NOT NULL
        CHECK (jsonb_typeof(content) = 'object'),

    created_by INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    change_note TEXT,

    CONSTRAINT uq_psp_marketing_revision_number
        UNIQUE (page_key, revision_number),

    CONSTRAINT uq_psp_marketing_revision_page_id
        UNIQUE (page_key, revision_id)
);

CREATE INDEX IF NOT EXISTS
    idx_psp_marketing_revisions_history
ON psp_marketing_revisions (
    page_key,
    revision_number DESC
);

CREATE TABLE IF NOT EXISTS psp_marketing_page_state (
    page_key VARCHAR(80) PRIMARY KEY
        REFERENCES psp_marketing_pages(page_key)
        ON DELETE RESTRICT,

    draft_revision_id BIGINT,
    published_revision_id BIGINT,

    published_at TIMESTAMPTZ,

    published_by INTEGER
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_psp_marketing_draft_revision
        FOREIGN KEY (page_key, draft_revision_id)
        REFERENCES psp_marketing_revisions(
            page_key, revision_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_psp_marketing_published_revision
        FOREIGN KEY (page_key, published_revision_id)
        REFERENCES psp_marketing_revisions(
            page_key, revision_id
        )
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS psp_marketing_publication_events (
    publication_event_id BIGSERIAL PRIMARY KEY,

    page_key VARCHAR(80) NOT NULL
        REFERENCES psp_marketing_pages(page_key)
        ON DELETE RESTRICT,

    revision_id BIGINT NOT NULL,
    previous_revision_id BIGINT,

    action VARCHAR(20) NOT NULL
        CHECK (action IN ('publish', 'restore')),

    performed_by INTEGER NOT NULL
        REFERENCES users(user_id)
        ON DELETE RESTRICT,

    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_psp_marketing_event_revision
        FOREIGN KEY (page_key, revision_id)
        REFERENCES psp_marketing_revisions(
            page_key, revision_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_psp_marketing_previous_revision
        FOREIGN KEY (page_key, previous_revision_id)
        REFERENCES psp_marketing_revisions(
            page_key, revision_id
        )
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS
    idx_psp_marketing_publication_history
ON psp_marketing_publication_events (
    page_key,
    performed_at DESC,
    publication_event_id DESC
);

-- Register pages without publishing or altering content.

INSERT INTO psp_marketing_pages (
    page_key,
    display_name
)
VALUES
    ('home', 'Home Page'),
    ('packages', 'Subscription Packages'),
    ('pricing', 'Pricing')
ON CONFLICT (page_key) DO NOTHING;

INSERT INTO psp_marketing_page_state (
    page_key
)
SELECT page_key
FROM psp_marketing_pages
ON CONFLICT (page_key) DO NOTHING;

COMMIT;
