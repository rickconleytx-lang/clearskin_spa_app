-- PEACH SUITE PRO
-- CORPORATE MARKETING CMS SECTION REGISTRATION V2
--
-- Additive initialization only.
-- No tables created or altered.
-- No existing revisions, drafts or publications modified.
-- No website content published.

BEGIN;

INSERT INTO psp_marketing_pages (
    page_key,
    display_name
)
VALUES
    ('home.peachweb', 'PeachWeb Showcase'),
    ('home.peachbook', 'PeachBook Showcase'),
    ('home.promo', 'Home Page Product Promotion'),
    ('product.solo', 'Solo'),
    ('product.peachpos', 'PeachPOS'),
    ('product.team', 'Team'),
    ('product.collective', 'Peach Collective'),
    (
        'marketing.benefits',
        'Additional Services & Launch Benefits'
    )
ON CONFLICT (page_key) DO NOTHING;

INSERT INTO psp_marketing_page_state (
    page_key
)
SELECT page_key
FROM psp_marketing_pages
WHERE page_key IN (
    'home.peachweb',
    'home.peachbook',
    'home.promo',
    'product.solo',
    'product.peachpos',
    'product.team',
    'product.collective',
    'marketing.benefits'
)
ON CONFLICT (page_key) DO NOTHING;

COMMIT;
