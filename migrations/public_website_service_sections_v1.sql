BEGIN;

ALTER TABLE public_website_settings
    ADD COLUMN IF NOT EXISTS
        show_services_two_section
        BOOLEAN NOT NULL DEFAULT FALSE,

    ADD COLUMN IF NOT EXISTS
        services_two_heading
        VARCHAR(180) NOT NULL
        DEFAULT 'Additional Services',

    ADD COLUMN IF NOT EXISTS
        services_two_description
        TEXT NOT NULL DEFAULT '',

    ADD COLUMN IF NOT EXISTS
        show_services_three_section
        BOOLEAN NOT NULL DEFAULT FALSE,

    ADD COLUMN IF NOT EXISTS
        services_three_heading
        VARCHAR(180) NOT NULL
        DEFAULT 'More Services',

    ADD COLUMN IF NOT EXISTS
        services_three_description
        TEXT NOT NULL DEFAULT '';


ALTER TABLE public_website_services
    ADD COLUMN IF NOT EXISTS
        website_section
        VARCHAR(30) NOT NULL
        DEFAULT 'services';


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
            'chk_public_website_services_section'
          AND conrelid =
                'public_website_services'::regclass
    ) THEN
        ALTER TABLE public_website_services
            ADD CONSTRAINT
                chk_public_website_services_section
            CHECK (
                website_section IN (
                    'services',
                    'services_two',
                    'services_three'
                )
            );
    END IF;
END
$$;


CREATE INDEX IF NOT EXISTS
    idx_public_website_services_section_order
ON public_website_services (
    spa_id,
    business_unit_id,
    show_on_public_website,
    website_section,
    website_sort_order
);


COMMIT;
