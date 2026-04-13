for each SQL file use touch "name".sql
example:
touch sql_updates/2026_04_11_add_owner_funding_tables.sql

#------------


inside copy any SQL changes:
EXAMPLE of SQL file

-- 2026_04_11_add_owner_funding_tables.sql
-- Purpose: add owner contribution and repayment tracking

BEGIN;

CREATE TABLE IF NOT EXISTS owner_contributions (
    contribution_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    contribution_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0),
    source_notes TEXT,
    memo TEXT
);

CREATE TABLE IF NOT EXISTS owner_repayments (
    repayment_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL REFERENCES spas(spa_id) ON DELETE CASCADE,
    repayment_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0),
    memo TEXT
);

COMMIT;


#-----------------

That gives you:
one file per schema change
a history of what changed
something you can run locally first, then on Render


STEPS
1.  create or alter SQL on pgAdmin  LOCAL
2.  test the table on pgAdmin LOCAL
3.  Run/Create the same on pgAdmin Render Live
4.  Push new code to Render:
    git add .
    git commit -m "Add owner funding tables"
    git push
5.  Create LOG FILE (SQL file - like this) in SQL Updates
6.  enter what SQL file contains into the README_applied_updates.sql 


