from flask import Flask, render_template
import psycopg2

app = Flask(__name__)

def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="clearskin_spa",
        user="postgres",
        password="ChrisJoshKat3"
    )
    return conn


@app.route("/")
def home():
    return "HOME WORKS"  # -----render_template("index.html")#


@app.route("/test_db")
def test_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT current_database();")
    db_name = cur.fetchone()[0]

    cur.close()
    conn.close()

    return f"Connected to database: {db_name}"


# -------------------
# Client History - all clients
# -------------------
@app.route("/client_history")
def client_history():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT client_id, first_name, last_name
        FROM vw_client_visit_history
        ORDER BY last_name, first_name
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("client_history.html", rows=rows)
# -------------------
# One Client at a Time
# -------------------
@app.route("/client_history/<int:client_id>")
def client_history_detail(client_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM vw_client_visit_history
        WHERE client_id = %s
        ORDER BY appointment_date DESC NULLS LAST, appointment_time DESC NULLS LAST
    """, (client_id,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("client_history_detail.html", rows=rows, client_id=client_id)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
