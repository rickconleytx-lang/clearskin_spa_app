-- Peach Suite Pro
-- Business Coach Profile contact emails
-- V1

ALTER TABLE business_coach_profiles
    ADD COLUMN IF NOT EXISTS business_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS personal_email VARCHAR(255);
