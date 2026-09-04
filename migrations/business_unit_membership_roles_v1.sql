BEGIN;

-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS UNIT MEMBERSHIP ROLES V1
--
-- Expands workspace membership roles for the current
-- Peach Suite Pro business-user permission model.
--
-- Business-facing roles:
--   organization_admin -> Business Administrator
--   management         -> Management
--   staff              -> Staff
--   provider           -> Provider
--   front_desk         -> Front Desk
--
-- Existing Enterprise role codes are preserved for
-- compatibility and possible future Enterprise use.
--
-- Master Admin is intentionally NOT a business-unit
-- membership role and is not added by this migration.
-- =========================================================

ALTER TABLE business_unit_memberships
    DROP CONSTRAINT IF EXISTS
        chk_business_unit_membership_role;

ALTER TABLE business_unit_memberships
    ADD CONSTRAINT chk_business_unit_membership_role
        CHECK (
            membership_role_code IN (
                'organization_owner',
                'organization_admin',
                'independent_provider',
                'scheduler',
                'bookkeeper',
                'management',
                'staff',
                'provider',
                'front_desk'
            )
        );

COMMIT;
