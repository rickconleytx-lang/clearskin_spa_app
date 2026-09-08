-- =========================================================
-- PEACH SUITE PRO
-- SUPPORT CENTER FOUNDATION V1
--
-- Purpose:
--   Extend the existing PSP-global Help system into the shared
--   content foundation for:
--
--       - In-App Help
--       - support.peachsuitepro.com
--
-- Existing help_pages rows remain the language-specific article
-- content. This migration adds shared topic metadata, translatable
-- categories, public article metadata, and related-topic support.
--
-- This migration DOES NOT:
--   - publish any Help article to the public Support Center
--   - alter existing Help article content
--   - change existing in-app Help routes
--   - create public Support Center routes
--   - create or send support requests
-- =========================================================

BEGIN;


-- =========================================================
-- SUPPORT CATEGORIES
--
-- Categories are PSP-global. Their visible names and descriptions
-- are translated separately so navigation can remain on the same
-- category while switching languages.
-- =========================================================

CREATE TABLE IF NOT EXISTS help_categories (

    help_category_id BIGSERIAL PRIMARY KEY,

    category_key VARCHAR(80) NOT NULL,

    display_order INTEGER NOT NULL DEFAULT 0,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_help_categories_category_key
        UNIQUE (category_key)
);


CREATE TABLE IF NOT EXISTS help_category_translations (

    help_category_translation_id BIGSERIAL PRIMARY KEY,

    help_category_id BIGINT NOT NULL,

    language_code VARCHAR(10) NOT NULL,

    display_name VARCHAR(160) NOT NULL,

    description TEXT,

    public_slug VARCHAR(180),

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_help_category_translations_category
        FOREIGN KEY (help_category_id)
        REFERENCES help_categories(help_category_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_help_category_translation_language
        UNIQUE (
            help_category_id,
            language_code
        )
);


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_help_category_translation_public_slug
ON help_category_translations (
    UPPER(language_code),
    LOWER(public_slug)
)
WHERE
    public_slug IS NOT NULL
    AND BTRIM(public_slug) <> '';


-- =========================================================
-- HELP TOPICS
--
-- One record represents one stable Help topic / page_key.
--
-- Properties shared by every translation belong here so English
-- and Spanish cannot accidentally have different categories,
-- publication state, visibility, article type, or tutorial video.
-- =========================================================

CREATE TABLE IF NOT EXISTS help_topics (

    help_topic_id BIGSERIAL PRIMARY KEY,

    page_key TEXT NOT NULL,

    help_category_id BIGINT,

    content_type VARCHAR(30)
        NOT NULL DEFAULT 'guide',

    show_in_app BOOLEAN
        NOT NULL DEFAULT TRUE,

    show_on_web BOOLEAN
        NOT NULL DEFAULT TRUE,

    publication_status VARCHAR(20)
        NOT NULL DEFAULT 'draft',

    display_order INTEGER,

    is_featured BOOLEAN
        NOT NULL DEFAULT FALSE,

    is_popular BOOLEAN
        NOT NULL DEFAULT FALSE,

    tutorial_video_url TEXT,

    published_at TIMESTAMPTZ,

    archived_at TIMESTAMPTZ,

    created_by INTEGER,

    updated_by INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_help_topics_page_key
        UNIQUE (page_key),

    CONSTRAINT chk_help_topics_content_type
        CHECK (
            content_type IN (
                'guide',
                'how_to',
                'faq',
                'troubleshooting'
            )
        ),

    CONSTRAINT chk_help_topics_publication_status
        CHECK (
            publication_status IN (
                'draft',
                'published',
                'archived'
            )
        ),

    CONSTRAINT fk_help_topics_category
        FOREIGN KEY (help_category_id)
        REFERENCES help_categories(help_category_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_help_topics_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_help_topics_updated_by
        FOREIGN KEY (updated_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL
);


CREATE INDEX IF NOT EXISTS
    idx_help_topics_web_directory
ON help_topics (
    help_category_id,
    display_order,
    page_key
)
WHERE
    show_on_web = TRUE
    AND publication_status = 'published';


CREATE INDEX IF NOT EXISTS
    idx_help_topics_in_app_directory
ON help_topics (
    help_category_id,
    display_order,
    page_key
)
WHERE
    show_in_app = TRUE;


-- =========================================================
-- RELATED HELP TOPICS
--
-- Allows Master Admin to create intentional "Related Topics"
-- navigation without embedding article relationships in HTML.
-- =========================================================

CREATE TABLE IF NOT EXISTS help_topic_relations (

    help_topic_relation_id BIGSERIAL PRIMARY KEY,

    help_topic_id BIGINT NOT NULL,

    related_help_topic_id BIGINT NOT NULL,

    display_order INTEGER
        NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_help_topic_relations_topic
        FOREIGN KEY (help_topic_id)
        REFERENCES help_topics(help_topic_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_help_topic_relations_related_topic
        FOREIGN KEY (related_help_topic_id)
        REFERENCES help_topics(help_topic_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_help_topic_relation
        UNIQUE (
            help_topic_id,
            related_help_topic_id
        ),

    CONSTRAINT chk_help_topic_relation_not_self
        CHECK (
            help_topic_id <> related_help_topic_id
        )
);


-- =========================================================
-- LANGUAGE-SPECIFIC ARTICLE METADATA
--
-- Existing help_pages remains the canonical translated article
-- content table.
--
-- These fields may legitimately differ between EN / ES versions.
-- =========================================================

ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS summary TEXT;


ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS search_keywords TEXT;


ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS public_slug VARCHAR(180);


ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS seo_description VARCHAR(320);


ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS translation_status VARCHAR(20)
        NOT NULL DEFAULT 'complete';


ALTER TABLE help_pages
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW();


CREATE UNIQUE INDEX IF NOT EXISTS
    uq_help_pages_global_language_public_slug
ON help_pages (
    UPPER(language_code),
    LOWER(public_slug)
)
WHERE
    spa_id IS NULL
    AND public_slug IS NOT NULL
    AND BTRIM(public_slug) <> '';


DO $$
BEGIN

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_help_pages_translation_status'
    ) THEN

        ALTER TABLE help_pages
        ADD CONSTRAINT chk_help_pages_translation_status
        CHECK (
            translation_status IN (
                'draft',
                'review',
                'complete'
            )
        );

    END IF;

END
$$;


COMMENT ON COLUMN help_pages.public_slug
IS
    'Language-specific public Support Center article slug.';


COMMENT ON COLUMN help_pages.search_keywords
IS
    'Language-specific search terms used by the Peach Suite Pro Help and Support Center search experience.';


COMMENT ON COLUMN help_pages.translation_status
IS
    'Translation workflow status for this language version: draft, review, or complete.';


-- =========================================================
-- INITIAL SUPPORT CATEGORIES
--
-- These are centrally managed defaults. Master Admin controls
-- their eventual use, ordering, labels, and topic assignments.
-- =========================================================

INSERT INTO help_categories (
    category_key,
    display_order
)
VALUES
    ('getting_started', 10),
    ('calendar_appointments', 20),
    ('clients', 30),
    ('square', 40),
    ('peachbook', 50),
    ('accounting', 60),
    ('employees', 70),
    ('website', 80),
    ('communications', 90),
    ('login_security', 100),
    ('coach_peach', 110)
ON CONFLICT (category_key) DO NOTHING;


INSERT INTO help_category_translations (
    help_category_id,
    language_code,
    display_name,
    public_slug
)
SELECT
    hc.help_category_id,
    seed.language_code,
    seed.display_name,
    seed.public_slug
FROM help_categories hc
JOIN (
    VALUES
        (
            'getting_started',
            'EN',
            'Getting Started',
            'getting-started'
        ),
        (
            'getting_started',
            'ES',
            'Primeros Pasos',
            'primeros-pasos'
        ),
        (
            'calendar_appointments',
            'EN',
            'Calendar & Appointments',
            'calendar-appointments'
        ),
        (
            'calendar_appointments',
            'ES',
            'Calendario y Citas',
            'calendario-citas'
        ),
        (
            'clients',
            'EN',
            'Clients',
            'clients'
        ),
        (
            'clients',
            'ES',
            'Clientes',
            'clientes'
        ),
        (
            'square',
            'EN',
            'Square',
            'square'
        ),
        (
            'square',
            'ES',
            'Square',
            'square'
        ),
        (
            'peachbook',
            'EN',
            'PeachBook',
            'peachbook'
        ),
        (
            'peachbook',
            'ES',
            'PeachBook',
            'peachbook'
        ),
        (
            'accounting',
            'EN',
            'Accounting',
            'accounting'
        ),
        (
            'accounting',
            'ES',
            'Contabilidad',
            'contabilidad'
        ),
        (
            'employees',
            'EN',
            'Employees',
            'employees'
        ),
        (
            'employees',
            'ES',
            'Empleados',
            'empleados'
        ),
        (
            'website',
            'EN',
            'Website',
            'website'
        ),
        (
            'website',
            'ES',
            'Sitio Web',
            'sitio-web'
        ),
        (
            'communications',
            'EN',
            'Communications',
            'communications'
        ),
        (
            'communications',
            'ES',
            'Comunicaciones',
            'comunicaciones'
        ),
        (
            'login_security',
            'EN',
            'Login & Security',
            'login-security'
        ),
        (
            'login_security',
            'ES',
            'Inicio de Sesión y Seguridad',
            'inicio-sesion-seguridad'
        ),
        (
            'coach_peach',
            'EN',
            'Coach Peach',
            'coach-peach'
        ),
        (
            'coach_peach',
            'ES',
            'Coach Peach',
            'coach-peach'
        )
) AS seed(
    category_key,
    language_code,
    display_name,
    public_slug
)
    ON seed.category_key = hc.category_key
ON CONFLICT (
    help_category_id,
    language_code
)
DO NOTHING;


-- =========================================================
-- BACKFILL EXISTING PSP HELP TOPICS
--
-- Every existing PSP-global page_key becomes one Help topic.
--
-- Existing Help remains visible in-app.
--
-- Web visibility is enabled as an intended destination, but every
-- backfilled topic starts in DRAFT publication state. Therefore,
-- nothing becomes public until Master Admin explicitly publishes it.
--
-- sms_email_terms remains a dedicated compliance workflow and is
-- not treated as an ordinary Web Support article.
-- =========================================================

INSERT INTO help_topics (
    page_key,
    display_order,
    show_in_app,
    show_on_web,
    publication_status,
    created_at,
    updated_at
)
SELECT
    hp.page_key,

    COALESCE(
        MAX(hp.display_order) FILTER (
            WHERE UPPER(
                COALESCE(hp.language_code, 'EN')
            ) = 'EN'
        ),
        MAX(hp.display_order)
    ) AS display_order,

    TRUE AS show_in_app,

    CASE
        WHEN hp.page_key = 'sms_email_terms'
            THEN FALSE
        ELSE TRUE
    END AS show_on_web,

    'draft' AS publication_status,

    NOW(),

    NOW()

FROM help_pages hp

WHERE hp.spa_id IS NULL

GROUP BY hp.page_key

ON CONFLICT (page_key) DO NOTHING;


COMMIT;
