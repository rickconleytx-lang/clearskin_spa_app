-- PEACH SUITE PRO
-- MARKETING CMS PAGE INTRODUCTION REGISTRATION V3
--
-- Additive initialization only.
-- No existing content, revisions or publications modified.
-- No public website content published.

BEGIN;

INSERT INTO psp_marketing_pages (
    page_key,
    display_name
)
VALUES
    (
        'packages.intro',
        'Subscription Packages Introduction'
    ),
    (
        'pricing.intro',
        'Pricing Introduction'
    )
ON CONFLICT (page_key) DO NOTHING;

INSERT INTO psp_marketing_page_state (
    page_key
)
SELECT page_key
FROM psp_marketing_pages
WHERE page_key IN (
    'packages.intro',
    'pricing.intro'
)
ON CONFLICT (page_key) DO NOTHING;

COMMIT;
