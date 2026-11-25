
CREATE TABLE security_login_attempt_details (
    system_log_id INTEGER PRIMARY KEY
        REFERENCES system_logs(log_id)
        ON DELETE CASCADE,

    failure_reason VARCHAR(64) NOT NULL,

    login_channel VARCHAR(40) NOT NULL,

    attempted_email_masked VARCHAR(260),

    attempted_email_fingerprint CHAR(64),

    source_fingerprint CHAR(64),

    browser_family VARCHAR(60),

    platform_family VARCHAR(60)
);

CREATE INDEX idx_security_login_attempt_email
ON security_login_attempt_details (
    attempted_email_fingerprint
);

CREATE INDEX idx_security_login_attempt_source
ON security_login_attempt_details (
    source_fingerprint
);
