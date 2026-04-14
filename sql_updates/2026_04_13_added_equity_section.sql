4-13-26

added owner equity, and loan tables

April 13

CREATE TABLE owner_contributions (
    owner_contribution_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    contribution_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    funding_source VARCHAR(100),
    notes TEXT
);

CREATE TABLE owner_reimbursements (
    owner_reimbursement_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    reimbursement_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    payment_method VARCHAR(50),
    notes TEXT
);



CREATE TABLE business_loans (
    loan_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    loan_name VARCHAR(100) NOT NULL,
    lender_name VARCHAR(100),
    loan_start_date DATE,
    original_amount NUMERIC(10,2) NOT NULL CHECK (original_amount > 0),
    interest_rate NUMERIC(6,3),
    term_months INT,
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);


CREATE TABLE loan_payments (
    loan_payment_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    loan_id INT NOT NULL REFERENCES business_loans(loan_id) ON DELETE CASCADE,
    payment_date DATE NOT NULL,
    principal_paid NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (principal_paid >= 0),
    interest_paid NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (interest_paid >= 0),
    total_payment NUMERIC(10,2) NOT NULL CHECK (total_payment >= 0),
    notes TEXT
);






Added 6 html pages:

funding_home.html
add_owner_contribution.html
add_owner_reimbursement.html
loans_home.html
add_business_loan.html
add_loan_payment.html

added

Edit and Deletes

Push to Render complete
