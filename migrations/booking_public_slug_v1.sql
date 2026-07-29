BEGIN;

ALTER TABLE booking_settings
ADD COLUMN IF NOT EXISTS public_booking_slug VARCHAR(120);


WITH slug_source AS (
    SELECT
        bs.booking_settings_id,
        bs.business_unit_id,

        LOWER(
            TRIM(
                BOTH '-'
                FROM REGEXP_REPLACE(
                    COALESCE(
                        NULLIF(TRIM(bu.unit_name), ''),
                        NULLIF(TRIM(s.spa_name), ''),
                        'booking-' || bs.business_unit_id::TEXT
                    ),
                    '[^a-zA-Z0-9]+',
                    '-',
                    'g'
                )
            )
        ) AS base_slug

    FROM booking_settings bs

    JOIN business_units bu
      ON bu.business_unit_id = bs.business_unit_id
     AND bu.spa_id = bs.spa_id

    JOIN spas s
      ON s.spa_id = bs.spa_id
),

ranked_slugs AS (
    SELECT
        booking_settings_id,
        business_unit_id,
        base_slug,

        COUNT(*) OVER (
            PARTITION BY base_slug
        ) AS matching_slug_count

    FROM slug_source
)

UPDATE booking_settings bs
SET public_booking_slug =
    CASE
        WHEN rs.base_slug IS NULL
          OR rs.base_slug = ''
        THEN
            'booking-' || rs.business_unit_id::TEXT

        WHEN rs.matching_slug_count = 1
        THEN
            rs.base_slug

        ELSE
            rs.base_slug
            || '-'
            || rs.business_unit_id::TEXT
    END

FROM ranked_slugs rs

WHERE bs.booking_settings_id =
      rs.booking_settings_id

  AND (
        bs.public_booking_slug IS NULL
        OR TRIM(bs.public_booking_slug) = ''
      );


ALTER TABLE booking_settings
ALTER COLUMN public_booking_slug SET NOT NULL;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname =
              'chk_booking_settings_public_slug'
    ) THEN
        ALTER TABLE booking_settings
        ADD CONSTRAINT
            chk_booking_settings_public_slug
        CHECK (
            public_booking_slug ~
            '^[a-z0-9]+(-[a-z0-9]+)*$'
        );
    END IF;
END
$$;


CREATE UNIQUE INDEX IF NOT EXISTS
idx_booking_settings_public_slug
ON booking_settings (
    public_booking_slug
);


COMMIT;
