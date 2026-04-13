4-11-26
added employee compensation tables, routes and html

CREATE TABLE employee_compensation (
    compensation_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    employee_id INT NOT NULL,
    compensation_date DATE NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT column_name
FROM information_schema.columns
WHERE table_name = 'income'
ORDER BY ordinal_position;

SELECT *
FROM information_schema.tables
WHERE table_name = 'employee_compensation';

CREATE TABLE compensation_types (
    compensation_type_id SERIAL PRIMARY KEY,
    spa_id INT NOT NULL,
    compensation_type_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO compensation_types (spa_id, compensation_type_name)
VALUES
(1, 'Tip Payout'),
(1, 'Draw'),
(1, 'Extra Pay'),
(1, 'Bonus');

ALTER TABLE employee_compensation
ADD COLUMN compensation_type_id INT,
ADD COLUMN amount NUMERIC(10,2);



CREATE TABLE employee_compensation_lines (
    line_id SERIAL PRIMARY KEY,
    compensation_id INT NOT NULL
        REFERENCES employee_compensation(compensation_id)
        ON DELETE CASCADE,
    compensation_type_id INT NOT NULL
        REFERENCES compensation_types(compensation_type_id),
    amount NUMERIC(10,2) NOT NULL DEFAULT 0
);
