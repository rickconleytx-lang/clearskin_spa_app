BEGIN;

CREATE TABLE IF NOT EXISTS public_website_settings (
    public_website_setting_id BIGSERIAL PRIMARY KEY,

    spa_id INTEGER NOT NULL UNIQUE
        REFERENCES spas(spa_id)
        ON DELETE CASCADE,

    hero_headline VARCHAR(180) NOT NULL,

    intro_heading VARCHAR(180) NOT NULL,
    intro_description TEXT NOT NULL,

    services_heading VARCHAR(180) NOT NULL,
    services_description TEXT NOT NULL,

    booking_heading VARCHAR(180) NOT NULL,
    booking_description TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


INSERT INTO public_website_settings (
    spa_id,
    hero_headline,
    intro_heading,
    intro_description,
    services_heading,
    services_description,
    booking_heading,
    booking_description
)
VALUES (
    1,
    'Healthy skin begins with personalized care.',
    'Skincare designed for you',
    'Every treatment begins with an understanding of your skin and your goals. Together, we will select the service that best supports your skincare journey.',
    'Professional treatments with a personal touch',
    'Explore a selection of treatments designed to refresh, restore, and support healthier-looking skin.',
    'Ready to make time for your skin?',
    'Choose your service, select an available appointment, and let Clear Skin Esthetics take care of the rest.'
)
ON CONFLICT (spa_id) DO NOTHING;

COMMIT;
