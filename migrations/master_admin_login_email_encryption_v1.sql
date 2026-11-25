
ALTER TABLE security_login_attempt_details
ADD COLUMN attempted_email_ciphertext TEXT;

COMMENT ON COLUMN
security_login_attempt_details.attempted_email_ciphertext
IS 'AES-256-GCM encrypted attempted login email; '
   'decryption restricted to authorized Master Admin.';
