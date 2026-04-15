THIS FILE IS FOR APRIL 14 DAY TIME WORK.

WORKED ON EMAIL CAMPAIGN


TABLES CREATED - ALTERED:




CREATE TABLE client_email_preferences (
    email_pref_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    client_id INT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    marketing_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    birthday_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    reminder_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    unsubscribed BOOLEAN NOT NULL DEFAULT FALSE,
    unsubscribed_date DATE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

SELECT * FROM client_email_preferences;





CREATE TABLE email_templates (
    email_template_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    template_name VARCHAR(100) NOT NULL,
    template_type VARCHAR(50) NOT NULL,  -- Birthday / Gift Certificate / Promotion
    subject_line VARCHAR(255) NOT NULL,
    body_text TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);



SELECT * FROM email_templates;





CREATE TABLE email_send_log (
    email_log_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    client_id INT,
    gift_certificate_id INT,
    email_template_id INT,
    email_type VARCHAR(50) NOT NULL,   -- Birthday / Gift Certificate / Promotion
    recipient_email VARCHAR(255) NOT NULL,
    subject_line VARCHAR(255) NOT NULL,
    sent_status VARCHAR(50) NOT NULL,  -- Pending / Sent / Failed / Skipped
    sent_date TIMESTAMP,
    error_message TEXT,
    related_year INT,
    notes TEXT
);

SELECT * FROM email_send_log;




CREATE TABLE promotions (
    promotion_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    promotion_name VARCHAR(150) NOT NULL,
    subject_line VARCHAR(255) NOT NULL,
    body_text TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

SELECT * FROM promotions;



ALTER TABLE email_send_log
ADD COLUMN promotion_id INT;



ALTER TABLE client_birthday_offers
ADD COLUMN email_template_id INT,
ADD COLUMN sent_status VARCHAR(50) DEFAULT 'Pending';





CREATE TABLE gift_certificate_email_reminders (
    gc_email_reminder_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    gift_cert_id INT NOT NULL REFERENCES gift_certificates(gift_cert_id) ON DELETE CASCADE,
    reminder_type VARCHAR(50) NOT NULL,   -- 30-day / 7-day / day-of / custom
    recipient_email VARCHAR(255) NOT NULL,
    sent_date TIMESTAMP,
    sent_status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    notes TEXT
);

all above uploaded to Render
