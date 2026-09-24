BEGIN;


-- =========================================================
-- PEACH SUITE PRO
-- BUSINESS MAILING ADDRESS V1
--
-- Adds a mailing address to the tenant-level business record.
--
-- Business / physical address remains authoritative in the
-- existing business_address_line1, business_address_line2,
-- city, state, and zip_code columns.
--
-- Existing businesses are not assumed to use their business
-- address as their mailing address.
-- =========================================================


ALTER TABLE spas
    ADD COLUMN IF NOT EXISTS mailing_address_same_as_business
        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS mailing_address_line1
        VARCHAR(150),
    ADD COLUMN IF NOT EXISTS mailing_address_line2
        VARCHAR(150),
    ADD COLUMN IF NOT EXISTS mailing_city
        VARCHAR(100),
    ADD COLUMN IF NOT EXISTS mailing_state
        VARCHAR(50),
    ADD COLUMN IF NOT EXISTS mailing_zip_code
        VARCHAR(20);


COMMENT ON COLUMN
    spas.mailing_address_same_as_business IS
    'TRUE when the business has explicitly confirmed that its mailing '
    'address is the same as its business / physical address.';


COMMENT ON COLUMN
    spas.mailing_address_line1 IS
    'Primary mailing street, PO Box, or other postal address line.';


COMMENT ON COLUMN
    spas.mailing_address_line2 IS
    'Optional secondary mailing address line such as suite, unit, '
    'building, or department.';


COMMENT ON COLUMN
    spas.mailing_city IS
    'City or locality for the business mailing address.';


COMMENT ON COLUMN
    spas.mailing_state IS
    'State, province, region, or other administrative area for the '
    'business mailing address.';


COMMENT ON COLUMN
    spas.mailing_zip_code IS
    'ZIP or postal code for the business mailing address.';


COMMIT;
