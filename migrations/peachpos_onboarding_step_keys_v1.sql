-- PeachPOS onboarding step keys v1
-- Preserve all nine existing Solo onboarding keys.
-- Add pos_inventory and website_menu_items.
-- No business or onboarding records are modified.

BEGIN;

DO $peachpos$
DECLARE
    current_definition text;
    current_keys text[];
    original_keys text[];
    desired_keys text[];
BEGIN
    SELECT pg_get_constraintdef(c.oid)
      INTO current_definition
    FROM pg_constraint c
    WHERE c.conrelid =
          'public.business_onboarding_steps'::regclass
      AND c.conname = 'business_onboarding_steps_key_check'
      AND c.contype = 'c';

    IF current_definition IS NULL THEN
        RAISE EXCEPTION
            'Expected onboarding step constraint not found';
    END IF;

    SELECT ARRAY(
        SELECT (m.captures)[1]
        FROM regexp_matches(
            current_definition,
            '''([^'']+)''',
            'g'
        ) AS m(captures)
        ORDER BY 1
    )
    INTO current_keys;

    SELECT ARRAY(
        SELECT item
        FROM unnest(ARRAY[
            'service_catalog',
            'website_services',
            'public_website_settings',
            'booking_control_center',
            'business_hours',
            'provider_hours',
            'provider_services',
            'provider_time_off',
            'website_links'
        ]::text[]) AS t(item)
        ORDER BY item
    )
    INTO original_keys;

    SELECT ARRAY(
        SELECT item
        FROM unnest(
            original_keys || ARRAY[
                'pos_inventory',
                'website_menu_items'
            ]::text[]
        ) AS t(item)
        ORDER BY item
    )
    INTO desired_keys;

    IF current_keys = desired_keys THEN
        RAISE NOTICE
            'PeachPOS onboarding keys already supported';

    ELSIF current_keys = original_keys THEN

        ALTER TABLE public.business_onboarding_steps
            DROP CONSTRAINT
            business_onboarding_steps_key_check;

        ALTER TABLE public.business_onboarding_steps
            ADD CONSTRAINT
            business_onboarding_steps_key_check
            CHECK (
                step_key IN (
                    'service_catalog',
                    'website_services',
                    'public_website_settings',
                    'booking_control_center',
                    'business_hours',
                    'provider_hours',
                    'provider_services',
                    'provider_time_off',
                    'website_links',
                    'pos_inventory',
                    'website_menu_items'
                )
            );

        RAISE NOTICE
            'PeachPOS onboarding keys added; Solo keys preserved';

    ELSE
        RAISE EXCEPTION
            'Unexpected onboarding constraint keys: %',
            current_keys;
    END IF;
END;
$peachpos$;

COMMIT;
