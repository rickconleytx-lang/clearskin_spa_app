BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS about_heading VARCHAR(180)
        NOT NULL DEFAULT 'Personalized skincare with a personal touch',

    ADD COLUMN IF NOT EXISTS about_description TEXT
        NOT NULL DEFAULT
        'Clear Skin Esthetics provides thoughtful, customized skincare in a comfortable and welcoming environment. Each treatment is selected around your skin, your goals, and the results you want to achieve.',

    ADD COLUMN IF NOT EXISTS about_image_url TEXT,

    ADD COLUMN IF NOT EXISTS about_image_alt VARCHAR(250),

    ADD COLUMN IF NOT EXISTS show_about_section BOOLEAN
        NOT NULL DEFAULT TRUE;

COMMIT;
