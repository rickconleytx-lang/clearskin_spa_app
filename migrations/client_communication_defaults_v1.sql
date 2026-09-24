-- Safe communication defaults for newly created clients.
--
-- This migration changes COLUMN DEFAULTS only.
-- It does NOT alter communication preferences on existing clients.

ALTER TABLE clients
    ALTER COLUMN ok_to_call SET DEFAULT FALSE,
    ALTER COLUMN ok_to_text SET DEFAULT FALSE,
    ALTER COLUMN ok_to_email SET DEFAULT FALSE,
    ALTER COLUMN sms_opt_in SET DEFAULT FALSE,
    ALTER COLUMN sms_opt_out SET DEFAULT FALSE,
    ALTER COLUMN email_opt_in SET DEFAULT FALSE,
    ALTER COLUMN email_opt_out SET DEFAULT FALSE;
