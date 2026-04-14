from flask import Flask, render_template, request, Response, send_file, redirect, url_for, session, flash
from datetime import date, timedelta, datetime
from psycopg2 import sql
from decimal import Decimal
import csv
import io
import os
from openpyxl import Workbook
from dotenv import load_dotenv
from openpyxl.styles import Font
from db import get_db_connection
output = io.StringIO()
file_data = io.BytesIO()
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-key")




#  ---------------------
#        HELPERS
#  --------------------

def get_status_id(status_name):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT gift_certificate_status_id
        FROM gift_certificate_statuses
        WHERE status_name = %s
    """, (status_name,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result[0] if result else None



def parse_bool(value):
    if value is None:
        return None

    value = str(value).strip().lower()

    if value in ("true", "yes", "y", "1", "on"):
        return True
    if value in ("false", "no", "n", "0", "off"):
        return False
    if value in ("none", "", "null"):
        return None

    return None



def split_client_name(full_name):
    if not full_name:
        return "", ""

    parts = full_name.strip().split()

    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def get_current_spa_id():
    return session.get("spa_id", 1)


def get_spa_today():
    return get_spa_now().date()


def get_spa_current_time():
    return get_spa_now().time()



#  ---------------
#   DONE HELPERS
#  --------------






#  ---------------
#   ERROR HANDLERS
#  --------------


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_server_error(error):
    return render_template("500.html"), 500








#  -------------------------
#  
#     SAVE TIME ZONE SETTINGS
#  
#  -------------------------


@app.route("/save_time_settings", methods=["POST"])
def save_time_settings():
    spa_id = get_current_spa_id()

    timezone_name = request.form.get("timezone_name", "").strip()

    # PUT IT RIGHT HERE
    allowed_timezones = {
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Anchorage",
        "Pacific/Honolulu",
        "America/Toronto",
        "America/Vancouver",
        "America/Edmonton",
        "America/Halifax",
        "Europe/London",
        "Europe/Dublin",
        "Europe/Paris",
        "Europe/Berlin",
        "Europe/Madrid",
        "Europe/Rome",
        "Australia/Sydney",
        "Australia/Perth",
        "Asia/Tokyo",
        "Asia/Singapore",
        "Asia/Dubai"
    }

    if timezone_name not in allowed_timezones:
        flash("Invalid timezone selected.", "error")
        return redirect(url_for("admin"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE spas
        SET timezone_name = %s
        WHERE spa_id = %s
    """, (timezone_name, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Time settings updated successfully.", "success")
    return redirect(url_for("admin"))











#  -------------------------
#
#  SQUARE WEBHOOK
#
#  -------------------------

@app.route("/square/webhook", methods=["POST"])
def square_webhook():
    payload = request.get_data(as_text=True)
    signature = request.headers.get("x-square-hmacsha256-signature")

    # validate signature here

    event = request.get_json()

    # look for booking.created
    # parse booking id and details
    # insert into incoming_square_bookings if not already present

    return "", 200






#  -------------------
#   Square Incomming Bookings
#
#  ------------------

@app.route("/incoming_bookings")
def incoming_bookings():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            incoming_booking_id,
            square_booking_id,
            client_name,
            client_email,
            client_phone,
            appointment_date,
            appointment_time,
            service_name,
            status,
            created_at
        FROM incoming_square_bookings
        ORDER BY
            CASE WHEN status = 'new' THEN 0 ELSE 1 END,
            appointment_date,
            appointment_time,
            created_at DESC
    """)
    bookings = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("incoming_bookings.html", bookings=bookings)


#  -------------------------------------
#   Square Incoming Booking Review
#
#  ------------------------------------

@app.route("/incoming_bookings/<int:incoming_booking_id>")
def review_incoming_booking(incoming_booking_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            incoming_booking_id,
            square_booking_id,
            client_name,
            client_email,
            client_phone,
            appointment_date,
            appointment_time,
            service_name,
            status,
            raw_payload,
            created_at
        FROM incoming_square_bookings
        WHERE incoming_booking_id = %s
    """, (incoming_booking_id,))
    booking = cur.fetchone()

    cur.close()
    conn.close()

    if not booking:
        flash("Incoming booking not found.", "error")
        return redirect(url_for("incoming_bookings"))

    return render_template("review_incoming_booking.html", booking=booking)




#  ----------------------------------
#
#  SQUARE Ignore incoming 
#
#  ----------------------------------

@app.route("/incoming_bookings/<int:incoming_booking_id>/ignore", methods=["POST"])
def ignore_incoming_booking(incoming_booking_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE incoming_square_bookings
        SET status = 'ignored',
            reviewed_at = CURRENT_TIMESTAMP
        WHERE incoming_booking_id = %s
    """, (incoming_booking_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash("Incoming booking marked as ignored.", "success")
    return redirect(url_for("incoming_bookings"))



#  ------------------------------
#
#  SQUARE ADD NEW CLIENT 
#
#  -----------------------------
  

@app.route("/incoming_bookings/<int:incoming_booking_id>/add_new_client")
def add_new_client_from_booking(incoming_booking_id):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT *
            FROM incoming_bookings
            WHERE incoming_booking_id = %s
        """, (incoming_booking_id,))

        booking = cur.fetchone()

        if not booking:
            flash("Booking record not found.", "error")
            return redirect(url_for("dashboard"))

        return render_template(
            "add_new_client.html",
            booking=booking
        )

    except Exception as e:
        flash(f"Error loading booking: {str(e)}", "error")
        return redirect(url_for("dashboard"))

    finally:
        cur.close()
        conn.close()

    cur.execute("""
        SELECT
            incoming_booking_id,
            client_name,
            client_email,
            client_phone,
            appointment_date,
            appointment_time,
            service_name
        FROM incoming_square_bookings
        WHERE incoming_booking_id = %s
    """, (incoming_booking_id,))
    booking = cur.fetchone()

    cur.close()
    conn.close()

    if not booking:
        flash("Incoming booking not found.", "error")
        return redirect(url_for("incoming_bookings"))

    first_name, last_name = split_client_name(booking[1])

    session["incoming_booking_data"] = {
        "incoming_booking_id": booking[0],
        "first_name": first_name,
        "last_name": last_name,
        "email": booking[2] or "",
        "phone": booking[3] or "",
        "appointment_date": booking[4].strftime("%Y-%m-%d") if booking[4] else "",
        "appointment_time": booking[5].strftime("%H:%M:%S") if booking[5] else "",
        "service_name": booking[6] or ""
    }

    return redirect(url_for("add_new_client"))






#  ------------------
#
#  SQUARE MATCH EXISTING
#
#  ------------------



@app.route("/incoming_bookings/<int:incoming_booking_id>/match_existing_client")
def match_existing_client_booking(incoming_booking_id):
    flash("Next step: choose existing client and create appointment.", "info")
    return redirect(url_for("review_incoming_booking", incoming_booking_id=incoming_booking_id))










#  ----------------------
#
#   DATABASE HOME
#
#  ----------------------

@app.route("/")
def home():
    return render_template("home.html")

DROPDOWN_CONFIG = {
    "appointment_status": {
        "title": "Appointment Status",
        "table": "appointment_status",
        "pk": "status_id",
        "value": "status_name",
        "label": "Status Name"
    },
        "referral_sources": {
    "title": "Referral Sources",
    "table": "referral_sources",
    "pk": "referral_source_id",
    "value": "referral_source_name",
    "label": "Referral Source Name"
   },
    "client_form_names": {
        "title": "Client Form Names",
        "table": "client_form_names",
        "pk": "form_type",
        "value": "form_type_name",
        "label": "Form Type Name"
    },
    "expense_categories": {
        "title": "Expense Categories",
        "table": "expense_categories",
        "pk": "expense_cat_id",
        "value": "expense_cat_name",
        "label": "Expense Category Name"
    },
    "income_types": {
        "title": "Income Types",
        "table": "income_types",
        "pk": "income_type_id",
        "value": "income_type_name",
        "label": "Income Type Name"
    },
    "payment_methods": {
        "title": "Payment Methods",
        "table": "payment_methods",
        "pk": "payment_method_id",
        "value": "payment_method",
        "label": "Payment Method"
    },
    "service_name_types": {
        "title": "Service Name Types",
        "table": "service_name_types",
        "pk": "service_type_id",
        "value": "service_name",
        "label": "Service Name"
    },
    "sex": {
        "title": "Sex",
        "table": "sex",
        "pk": "sex_type_id",
        "value": "sex_type",
        "label": "Sex Type"
    },
    "treatment_rooms": {
        "title": "Treatment Rooms",
        "table": "treatment_rooms",
        "pk": "room_id",
        "value": "room_name",
        "label": "Room Name"
    },
    "vendor_name": {
        "title": "Vendor Name",
        "table": "vendor_name",
        "pk": "vendor_id",
        "value": "vendors_name",
        "label": "Vendor Name"
    }
}




#  -------------------------------
#           DROP DOWNS
#
#
#  APPOINTMENT STATUS
#  CLIENT FORM NAME  
#  EXPENSE CATEGORIES  
#  INCOME TYPES
#  PAYMENT METHODS
#  SERVICE NAME TYPES
#  SEX
#  TREATMENT ROOMS
#  VENDOR NAMES
#
#
#  --------------------------------


@app.route("/admin/dropdowns/<dropdown_key>", methods=["GET", "POST"])
def manage_dropdown(dropdown_key):
    spa_id = get_current_spa_id()

    if dropdown_key not in DROPDOWN_CONFIG:
        flash("Invalid dropdown selection.", "error")
        return redirect(url_for("admin"))

    config = DROPDOWN_CONFIG[dropdown_key]

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        new_value = request.form.get("new_value", "").strip()

        if new_value:
            try:
                cur.execute(
                    sql.SQL("INSERT INTO {table} ({value_col}) VALUES (%s)").format(
                        table=sql.Identifier(config["table"]),
                        value_col=sql.Identifier(config["value"])
                    ),
                    (new_value,)
                )
                conn.commit()
                flash(f'{config["title"]} added successfully.', "success")
            except Exception as e:
                conn.rollback()
                flash(f"Error adding item: {e}", "error")
        else:
            flash("Value cannot be blank.", "error")

        cur.close()
        conn.close()
        return redirect(url_for("manage_dropdown", dropdown_key=dropdown_key))

    cur.execute(
        sql.SQL("""
            SELECT {pk_col}, {value_col}
            FROM {table}
            ORDER BY {value_col}
        """).format(
            pk_col=sql.Identifier(config["pk"]),
            value_col=sql.Identifier(config["value"]),
            table=sql.Identifier(config["table"])
        )
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dropdown_generic.html",
        dropdown_key=dropdown_key,
        title=config["title"],
        label=config["label"],
        rows=rows
    )


#  --------------------------------
#
#     DROP DOWNS  DELETE FUNCTION
#
# ROUTE:  admin/dropdowns
# 
#  ------------------------------


@app.route("/admin/dropdowns/<dropdown_key>/delete/<path:item_id>", methods=["POST"])
def delete_dropdown_item(dropdown_key, item_id):
    spa_id = get_current_spa_id()

    if dropdown_key not in DROPDOWN_CONFIG:
        flash("Invalid dropdown selection.", "error")
        return redirect(url_for("admin"))

    config = DROPDOWN_CONFIG[dropdown_key]

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            sql.SQL("DELETE FROM {table} WHERE {pk_col} = %s").format(
                table=sql.Identifier(config["table"]),
                pk_col=sql.Identifier(config["pk"])
            ),
            (item_id,)
        )
        conn.commit()
        flash("Item deleted successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting item: {e}", "error")

    cur.close()
    conn.close()

    return redirect(url_for("manage_dropdown", dropdown_key=dropdown_key))









#  ---------------------
#
#     HELP PAGES
#
#  -----------------



@app.route("/help")
def help_page():
    return render_template("help.html")



@app.route("/help_calendar")
def help_calendar_page():   
    return render_template("help_calendar.html")


    
@app.route("/help_appointments")
def help_appointments_page():
    return render_template("help_appointments.html")
            


@app.route("/help_client_management")
def help_client_management_page():
    return render_template("help_client_management.html")
 

@app.route("/help_add_new_client")
def help_add_new_client_page():
    return render_template("help_add_new_client.html")



@app.route("/help_clients")
def help_clients_page():
    return render_template("help_clients.html")


@app.route("/help_birthday_offer")
def help_birthday_offer_page():
    return render_template("help_birthday_offer.html")



@app.route("/help_income")
def help_income_page():
    return render_template("help_income.html")



@app.route("/help_gift_certs")
def help_gift_certs_page():
    return render_template("help_gift_certs.html")


@app.route("/help_expenses")
def help_expenses_page():
    return render_template("help_expenses.html")


@app.route("/help_admin")
def help_admin_page():
    return render_template("help_admin.html")




                 
#   -----------------------
#               
#     SPA MANAGEMENT PAGE
#               
#  ----------------------

@app.route("/spa_management")
def spa_management():
    return render_template("spa_management.html")




#   -----------------------
#  
#     CREDIT   PROCESSORS
#
#  ----------------------

@app.route("/credit_processors")
def credit_processors():
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            credit_processor_id,
            credit_processor_name,
            percentage_fee,
            flat_fee,
            additional_fee,
            is_active
        FROM credit_processors
        WHERE spa_id = %s
        ORDER BY credit_processor_name
    """, (spa_id,))

    processors = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "credit_processors.html",
        processors=processors
    )




#   -----------------------
#     
#      ADD CREDIT PROCESSORS
#  
#  ----------------------




@app.route("/credit_processors/add", methods=["GET", "POST"])
def add_credit_processor():
    spa_id = get_current_spa_id()

    if request.method == "POST":
        credit_processor_name = request.form.get("credit_processor_name", "").strip()
        percentage_fee = request.form.get("percentage_fee") or 0
        flat_fee = request.form.get("flat_fee") or 0
        additional_fee = request.form.get("additional_fee") or 0

        if not credit_processor_name:
            flash("Processor name is required.", "error")
            return redirect(url_for("add_credit_processor"))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO credit_processors (
                spa_id,
                credit_processor_name,
                percentage_fee,
                flat_fee,
                additional_fee,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (
            spa_id,
            credit_processor_name,
            percentage_fee,
            flat_fee,
            additional_fee
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Credit processor added successfully.", "success")
        return redirect(url_for("credit_processors"))

    return render_template("add_credit_processor.html")




#   ----------------------------
#     
#     EDIT CREDIT PROCESSOR
#  
#  ----------------------------



@app.route("/credit_processors/edit/<int:credit_processor_id>", methods=["GET", "POST"])
def edit_credit_processor(credit_processor_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        credit_processor_name = request.form.get("credit_processor_name", "").strip()
        percentage_fee = request.form.get("percentage_fee") or 0
        flat_fee = request.form.get("flat_fee") or 0
        additional_fee = request.form.get("additional_fee") or 0

        if not credit_processor_name:
            cur.close()
            conn.close()
            flash("Processor name is required.", "error")
            return redirect(url_for("edit_credit_processor", credit_processor_id=credit_processor_id))

        cur.execute("""
            UPDATE credit_processors
            SET credit_processor_name = %s,
                percentage_fee = %s,
                flat_fee = %s,
                additional_fee = %s
            WHERE credit_processor_id = %s
              AND spa_id = %s
        """, (
            credit_processor_name,
            percentage_fee,
            flat_fee,
            additional_fee,
            credit_processor_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Credit processor updated successfully.", "success")
        return redirect(url_for("credit_processors"))

    cur.execute("""
        SELECT
            credit_processor_id,
            credit_processor_name,
            percentage_fee,
            flat_fee,
            additional_fee,
            is_active
        FROM credit_processors
        WHERE credit_processor_id = %s
          AND spa_id = %s
    """, (credit_processor_id, spa_id))

    processor = cur.fetchone()

    cur.close()
    conn.close()

    if not processor:
        flash("Credit processor not found.", "error")
        return redirect(url_for("credit_processors"))

    return render_template(
        "edit_credit_processor.html",
        processor=processor
    )




#   ------------------------------
#     TOGGLE ACTIVE/DEACTIVATE
#     CREDIT PROCESSORS
#  
#  ------------------------------


@app.route("/credit_processors/toggle/<int:credit_processor_id>", methods=["POST"])
def toggle_credit_processor(credit_processor_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE credit_processors
        SET is_active = NOT is_active
        WHERE credit_processor_id = %s
          AND spa_id = %s
    """, (credit_processor_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Credit processor status updated.", "success")
    return redirect(url_for("credit_processors"))












#   -----------------------
#
#     FUTURE CALENDAR SYNC
#
#  ----------------------
    
    
@app.route("/admin/sync_calendar")
def sync_calendar():
    flash(
        "Google Calendar sync is not active yet. This feature will be added after deployment.",
        "info"
    )
    return redirect(url_for("admin"))





#   ------------------------------------------
#
#     Owner and Loan Funding
#
#       HELPERS
#
#   ------------------------------------------







#   --------------------------------------------------
#
#
#              HELPER   QUERY
#
#
#  ----------------------------------------------------




from datetime import date


def get_loan_contribution_rows(spa_id, start_date=None, end_date=None):
    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT
            contribution_date AS activity_date,
            'Owner Contribution' AS activity_type,
            funding_source AS description,
            amount,
            NULL AS payment_method,
            NULL AS loan_name,
            notes
        FROM owner_contributions
        WHERE spa_id = %s
    """
    params = [spa_id]

    if start_date:
        query += " AND contribution_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND contribution_date <= %s"
        params.append(end_date)

    query += """

        UNION ALL

        SELECT
            reimbursement_date AS activity_date,
            'Owner Reimbursement' AS activity_type,
            NULL AS description,
            amount,
            payment_method,
            NULL AS loan_name,
            notes
        FROM owner_reimbursements
        WHERE spa_id = %s
    """
    params.append(spa_id)

    if start_date:
        query += " AND reimbursement_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND reimbursement_date <= %s"
        params.append(end_date)

    query += """

        UNION ALL

        SELECT
            lp.payment_date AS activity_date,
            'Loan Payment' AS activity_type,
            CONCAT('Principal: $', lp.principal_paid,
                   ' / Interest: $', lp.interest_paid) AS description,
            lp.total_payment AS amount,
            NULL AS payment_method,
            bl.loan_name,
            lp.notes
        FROM loan_payments lp
        LEFT JOIN business_loans bl
            ON lp.loan_id = bl.loan_id
        WHERE lp.spa_id = %s
    """
    params.append(spa_id)

    if start_date:
        query += " AND lp.payment_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND lp.payment_date <= %s"
        params.append(end_date)

    query += " ORDER BY activity_date DESC"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    cur.close()
    conn.close()
    return rows

















#   --------------------------------------
#     LOAN CONTRIBUTIONS EXPORT   CSV
#
#   --------------------------------------

@app.route("/loan_contributions/export/csv")
def export_loan_contributions_csv():
    spa_id = get_current_spa_id()

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    rows = get_loan_contribution_rows(
        spa_id=spa_id,
        start_date=start_date or None,
        end_date=end_date or None
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Type",
        "Description",
        "Amount",
        "Payment Method",
        "Loan",
        "Notes"
    ])

    for row in rows:
        writer.writerow([
            row[0].strftime("%Y-%m-%d") if row[0] else "",
            row[1] or "",
            row[2] or "",
            f"{float(row[3]):.2f}" if row[3] is not None else "0.00",
            row[4] or "",
            row[5] or "",
            row[6] or ""
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=loan_contributions.csv"
        }
    )


#   --------------------------------------
#     LOAN CONTRIBUTIONS EXPORT   EXCEL
#
#   --------------------------------------

@app.route("/loan_contributions/export/excel")
def export_loan_contributions_excel():
    spa_id = get_current_spa_id()

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    rows = get_loan_contribution_rows(
        spa_id=spa_id,
        start_date=start_date or None,
        end_date=end_date or None
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Loans & Contributions"

    headers = [
        "Date",
        "Type",
        "Description",
        "Amount",
        "Payment Method",
        "Loan",
        "Notes"
    ]

    ws.append(headers)

    for row in rows:
        ws.append([
            row[0].strftime("%Y-%m-%d") if row[0] else "",
            row[1] or "",
            row[2] or "",
            float(row[3]) if row[3] is not None else 0.00,
            row[4] or "",
            row[5] or "",
            row[6] or ""
        ])

    # make columns fit nicely
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter

        for cell in column:
            try:
                max_length = max(max_length, len(str(cell.value)))
            except:
                pass

        ws.column_dimensions[column_letter].width = max_length + 2

    # format amount column
    for cell in ws["D"][1:]:
        cell.number_format = "$#,##0.00"

    file_data = io.BytesIO()
    wb.save(file_data)
    file_data.seek(0)

    return send_file(
        file_data,
        as_attachment=True,
        download_name="loan_contributions.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )















#   -----------------------  
#
#      FUNDING     
#
#  ----------------------
    


@app.route("/funding")
def funding_home():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM owner_contributions
        WHERE spa_id = %s
    """, (spa_id,))
    total_contributions = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM owner_reimbursements
        WHERE spa_id = %s
    """, (spa_id,))
    total_reimbursements = cur.fetchone()[0]

    net_owner_funding = total_contributions - total_reimbursements

    cur.execute("""
        SELECT
            owner_contribution_id,
            contribution_date,
            amount,
            funding_source,
            notes
        FROM owner_contributions
        WHERE spa_id = %s
        ORDER BY contribution_date DESC, owner_contribution_id DESC
    """, (spa_id,))
    contributions = cur.fetchall()

    cur.execute("""
        SELECT
            owner_reimbursement_id,
            reimbursement_date,
            amount,
            payment_method,
            notes
        FROM owner_reimbursements
        WHERE spa_id = %s
        ORDER BY reimbursement_date DESC, owner_reimbursement_id DESC
    """, (spa_id,))
    reimbursements = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "funding_home.html",
        total_contributions=total_contributions,
        total_reimbursements=total_reimbursements,
        net_owner_funding=net_owner_funding,
        contributions=contributions,
        reimbursements=reimbursements
    )
                
                
                
#   -----------------------
#
#    OWNER CONTRIBUTIONS                     
#
#  ----------------------
                    
                    
                      
@app.route("/owner_contributions/add", methods=["GET", "POST"])
def add_owner_contribution():
    spa_id = get_current_spa_id()

    if request.method == "POST":
        contribution_date = request.form.get("contribution_date")
        amount = request.form.get("amount")
        funding_source = request.form.get("funding_source", "").strip()
        notes = request.form.get("notes", "").strip()

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO owner_contributions (
                spa_id,
                contribution_date,
                amount,
                funding_source,
                notes
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            spa_id,
            contribution_date,
            amount,
            funding_source,
            notes
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Owner contribution added successfully.", "success")
        return redirect(url_for("funding_home"))

    return render_template("add_owner_contribution.html")
                
                

                
#   -----------------------
#
#   OWNER REIMBURSEMENTS      
#
#  ----------------------
                    
                    
@app.route("/owner_reimbursements/add", methods=["GET", "POST"])
def add_owner_reimbursement():
    spa_id = get_current_spa_id()

    if request.method == "POST":
        reimbursement_date = request.form.get("reimbursement_date")
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method", "").strip()
        notes = request.form.get("notes", "").strip()

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO owner_reimbursements (
                spa_id,
                reimbursement_date,
                amount,
                payment_method,
                notes
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            spa_id,
            reimbursement_date,
            amount,
            payment_method,
            notes
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Owner reimbursement added successfully.", "success")
        return redirect(url_for("funding_home"))

    return render_template("add_owner_reimbursement.html")


                
                
                
#   -----------------------
#
#   LOANS   HOME                   
#
#  ----------------------
                    
                    
                      

@app.route("/loans")
def loans_home():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            bl.loan_id,
            bl.loan_name,
            bl.lender_name,
            bl.loan_start_date,
            bl.original_amount,
            bl.interest_rate,
            bl.term_months,
            bl.notes,
            bl.is_active,
            COALESCE(SUM(lp.principal_paid), 0) AS principal_paid_total,
            COALESCE(SUM(lp.interest_paid), 0) AS interest_paid_total,
            bl.original_amount - COALESCE(SUM(lp.principal_paid), 0) AS remaining_balance
        FROM business_loans bl
        LEFT JOIN loan_payments lp
            ON bl.loan_id = lp.loan_id
           AND lp.spa_id = bl.spa_id
        WHERE bl.spa_id = %s
        GROUP BY
            bl.loan_id,
            bl.loan_name,
            bl.lender_name,
            bl.loan_start_date,
            bl.original_amount,
            bl.interest_rate,
            bl.term_months,
            bl.notes,
            bl.is_active
        ORDER BY bl.loan_start_date DESC NULLS LAST, bl.loan_id DESC
    """, (spa_id,))
    loans = cur.fetchall()

    cur.execute("""
        SELECT COALESCE(SUM(original_amount), 0)
        FROM business_loans
        WHERE spa_id = %s
    """, (spa_id,))
    total_original_loans = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(principal_paid), 0)
        FROM loan_payments
        WHERE spa_id = %s
    """, (spa_id,))
    total_principal_paid = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(interest_paid), 0)
        FROM loan_payments
        WHERE spa_id = %s
    """, (spa_id,))
    total_interest_paid = cur.fetchone()[0]

    total_remaining_balance = total_original_loans - total_principal_paid

    cur.close()
    conn.close()

    return render_template(
        "loans_home.html",
        loans=loans,
        total_original_loans=total_original_loans,
        total_principal_paid=total_principal_paid,
        total_interest_paid=total_interest_paid,
        total_remaining_balance=total_remaining_balance
    )

                
                

                
#   -----------------------
#
#    ADD BUSINESS LOANS                     
#
#  ----------------------
                    
                    
                      

@app.route("/business_loans/add", methods=["GET", "POST"])
def add_business_loan():
    spa_id = get_current_spa_id()

    if request.method == "POST":
        loan_name = request.form.get("loan_name", "").strip()
        lender_name = request.form.get("lender_name", "").strip()
        loan_start_date = request.form.get("loan_start_date") or None
        original_amount = request.form.get("original_amount")
        interest_rate = request.form.get("interest_rate") or None
        term_months = request.form.get("term_months") or None
        notes = request.form.get("notes", "").strip()
        is_active = True if request.form.get("is_active") == "yes" else False

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO business_loans (
                spa_id,
                loan_name,
                lender_name,
                loan_start_date,
                original_amount,
                interest_rate,
                term_months,
                notes,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            spa_id,
            loan_name,
            lender_name,
            loan_start_date,
            original_amount,
            interest_rate,
            term_months,
            notes,
            is_active
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Business loan added successfully.", "success")
        return redirect(url_for("loans_home"))

    return render_template("add_business_loan.html")

                
                
                
#   -----------------------
#
#    ADD LOAN PAYMENT                     
#
#  ----------------------
                    
                    
                      

@app.route("/loan_payments/add", methods=["GET", "POST"])
def add_loan_payment():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        loan_id = request.form.get("loan_id")
        payment_date = request.form.get("payment_date")
        principal_paid = float(request.form.get("principal_paid") or 0)
        interest_paid = float(request.form.get("interest_paid") or 0)
        total_payment = principal_paid + interest_paid
        notes = request.form.get("notes", "").strip()

        cur.execute("""
            INSERT INTO loan_payments (
                spa_id,
                loan_id,
                payment_date,
                principal_paid,
                interest_paid,
                total_payment,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            spa_id,
            loan_id,
            payment_date,
            principal_paid,
            interest_paid,
            total_payment,
            notes
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Loan payment added successfully.", "success")
        return redirect(url_for("loans_home"))

    cur.execute("""
        SELECT loan_id, loan_name
        FROM business_loans
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY loan_name
    """, (spa_id,))
    loans = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "add_loan_payment.html",
        loans=loans
    )





#   ------------------------------------
#   
#         EDIT OWNER CONTRIBUTIONS   
#  
#   
#   --------------------------------


@app.route("/owner_contributions/edit/<int:owner_contribution_id>", methods=["GET", "POST"])
def edit_owner_contribution(owner_contribution_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        contribution_date = request.form.get("contribution_date")
        amount = request.form.get("amount")
        funding_source = request.form.get("funding_source", "").strip()
        notes = request.form.get("notes", "").strip()

        cur.execute("""
            UPDATE owner_contributions
            SET contribution_date = %s,
                amount = %s,
                funding_source = %s,
                notes = %s
            WHERE owner_contribution_id = %s
              AND spa_id = %s
        """, (
            contribution_date,
            amount,
            funding_source,
            notes,
            owner_contribution_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Owner contribution updated successfully.", "success")
        return redirect(url_for("funding_home"))

    cur.execute("""
        SELECT
            owner_contribution_id,
            contribution_date,
            amount,
            funding_source,
            notes
        FROM owner_contributions
        WHERE owner_contribution_id = %s
          AND spa_id = %s
    """, (owner_contribution_id, spa_id))

    contribution = cur.fetchone()

    cur.close()
    conn.close()

    if not contribution:
        flash("Owner contribution not found.", "error")
        return redirect(url_for("funding_home"))

    return render_template(
        "edit_owner_contribution.html",
        contribution=contribution
    )








#   ------------------------------------
#
#      DELETE OWNER CONTRIBUTIONS
#                    
#
#   --------------------------------



@app.route("/owner_contributions/delete/<int:owner_contribution_id>", methods=["POST"])
def delete_owner_contribution(owner_contribution_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM owner_contributions
        WHERE owner_contribution_id = %s
          AND spa_id = %s
    """, (owner_contribution_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Owner contribution deleted successfully.", "success")
    return redirect(url_for("funding_home"))







        
#   ------------------------------------
#
#    EDIT OWNER REIMBURSEMENTS
#
#
#   --------------------------------
                     

@app.route("/owner_reimbursements/edit/<int:owner_reimbursement_id>", methods=["GET", "POST"])
def edit_owner_reimbursement(owner_reimbursement_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        reimbursement_date = request.form.get("reimbursement_date")
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method", "").strip()
        notes = request.form.get("notes", "").strip()

        cur.execute("""
            UPDATE owner_reimbursements
            SET reimbursement_date = %s,
                amount = %s,
                payment_method = %s,
                notes = %s
            WHERE owner_reimbursement_id = %s
              AND spa_id = %s
        """, (
            reimbursement_date,
            amount,
            payment_method,
            notes,
            owner_reimbursement_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Owner reimbursement updated successfully.", "success")
        return redirect(url_for("funding_home"))

    cur.execute("""
        SELECT
            owner_reimbursement_id,
            reimbursement_date,
            amount,
            payment_method,
            notes
        FROM owner_reimbursements
        WHERE owner_reimbursement_id = %s
          AND spa_id = %s
    """, (owner_reimbursement_id, spa_id))

    reimbursement = cur.fetchone()

    cur.close()
    conn.close()

    if not reimbursement:
        flash("Owner reimbursement not found.", "error")
        return redirect(url_for("funding_home"))

    return render_template(
        "edit_owner_reimbursement.html",
        reimbursement=reimbursement
    )







#   ------------------------------------
#   
#       DELETE OWNER REIMBURSEMENT        
#  
#   
#   --------------------------------


@app.route("/owner_reimbursements/delete/<int:owner_reimbursement_id>", methods=["POST"])
def delete_owner_reimbursement(owner_reimbursement_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM owner_reimbursements
        WHERE owner_reimbursement_id = %s
          AND spa_id = %s
    """, (owner_reimbursement_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Owner reimbursement deleted successfully.", "success")
    return redirect(url_for("funding_home"))






#   ------------------------------------
#   
#      EDIT LOAN    
#   
#   
#   --------------------------------

@app.route("/business_loans/edit/<int:loan_id>", methods=["GET", "POST"])
def edit_business_loan(loan_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        loan_name = request.form.get("loan_name", "").strip()
        lender_name = request.form.get("lender_name", "").strip()
        loan_start_date = request.form.get("loan_start_date") or None
        original_amount = request.form.get("original_amount")
        interest_rate = request.form.get("interest_rate") or None
        term_months = request.form.get("term_months") or None
        notes = request.form.get("notes", "").strip()
        is_active = True if request.form.get("is_active") == "yes" else False

        cur.execute("""
            UPDATE business_loans
            SET loan_name = %s,
                lender_name = %s,
                loan_start_date = %s,
                original_amount = %s,
                interest_rate = %s,
                term_months = %s,
                notes = %s,
                is_active = %s
            WHERE loan_id = %s
              AND spa_id = %s
        """, (
            loan_name,
            lender_name,
            loan_start_date,
            original_amount,
            interest_rate,
            term_months,
            notes,
            is_active,
            loan_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Business loan updated successfully.", "success")
        return redirect(url_for("loans_home"))

    cur.execute("""
        SELECT
            loan_id,
            loan_name,
            lender_name,
            loan_start_date,
            original_amount,
            interest_rate,
            term_months,
            notes,
            is_active
        FROM business_loans
        WHERE loan_id = %s
          AND spa_id = %s
    """, (loan_id, spa_id))

    loan = cur.fetchone()

    cur.close()
    conn.close()

    if not loan:
        flash("Business loan not found.", "error")
        return redirect(url_for("loans_home"))

    return render_template(
        "edit_business_loan.html",
        loan=loan
    )






#   ------------------------------------
#   
#   DELETE BUSINESS LOAN
#   
#   
#   ------------------------------------


@app.route("/business_loans/delete/<int:loan_id>", methods=["POST"])
def delete_business_loan(loan_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM business_loans
        WHERE loan_id = %s
          AND spa_id = %s
    """, (loan_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Business loan and all related payments deleted successfully.", "success")
    return redirect(url_for("loans_home"))



















#   ------------------------------------
#   
#   
#   
#   
#   --------------------------------









#   ------------------------------------
#   
#   
#   
#   
#   --------------------------------

















#   ------------------------------------
#
#
#   CLIENT MANAGEMENT
#
#   --------------------------------



@app.route("/client_management")
def client_management():
    spa_id = get_current_spa_id()
    search = request.args.get("search", "").strip()
    today = get_spa_today()

    conn = get_db_connection()
    cur = conn.cursor()

    rows = []

    if search:
        cur.execute("""
            SELECT
                c.client_id,
                c.first_name,
                c.last_name,
                c.phone,
                c.email,
                c.birth_date,

                (
                    SELECT MAX(a1.appointment_date)
                    FROM appointments a1
                    WHERE a1.client_id = c.client_id
                      AND a1.spa_id = c.spa_id
                      AND a1.appointment_date <= %s
                ) AS last_visit_date,

                (
                    SELECT MIN(a2.appointment_date)
                    FROM appointments a2
                    WHERE a2.client_id = c.client_id
                      AND a2.spa_id = c.spa_id
                      AND a2.appointment_date >= %s
                ) AS next_visit_date

            FROM clients c
            WHERE c.spa_id = %s
              AND (
                   LOWER(c.first_name) LIKE %s
                   OR LOWER(c.last_name) LIKE %s
                   OR c.phone LIKE %s
              )
            ORDER BY c.last_name, c.first_name
        """, (
            today,
            today,
            spa_id,
            f"%{search.lower()}%",
            f"%{search.lower()}%",
            f"%{search}%"
        ))

        rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "client_management.html",
        rows=rows,
        search=search
    )





#  --------------------------------------
#
#  SCHEDULE APPOINTMENT START
#
#
#  -----------------------------------

@app.route("/schedule_appointment_start", methods=["GET", "POST"])
def schedule_appointment_start():
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    clients = []

    selected_date = request.args.get("selected_date") \
        or request.form.get("selected_date") \
        or ""

    last_name = ""
    birth_date = ""

    if request.method == "POST":
        last_name = request.form.get("last_name", "").strip()
        birth_date = request.form.get("birth_date", "").strip()

        query = """
            SELECT
                client_id,
                first_name,
                last_name,
                birth_date,
                phone
            FROM clients
            WHERE spa_id = %s
        """
        params = [spa_id]

        if last_name:
            query += " AND last_name ILIKE %s"
            params.append(f"%{last_name}%")

        if birth_date:
            query += " AND birth_date = %s"
            params.append(birth_date)

        query += " ORDER BY last_name, first_name"

        if last_name or birth_date:
            cur.execute(query, tuple(params))
            clients = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "schedule_appointment_start.html",
        clients=clients,
        selected_date=selected_date,
        last_name=last_name,
        birth_date=birth_date
    )









#  ------------------------------------------
#      INCOME HOME PAGE
#
# ROUTE: INCOME
# URL: /income
# SECTION: INCOME HOME PAGE
#  ------------------------------------------

@app.route("/income")
def income_home():
    conn = get_db_connection()
    cur = conn.cursor()

    # summary totals
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM income")
    total_income = cur.fetchone()[0] or 0

    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses")
    total_expenses = cur.fetchone()[0] or 0

    net_total = total_income - total_expenses

    # income list
    cur.execute("""
        SELECT
            i.income_id,
            i.income_date,
            i.client_id,
            c.first_name,
            c.last_name,
            i.total_amount,
            i.payment_method
        FROM income i
        LEFT JOIN clients c
            ON i.client_id = c.client_id
        ORDER BY i.income_date DESC, i.income_id DESC
    """)
    income_records = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "income_home.html",
        income_records=income_records,
        total_income=total_income,
        total_expenses=total_expenses,
        net_total=net_total
    )








#  ------------------------------------------
#           
#           CLIENT FORMS 
#
#  ------------------------------------------


@app.route("/client_forms/<int:client_id>", methods=["GET", "POST"])
def client_forms(client_id):
    spa_id = get_current_spa_id()
    appointment_id = request.args.get("appointment_id") or request.form.get("appointment_id")
    selected_date = request.args.get("date") or request.form.get("date")

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        form_type_id = request.form.get("form_type_id")
        date_given = request.form.get("date_given") or None
        date_signed = request.form.get("date_signed") or None
        form_given = "form_given" in request.form
        form_signed = "form_signed" in request.form
        notes = request.form.get("notes", "")

        cur.execute("""
            INSERT INTO client_forms_log (
                spa_id,
                client_id,
                appointment_id,
                form_type_id,
                date_given,
                date_signed,
                form_given,
                form_signed,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            spa_id,
            client_id,
            appointment_id,
            form_type_id,
            date_given,
            date_signed,
            form_given,
            form_signed,
            notes
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Client form log saved successfully.", "success")

        return redirect(
            url_for(
                "client_forms",
                client_id=client_id,
                appointment_id=appointment_id,
                date=selected_date
            )
        )

    cur.execute("""
        SELECT form_type_id, form_name
        FROM form_types
        WHERE spa_id = %s
          AND active = TRUE
        ORDER BY form_name
    """, (spa_id,))
    form_types = cur.fetchall()

    cur.execute("""
        SELECT client_id, first_name, last_name
        FROM clients
        WHERE client_id = %s
          AND spa_id = %s
    """, (client_id, spa_id))
    client = cur.fetchone()

    cur.execute("""
        SELECT
            cfl.client_form_log_id,
            ft.form_name,
            cfl.date_given,
            cfl.date_signed,
            cfl.form_given,
            cfl.form_signed,
            cfl.notes
        FROM client_forms_log cfl
        JOIN form_types ft
            ON cfl.form_type_id = ft.form_type_id
        WHERE cfl.client_id = %s
          AND cfl.spa_id = %s
        ORDER BY cfl.created_at DESC
    """, (client_id, spa_id))
    form_history = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "client_forms.html",
        client=client,
        form_types=form_types,
        form_history=form_history,
        appointment_id=appointment_id,
        selected_date=selected_date
    )








#  ------------------------------------------
#      GIFT CERTIFICATES
#
#
#  ------------------------------------------

@app.route("/gift_certificates")
def gift_certificates_home():
    spa_id = get_current_spa_id()

    certificate_search = request.args.get("certificate_search", "").strip()
    sort_by = request.args.get("sort_by", "date_desc")
    filter_by = request.args.get("filter", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    where_clauses = ["gc.spa_id = %s"]
    params = [spa_id]

    if certificate_search:
        where_clauses.append("gc.certificate_number ILIKE %s")
        params.append(f"%{certificate_search}%")

    if filter_by == "expiring_soon":
        where_clauses.append("gc.expires_date IS NOT NULL")
        where_clauses.append("gc.expires_date >= CURRENT_DATE")
        where_clauses.append("gc.expires_date <= CURRENT_DATE + INTERVAL '60 days'")
        where_clauses.append("gcs.status_name IN ('Active', 'Printed')")
        where_clauses.append("gc.remaining_balance > 0")

    where_sql = "WHERE " + " AND ".join(where_clauses)

    if sort_by == "date_asc":
        order_sql = "ORDER BY gc.date_issued ASC, gc.gift_cert_id ASC"
    elif sort_by == "cert_asc":
        order_sql = "ORDER BY gc.certificate_number ASC"
    elif sort_by == "cert_desc":
        order_sql = "ORDER BY gc.certificate_number DESC"
    else:
        order_sql = "ORDER BY gc.date_issued DESC, gc.gift_cert_id DESC"

    query = f"""
        SELECT
            gc.gift_cert_id,
            gc.certificate_number,
            gc.date_issued,
            gc.expires_date,
            gc.original_value,
            gc.amount_paid,
            gc.remaining_balance,
            gc.purchased_by_first_name,
            gc.purchased_by_last_name,
            gc.recipient_name,
            gcs.status_name,
            gc.notes
        FROM gift_certificates gc
        LEFT JOIN gift_certificate_statuses gcs
            ON gc.gift_certificate_status_id = gcs.gift_certificate_status_id
        {where_sql}
        {order_sql}
    """

    cur.execute(query, params)
    gift_certificates = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "gift_certificates_home.html",
        gift_certificates=gift_certificates,
        certificate_search=certificate_search,
        sort_by=sort_by,
        filter_by=filter_by
    )






#  ------------------------------------------
#      ADD GIFT CERTIFICATE
#  ------------------------------------------

@app.route("/add_gift_certificate", methods=["GET", "POST"])
def add_gift_certificate():
    conn = get_db_connection() 
    cur = conn.cursor() 

    if request.method == "POST":
        certificate_number = request.form.get("certificate_number")
        date_issued = request.form.get("date_issued") or None
        expires_date = request.form.get("expires_date") or None
        original_value = request.form.get("original_value") or None
        amount_paid = request.form.get("amount_paid") or None
        remaining_balance = request.form.get("remaining_balance") or None
        purchased_by_first_name = request.form.get("purchased_by_first_name") or None
        purchased_by_last_name = request.form.get("purchased_by_last_name") or None
        purchaser_phone = request.form.get("purchaser_phone") or None
        purchaser_email = request.form.get("purchaser_email") or None
        recipient_name = request.form.get("recipient_name") or None
        notes = request.form.get("notes") or None

        gift_certificate_status_id = 5

        if not certificate_number:
            flash("Certificate number is required.", "danger")
            return redirect(url_for("add_gift_certificate"))

        cur.execute("""
            INSERT INTO gift_certificates (
                certificate_number,
                date_issued,
                expires_date,
                original_value,
                amount_paid,
                remaining_balance,
                purchased_by_first_name,
                purchased_by_last_name,
                purchaser_phone,
                purchaser_email,
                recipient_name,
                notes,
                gift_certificate_status_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            certificate_number,
            date_issued,
            expires_date,
            original_value,
            amount_paid,
            remaining_balance,
            purchased_by_first_name,
            purchased_by_last_name,
            purchaser_phone,
            purchaser_email,
            recipient_name,
            notes,
            gift_certificate_status_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Gift certificate added to inventory.", "success")
        return redirect(url_for("gift_certificates_home"))

    # GET
    cur.close()
    conn.close()
    return render_template("add_gift_certificate.html")


#  ------------------------------------------
#         EDIT GIFT CERTIFICATE
#  ------------------------------------------

@app.route("/edit_gift_certificate/<int:certificate_id>", methods=["GET", "POST"])
def edit_gift_certificate(certificate_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        certificate_number = request.form.get("certificate_number")
        date_issued = request.form.get("date_issued") or None
        expires_date = request.form.get("expires_date") or None
        original_value = request.form.get("original_value") or None
        amount_paid = request.form.get("amount_paid") or None
        remaining_balance = request.form.get("remaining_balance") or None
        purchased_by_first_name = request.form.get("purchased_by_first_name") or None
        purchased_by_last_name = request.form.get("purchased_by_last_name") or None
        recipient_name = request.form.get("recipient_name") or None
        gift_certificate_status_id = request.form.get("gift_certificate_status_id") or None
        notes = request.form.get("notes") or None

        cur.execute("""
            UPDATE gift_certificates
            SET certificate_number = %s,
                date_issued = %s,
                expires_date = %s,
                original_value = %s,
                amount_paid = %s,
                remaining_balance = %s,
                purchased_by_first_name = %s,
                purchased_by_last_name = %s,
                recipient_name = %s,
                gift_certificate_status_id = %s,
                notes = %s
            WHERE gift_cert_id = %s
        """, (
            certificate_number,
            date_issued,
            expires_date,
            original_value,
            amount_paid,
            remaining_balance,
            purchased_by_first_name,
            purchased_by_last_name,
            recipient_name,
            gift_certificate_status_id,
            notes,
            certificate_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("gift_certificates_home"))

    cur.execute("""
        SELECT
            gift_cert_id,
            certificate_number,
            date_issued,
            expires_date,
            original_value,
            amount_paid,
            remaining_balance,
            purchased_by_first_name,
            purchased_by_last_name,
            recipient_name,
            gift_certificate_status_id,
            notes
        FROM gift_certificates
        WHERE gift_cert_id = %s
    """, (certificate_id,))
    gift_certificate = cur.fetchone()

    cur.execute("""
        SELECT gift_certificate_status_id, status_name
        FROM gift_certificate_statuses
        ORDER BY gift_certificate_status_id
    """)
    statuses = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "edit_gift_certificate.html",
        gift_certificate=gift_certificate,
        statuses=statuses
    )


#  ------------------------------------------
#       REDEEM GIFT CERTIFICATE
#  ------------------------------------------

@app.route("/redeem_gift_certificate/<int:certificate_id>", methods=["GET", "POST"])
def redeem_gift_certificate(certificate_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        redeemed_on = request.form.get("redeemed_on") or None
        redeemed_by = request.form.get("redeemed_by") or None

        cur.execute("""
            SELECT gift_certificate_status_id
            FROM gift_certificate_statuses
            WHERE status_name = %s
            LIMIT 1
        """, ("Redeemed",))
        redeemed_row = cur.fetchone()

        if not redeemed_row:
            flash("Redeemed status not found.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("gift_certificates_home"))

        redeemed_status_id = redeemed_row[0]

        cur.execute("""
            UPDATE gift_certificates
            SET redeemed_on = %s,
                redeemed_by = %s,
                remaining_balance = 0,
                gift_certificate_status_id = %s
            WHERE gift_cert_id = %s
        """, (
            redeemed_on,
            redeemed_by,
            redeemed_status_id,
            certificate_id
        ))

        conn.commit()
        flash("Gift certificate redeemed successfully.", "success")
        cur.close()
        conn.close()

        return redirect(url_for("gift_certificates_home"))

    cur.execute("""
        SELECT
            gc.gift_cert_id,
            gc.certificate_number,
            gc.original_value,
            gc.remaining_balance,
            gc.purchased_by_first_name,
            gc.purchased_by_last_name,
            gc.recipient_name,
            gcs.status_name
        FROM gift_certificates gc
        LEFT JOIN gift_certificate_statuses gcs
            ON gc.gift_certificate_status_id = gcs.gift_certificate_status_id
        WHERE gc.gift_cert_id = %s
    """, (certificate_id,))
    gift_certificate = cur.fetchone()

    cur.close()
    conn.close()

    return render_template(
        "redeem_gift_certificate.html",
        gift_certificate=gift_certificate
    )




                
#  ------------------------------------------
#      CLIENTS   HOME PAGE
#  ------------------------------------------

from datetime import date

@app.route("/clients")
def clients_home():
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()
    current_month = today.month
    current_day = today.day
    current_year = today.year

    months_to_show = [current_month]

    if current_day >= 15:
        next_month = 1 if current_month == 12 else current_month + 1
        months_to_show.append(next_month)

    cur.execute("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.birth_date,
            EXTRACT(MONTH FROM c.birth_date) AS birth_month,
            cbo.birthday_offer_id,
            cbo.birthday_year,
            COALESCE(cbo.offer_sent, FALSE) AS offer_sent,
            cbo.offer_sent_date,
            cbo.acknowledged_by,
            cbo.notes
        FROM clients c
        LEFT JOIN client_birthday_offers cbo
            ON c.client_id = cbo.client_id
            AND cbo.birthday_year = %s
        WHERE c.birth_date IS NOT NULL
          AND EXTRACT(MONTH FROM c.birth_date) = ANY(%s)
          AND COALESCE(cbo.offer_sent, FALSE) = FALSE
        ORDER BY
            EXTRACT(MONTH FROM c.birth_date),
            EXTRACT(DAY FROM c.birth_date),
            c.last_name,
            c.first_name
    """, (current_year, months_to_show))

    birthday_clients = cur.fetchall()

    print("birthday_clients =", birthday_clients)

    # keep your normal clients query here too
    cur.execute("""
        SELECT client_id, first_name, last_name, phone, email, birth_date
        FROM clients
        ORDER BY last_name, first_name
    """)
    clients = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "clients_home.html",
        clients=clients,
        birthday_clients=birthday_clients
    )




#  ------------------------------------------
#          
#        FULL EDIT CLIENT   
#  
#  
#  ------------------------------------------

@app.route("/edit-client-full/<int:client_id>", methods=["GET", "POST"])
def edit_client_full(client_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        # ----- clients table fields -----
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        birth_date = request.form.get("birth_date") or None
        address = request.form.get("address")
        city = request.form.get("city")
        state = request.form.get("state")
        zip_code = request.form.get("zip")
        emergency_contact_name = request.form.get("emergency_contact_name")
        emergency_contact_phone = request.form.get("emergency_contact_phone")
        referred_by = request.form.get("referred_by")
        notes_one = request.form.get("notes_one")
        notes_two = request.form.get("notes_two")
        notes_three = request.form.get("notes_three")
        active_client = True if request.form.get("active_client") == "on" else False

        # ----- client_health_profile fields -----
        sex = request.form.get("sex")
        skin_type_id = request.form.get("skin_type_id") or None
        fitzpatrick_id = request.form.get("fitzpatrick_id") or None
        skin_concerns = request.form.get("skin_concerns")
        skin_conditions = request.form.get("skin_conditions")
        allergies = request.form.get("allergies")
        medications = request.form.get("medications")
        current_medical_conditions = request.form.get("current_medical_conditions")
        past_medical_treatments = request.form.get("past_medical_treatments")

        recent_injections = parse_bool(request.form.get("recent_injections"))
        recent_laser = parse_bool(request.form.get("recent_laser"))
        pregnant = parse_bool(request.form.get("pregnant"))
        nursing = parse_bool(request.form.get("nursing"))
        using_retinol = parse_bool(request.form.get("using_retinol"))
        using_accutane = parse_bool(request.form.get("using_accutane"))


        sun_exposure_level = request.form.get("sun_exposure_level")
        last_facial_date = request.form.get("last_facial_date") or None
        health_notes1 = request.form.get("health_notes1")
        health_notes2 = request.form.get("health_notes2")
        health_notes3 = request.form.get("health_notes3")

        # ----- update clients -----
        cur.execute("""
            UPDATE clients
            SET
                first_name = %s,
                last_name = %s,
                phone = %s,
                email = %s,
                birth_date = %s,
                address = %s,
                city = %s,
                state = %s,
                zip = %s,
                emergency_contact_name = %s,
                emergency_contact_phone = %s,
                referred_by = %s,
                notes_one = %s,
                notes_two = %s,
                notes_three = %s,
                active_client = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE client_id = %s
        """, (
            first_name, last_name, phone, email, birth_date,
            address, city, state, zip_code,
            emergency_contact_name, emergency_contact_phone,
            referred_by, notes_one, notes_two, notes_three,
            active_client, client_id
        ))

        # ----- check whether health profile exists -----
        cur.execute("""
            SELECT health_profile_id
            FROM client_health_profile
            WHERE client_id = %s
        """, (client_id,))
        existing_health = cur.fetchone()

        if existing_health:
            # update existing health profile
            cur.execute("""
                UPDATE client_health_profile
                SET
                    sex = %s,
                    skin_type_id = %s,
                    fitzpatrick_id = %s,
                    skin_concerns = %s,
                    skin_conditions = %s,
                    allergies = %s,
                    medications = %s,
                    current_medical_conditions = %s,
                    past_medical_treatments = %s,
                    recent_injections = %s,
                    recent_laser = %s,
                    pregnant = %s,
                    nursing = %s,
                    using_retinol = %s,
                    using_accutane = %s,
                    sun_exposure_level = %s,
                    last_facial_date = %s,
                    notes1 = %s,
                    notes2 = %s,
                    notes3 = %s,
                    last_updated = CURRENT_DATE
                WHERE client_id = %s
            """, (
                sex, skin_type_id, fitzpatrick_id, skin_concerns, skin_conditions,
                allergies, medications, current_medical_conditions, past_medical_treatments,
                recent_injections, recent_laser, pregnant, nursing,
                using_retinol, using_accutane, sun_exposure_level,
                last_facial_date, health_notes1, health_notes2, health_notes3,
                client_id
            ))
        else:
            # insert new health profile
            cur.execute("""
                INSERT INTO client_health_profile (
                    client_id,
                    sex,
                    skin_type_id,
                    fitzpatrick_id,
                    skin_concerns,
                    skin_conditions,
                    allergies,
                    medications,
                    current_medical_conditions,
                    past_medical_treatments,
                    recent_injections,
                    recent_laser,
                    pregnant,
                    nursing,
                    using_retinol,
                    using_accutane,
                    sun_exposure_level,
                    last_facial_date,
                    notes1,
                    notes2,
                    notes3,
                    last_updated,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, CURRENT_TIMESTAMP)
            """, (
                client_id,
                sex,
                skin_type_id,
                fitzpatrick_id,
                skin_concerns,
                skin_conditions,
                allergies,
                medications,
                current_medical_conditions,
                past_medical_treatments,
                recent_injections,
                recent_laser,
                pregnant,
                nursing,
                using_retinol,
                using_accutane,
                sun_exposure_level,
                last_facial_date,
                health_notes1,
                health_notes2,
                health_notes3
            ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Client full record updated successfully.", "success")
        return redirect(url_for("clients_home"))

    # ---------------- GET request ----------------

    # get client record
    cur.execute("""
        SELECT
            client_id,
            first_name,
            last_name,
            phone,
            email,
            birth_date,
            address,
            city,
            state,
            zip,
            emergency_contact_name,
            emergency_contact_phone,
            referred_by,
            notes_one,
            notes_two,
            notes_three,
            active_client,
            created_at,
            updated_at
        FROM clients
        WHERE client_id = %s
    """, (client_id,))
    client = cur.fetchone()

    # get health profile
    cur.execute("""
        SELECT
            health_profile_id,
            client_id,
            sex,
            skin_type_id,
            fitzpatrick_id,
            skin_concerns,
            skin_conditions,
            allergies,
            medications,
            current_medical_conditions,
            past_medical_treatments,
            recent_injections,
            recent_laser,
            pregnant,
            nursing,
            using_retinol,
            using_accutane,
            sun_exposure_level,
            last_facial_date,
            notes1,
            notes2,
            notes3,
            last_updated,
            created_at
        FROM client_health_profile
        WHERE client_id = %s
    """, (client_id,))
    health = cur.fetchone()

    # dropdown values
    cur.execute("SELECT sex_type_id, sex_type FROM sex ORDER BY sex_type")
    sex_options = cur.fetchall()

    cur.execute("SELECT skin_type_id, skin_type_name FROM skin_types ORDER BY skin_type_name")
    skin_types = cur.fetchall()

    cur.execute("SELECT fitzpatrick_id, fitzpatrick_level FROM fitzpatrick_types ORDER BY fitzpatrick_id")
    fitzpatrick_types = cur.fetchall()

    cur.execute("SELECT referral_source_id, referral_source_name FROM referral_sources ORDER BY referral_source_name")
    referral_sources = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "edit_client_full.html",
        client=client,
        health=health,
        sex_options=sex_options, 
        skin_types=skin_types,
        fitzpatrick_types=fitzpatrick_types,
        referral_sources=referral_sources
    )





#  ------------------------------------------
#           BIRTHDAYS            
#
#
#  
#  ------------------------------------------



#  ------------------------------------------
#           BIRTHDAY OFFERS
#  ------------------------------------------

@app.route("/birthday-offers")
def birthday_offers_home():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()
    end_date = today + timedelta(days=30)
    current_year = today.year

    cur.execute("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.phone,
            c.email,
            c.birth_date,
            bo.birthday_offer_id,
            bo.offer_sent,
            bo.offer_sent_date,
            bo.acknowledged_by,
            bo.notes
        FROM clients c
        LEFT JOIN client_birthday_offers bo
            ON c.client_id = bo.client_id
           AND bo.birthday_year = %s
        WHERE c.birth_date IS NOT NULL
        ORDER BY
            CASE
                WHEN TO_DATE(
                    EXTRACT(MONTH FROM c.birth_date)::text || '-' ||
                    EXTRACT(DAY FROM c.birth_date)::text || '-' ||
                    %s::text,
                    'MM-DD-YYYY'
                ) >= %s
                THEN TO_DATE(
                    EXTRACT(MONTH FROM c.birth_date)::text || '-' ||
                    EXTRACT(DAY FROM c.birth_date)::text || '-' ||
                    %s::text,
                    'MM-DD-YYYY'
                )
                ELSE TO_DATE(
                    EXTRACT(MONTH FROM c.birth_date)::text || '-' ||
                    EXTRACT(DAY FROM c.birth_date)::text || '-' ||
                    (%s + 1)::text,
                    'MM-DD-YYYY'
                )
            END
    """, (current_year, current_year, today, current_year, current_year))

    all_birthdays = cur.fetchall()

    upcoming_birthdays = []

    for row in all_birthdays:
        birth_date = row[5]
        if not birth_date:
            continue

        this_year_bday = date(today.year, birth_date.month, birth_date.day)

        if this_year_bday < today:
            next_birthday = date(today.year + 1, birth_date.month, birth_date.day)
        else:
            next_birthday = this_year_bday

        if today <= next_birthday <= end_date:
            days_until = (next_birthday - today).days
            upcoming_birthdays.append({
                "client_id": row[0],
                "first_name": row[1],
                "last_name": row[2],
                "phone": row[3],
                "email": row[4],
                "birth_date": row[5],
                "next_birthday": next_birthday,
                "birthday_offer_id": row[6],
                "offer_sent": row[7],
                "offer_sent_date": row[8],
                "acknowledged_by": row[9],
                "notes": row[10],
                "days_until": days_until
            })

    cur.close()
    conn.close()

    return render_template(
        "birthday_offers_home.html",
        upcoming_birthdays=upcoming_birthdays
    )
        
#  ------------------------------------------
#        BIRTHDAY OFFERS MARK SENT
#
#  ------------------------------------------

@app.route("/birthday-offers/mark-sent/<int:client_id>", methods=["POST"])
def mark_birthday_offer_sent(client_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    current_year = date.today().year

    cur.execute("""
        SELECT birthday_offer_id
        FROM client_birthday_offers
        WHERE client_id = %s AND birthday_year = %s
    """, (client_id, current_year))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE client_birthday_offers
            SET offer_sent = TRUE,
                offer_sent_date = CURRENT_DATE,
                acknowledged_by = %s
            WHERE client_id = %s AND birthday_year = %s
        """, ("Staff", client_id, current_year))
    else:
        cur.execute("""
            INSERT INTO client_birthday_offers (
                client_id,
                birthday_year,
                offer_sent,
                offer_sent_date,
                acknowledged_by
            )
            VALUES (%s, %s, TRUE, CURRENT_DATE, %s)
        """, (client_id, current_year, "Staff"))

    conn.commit()
    cur.close()
    conn.close()

    flash("Birthday offer marked as sent.", "success")
    return redirect(url_for("birthday_offers_home"))







#  ------------------------------------------
#      EMPLOYEES  
#
#
#
#  ------------------------------------------








#  ------------------------------------------
#      EMPLOYEES   HOME PAGE
#  ------------------------------------------



@app.route("/employees")
def employees_home():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            employee_id,
            first_name,
            last_name,
            phone,
            email,
            job_title,
            hire_date,
            termination_date,
            status,
            birthday,
            esthetician_license_number,
            license_expiration_date,
            pay_type,
            pay_rate,
            created_at
        FROM employees
        WHERE spa_id = %s
        ORDER BY last_name ASC, first_name ASC
    """, (spa_id,))
    employees = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*)
        FROM employees
        WHERE spa_id = %s
    """, (spa_id,))
    total_employees = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM employees
        WHERE spa_id = %s
          AND status = 'Active'
    """, (spa_id,))
    active_employees = cur.fetchone()[0]

    cur.close()
    conn.close()

    return render_template(
        "employees_home.html",
        employees=employees,
        total_employees=total_employees,
        active_employees=active_employees
    )





#   ---------------------------------------
#
#   EMPLOYEE PAY SUMMARY
#
#
#   ---------------------------------------



from datetime import date

@app.route("/employee_pay_summary")
def employee_pay_summary():
    spa_id = get_current_spa_id()

    today = date.today()
    first_day = today.replace(day=1)

    start_date = request.args.get("start_date") or first_day.strftime("%Y-%m-%d")
    end_date = request.args.get("end_date") or today.strftime("%Y-%m-%d")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            e.employee_id,
            e.first_name || ' ' || e.last_name AS employee_name,
            COUNT(i.income_id) AS sessions_worked,
            COALESCE(SUM(i.service_amount), 0.00) AS service_sales,
            COALESCE(SUM(i.retail_amount), 0.00) AS retail_sales,
            COALESCE(SUM(i.tip_amount), 0.00) AS tips_earned,
            COALESCE(SUM(i.total_amount), 0.00) AS gross_collected
        FROM employees e
        LEFT JOIN income i
            ON e.employee_id = i.employee_id
           AND i.spa_id = e.spa_id
           AND i.income_date BETWEEN %s AND %s
        WHERE e.spa_id = %s
        GROUP BY e.employee_id, e.first_name, e.last_name
        ORDER BY e.last_name, e.first_name
    """, (start_date, end_date, spa_id))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "employee_pay_summary.html",
        rows=rows,
        start_date=start_date,
        end_date=end_date
    )






#   ----------------------------------------
#
#   ADD  EMPLOYEE COMPENSATION
#
#
#   ---------------------------------------



@app.route("/add_employee_compensation", methods=["GET", "POST"])
def add_employee_compensation():
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    # Load employees
    cur.execute("""
        SELECT employee_id, first_name || ' ' || last_name AS employee_name
        FROM employees
        WHERE spa_id = %s
        ORDER BY first_name, last_name
    """, (spa_id,))
    employees = cur.fetchall()

    # Load compensation types for all 4 dropdowns
    cur.execute("""
        SELECT compensation_type_id, compensation_type_name
        FROM compensation_types
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY compensation_type_name
    """, (spa_id,))
    compensation_types = cur.fetchall()

    if request.method == "POST":
        payment_date = request.form.get("payment_date")
        employee_id = request.form.get("employee_id") or None
        notes = (request.form.get("notes") or "").strip()

        # Gather up to 4 compensation lines
        detail_lines = []

        for i in range(1, 5):
            comp_type_id = request.form.get(f"comp_type_{i}") or None
            amount_raw = request.form.get(f"amount_{i}") or "0"

            try:
                amount = float(amount_raw)
            except ValueError:
                amount = 0

            if comp_type_id and amount > 0:
                detail_lines.append((comp_type_id, amount))

        # Validation
        if not payment_date:
            flash("Payment date is required.", "error")
        elif not employee_id:
            flash("Employee is required.", "error")
        elif not detail_lines:
            flash("Enter at least one compensation line with type and amount.", "error")
        else:
            # Insert header
            cur.execute("""
                INSERT INTO employee_compensation (
                    spa_id,
                    employee_id,
                    compensation_date,
                    notes
                )
                VALUES (%s, %s, %s, %s)
                RETURNING compensation_id
            """, (
                spa_id,
                employee_id,
                payment_date,
                notes
            ))
            compensation_id = cur.fetchone()[0]

            # Insert detail lines
            for comp_type_id, amount in detail_lines:
                cur.execute("""
                    INSERT INTO employee_compensation_lines (
                        compensation_id,
                        compensation_type_id,
                        amount
                    )
                    VALUES (%s, %s, %s)
                """, (
                    compensation_id,
                    comp_type_id,
                    amount
                ))

            conn.commit()
            cur.close()
            conn.close()

            flash("Compensation saved successfully.", "success")
            return redirect(url_for("employee_compensation_report"))

    cur.close()
    conn.close()

    return render_template(
        "add_employee_compensation.html",
        employees=employees,
        compensation_types=compensation_types
    )





#   -------------------------------
#  
#     EMPLOYEE  ADMIN
#   
#   -------------------------------

@app.route("/employee_admin")
def employee_admin():
    return render_template("employee_admin.html")









#   ------------------------------------------
#
#   EMPLOYEE COMPENSATION HELPER
# 
#     HELPER         HELPER        HELPER
#   -----------------------------------------

def get_employee_compensation_history_data(spa_id, employee_id="", start_date="", end_date=""):
    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT
            ec.compensation_id,
            ec.compensation_date,
            e.first_name,
            e.last_name,
            ct.compensation_type_name,
            ecl.amount,
            ec.notes,
            ec.created_at
        FROM employee_compensation ec
        JOIN employees e
            ON ec.employee_id = e.employee_id
        JOIN employee_compensation_lines ecl
            ON ec.compensation_id = ecl.compensation_id
        LEFT JOIN compensation_types ct
            ON ecl.compensation_type_id = ct.compensation_type_id
        WHERE ec.spa_id = %s
          AND ec.compensation_date BETWEEN %s AND %s
    """
    params = [spa_id, start_date, end_date]

    if employee_id:
        query += " AND ec.employee_id = %s"
        params.append(employee_id)

    query += """
        ORDER BY ec.compensation_date DESC,
                 ec.compensation_id DESC,
                 ct.compensation_type_name ASC
    """

    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows











#   -------------------------------
#  
#  COMPENSATION TYPES
#   
#   -------------------------------


@app.route("/compensation_types")
def compensation_types_report():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            compensation_type_id,
            compensation_type_name,
            is_active
        FROM compensation_types
        WHERE spa_id = %s
        ORDER BY compensation_type_name
    """, (spa_id,))
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "compensation_types_report.html",
        rows=rows
    )




#   -------------------------------
#  
#   ADD   COMPENSATION TYPE
#   
#   -------------------------------



@app.route("/add_compensation_type", methods=["GET", "POST"])
def add_compensation_type():
    spa_id = get_current_spa_id()

    if request.method == "POST":
        compensation_type_name = (request.form.get("compensation_type_name") or "").strip()

        if not compensation_type_name:
            flash("Compensation type name is required.", "error")
        else:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT 1
                FROM compensation_types
                WHERE spa_id = %s
                  AND LOWER(compensation_type_name) = LOWER(%s)
            """, (spa_id, compensation_type_name))
            existing = cur.fetchone()

            if existing:
                cur.close()
                conn.close()
                flash("That compensation type already exists.", "warning")
            else:
                cur.execute("""
                    INSERT INTO compensation_types (
                        spa_id,
                        compensation_type_name,
                        is_active
                    )
                    VALUES (%s, %s, TRUE)
                """, (spa_id, compensation_type_name))

                conn.commit()
                cur.close()
                conn.close()

                flash("Compensation type added successfully.", "success")
                return redirect(url_for("compensation_types_report"))

    return render_template("add_compensation_type.html")





#   -------------------------------
#  
#    EDIT COMPENSATION  TYPE
#   
#   -------------------------------


@app.route("/edit_compensation_type/<int:compensation_type_id>", methods=["GET", "POST"])
def edit_compensation_type(compensation_type_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        compensation_type_name = (request.form.get("compensation_type_name") or "").strip()

        if not compensation_type_name:
            flash("Compensation type name is required.", "error")
        else:
            cur.execute("""
                SELECT 1
                FROM compensation_types
                WHERE spa_id = %s
                  AND LOWER(compensation_type_name) = LOWER(%s)
                  AND compensation_type_id <> %s
            """, (spa_id, compensation_type_name, compensation_type_id))
            existing = cur.fetchone()

            if existing:
                flash("That compensation type already exists.", "warning")
            else:
                cur.execute("""
                    UPDATE compensation_types
                    SET compensation_type_name = %s
                    WHERE compensation_type_id = %s
                      AND spa_id = %s
                """, (compensation_type_name, compensation_type_id, spa_id))

                conn.commit()
                cur.close()
                conn.close()

                flash("Compensation type updated successfully.", "success")
                return redirect(url_for("compensation_types_report"))

    cur.execute("""
        SELECT
            compensation_type_id,
            compensation_type_name,
            is_active
        FROM compensation_types
        WHERE compensation_type_id = %s
          AND spa_id = %s
    """, (compensation_type_id, spa_id))
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        flash("Compensation type not found.", "error")
        return redirect(url_for("compensation_types_report"))

    return render_template(
        "edit_compensation_type.html",
        row=row
    )







#   -------------------------------
#  
#     TOGGLE  COMPENSATION TYPE
#   
#   -------------------------------


@app.route("/toggle_compensation_type/<int:compensation_type_id>", methods=["POST"])
def toggle_compensation_type(compensation_type_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE compensation_types
        SET is_active = NOT is_active
        WHERE compensation_type_id = %s
          AND spa_id = %s
    """, (compensation_type_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Compensation type status updated.", "success")
    return redirect(url_for("compensation_types_report"))









#   -------------------------------
#
#  EMPLOYEE COMPENSATION REPORT
#
#   -------------------------------



@app.route("/employee_compensation_report")
def employee_compensation_report():
    spa_id = get_current_spa_id()
    today = date.today()
    first_day = today.replace(day=1)

    start_date = request.args.get("start_date") or first_day.strftime("%Y-%m-%d")
    end_date = request.args.get("end_date") or today.strftime("%Y-%m-%d")

    conn = get_db_connection()
    cur = conn.cursor()

    # Total tips earned
    cur.execute("""
        SELECT COALESCE(SUM(tip_amount), 0.00)
        FROM income
        WHERE spa_id = %s
          AND income_date BETWEEN %s AND %s
    """, (spa_id, start_date, end_date))
    tips_earned_total = cur.fetchone()[0]

    # Total compensation paid
    cur.execute("""
        SELECT COALESCE(SUM(ecl.amount), 0.00)
        FROM employee_compensation ec
        JOIN employee_compensation_lines ecl
            ON ec.compensation_id = ecl.compensation_id
        WHERE ec.spa_id = %s
          AND ec.compensation_date BETWEEN %s AND %s
    """, (spa_id, start_date, end_date))
    total_comp_paid = cur.fetchone()[0]

    outstanding_tips = tips_earned_total - total_comp_paid

    # Employee summary
    cur.execute("""
        SELECT
            e.employee_id,
            e.first_name || ' ' || e.last_name AS employee_name,
            COALESCE(inc.tips_earned, 0.00) AS tips_earned,
            COALESCE(comp.total_comp_paid, 0.00) AS total_comp_paid,
            COALESCE(inc.tips_earned, 0.00) - COALESCE(comp.total_comp_paid, 0.00) AS outstanding_balance
        FROM employees e
        LEFT JOIN (
            SELECT
                employee_id,
                COALESCE(SUM(tip_amount), 0.00) AS tips_earned
            FROM income
            WHERE spa_id = %s
              AND income_date BETWEEN %s AND %s
            GROUP BY employee_id
        ) inc ON e.employee_id = inc.employee_id
        LEFT JOIN (
            SELECT
                ec.employee_id,
                COALESCE(SUM(ecl.amount), 0.00) AS total_comp_paid
            FROM employee_compensation ec
            JOIN employee_compensation_lines ecl
                ON ec.compensation_id = ecl.compensation_id
            WHERE ec.spa_id = %s
              AND ec.compensation_date BETWEEN %s AND %s
            GROUP BY ec.employee_id
        ) comp ON e.employee_id = comp.employee_id
        WHERE e.spa_id = %s
        ORDER BY e.last_name, e.first_name
    """, (
        spa_id, start_date, end_date,
        spa_id, start_date, end_date,
        spa_id
    ))
    summary_rows = cur.fetchall()

    # Detailed ledger rows
    cur.execute("""
        SELECT
            ec.compensation_id,
            ec.compensation_date,
            e.first_name || ' ' || e.last_name AS employee_name,
            ct.compensation_type_name,
            ecl.amount,
            COALESCE(ec.notes, '') AS notes
        FROM employee_compensation ec
        JOIN employee_compensation_lines ecl
            ON ec.compensation_id = ecl.compensation_id
        JOIN compensation_types ct
            ON ecl.compensation_type_id = ct.compensation_type_id
        LEFT JOIN employees e
            ON ec.employee_id = e.employee_id
        WHERE ec.spa_id = %s
          AND ec.compensation_date BETWEEN %s AND %s
        ORDER BY ec.compensation_date DESC, ec.compensation_id DESC, ct.compensation_type_name
    """, (spa_id, start_date, end_date))
    ledger_rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "employee_compensation_report.html",
        summary_rows=summary_rows,
        ledger_rows=ledger_rows,
        start_date=start_date,
        end_date=end_date,
        tips_earned_total=tips_earned_total,
        total_comp_paid=total_comp_paid,
        outstanding_tips=outstanding_tips
    )






#   ----------------------------------
#
#     EMPLOYEE COMPENSATION HISTORY
#
#
#   --------------------------------




@app.route("/employee_compensation_history")
def employee_compensation_history():
    spa_id = get_current_spa_id()

    today = date.today()
    first_day = today.replace(day=1)

    employee_id = request.args.get("employee_id", "").strip()
    start_date = request.args.get("start_date", first_day.strftime("%Y-%m-%d")).strip()
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d")).strip()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT employee_id, first_name, last_name
        FROM employees
        WHERE spa_id = %s
        ORDER BY last_name, first_name
    """, (spa_id,))
    employees = cur.fetchall()

    cur.close()
    conn.close()

    rows = get_employee_compensation_history_data(
        spa_id=spa_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date
    )

    total_amount = sum((row[5] or 0) for row in rows)

    return render_template(
        "employee_compensation_history.html",
        employees=employees,
        rows=rows,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
        total_amount=total_amount
    )









#   -----------------------------------------
#       DELETE  EMPLOYEE COMPENSATION HISTORY
#
#    
#
#
#   -----------------------------------------


@app.route("/delete_employee_compensation/<int:compensation_id>", methods=["POST"])
def delete_employee_compensation(compensation_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT compensation_id
        FROM employee_compensation
        WHERE compensation_id = %s
          AND spa_id = %s
    """, (compensation_id, spa_id))
    record = cur.fetchone()

    if not record:
        cur.close()
        conn.close()
        flash("Compensation record not found.", "error")
        return redirect(url_for("employee_compensation_history"))

    cur.execute("""
        DELETE FROM employee_compensation_lines
        WHERE compensation_id = %s
    """, (compensation_id,))

    cur.execute("""
        DELETE FROM employee_compensation
        WHERE compensation_id = %s
          AND spa_id = %s
    """, (compensation_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Full compensation entry deleted successfully.", "success")
    return redirect(url_for("employee_compensation_history"))







#   -----------------------------------------
#       EDIT   EMPLOYEE COMPENSATION HISTORY
#           
#
#
#
#   -----------------------------------------



@app.route("/edit_employee_compensation/<int:compensation_id>", methods=["GET", "POST"])
def edit_employee_compensation(compensation_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    # Load employees
    cur.execute("""
        SELECT employee_id, first_name || ' ' || last_name AS employee_name
        FROM employees
        WHERE spa_id = %s
        ORDER BY first_name, last_name
    """, (spa_id,))
    employees = cur.fetchall()

    # Load active compensation types
    cur.execute("""
        SELECT compensation_type_id, compensation_type_name
        FROM compensation_types
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY compensation_type_name
    """, (spa_id,))
    compensation_types = cur.fetchall()

    if request.method == "POST":
        payment_date = request.form.get("payment_date")
        employee_id = request.form.get("employee_id") or None
        notes = (request.form.get("notes") or "").strip()

        detail_lines = []

        for i in range(1, 5):
            comp_type_id = request.form.get(f"comp_type_{i}") or None
            amount_raw = request.form.get(f"amount_{i}") or "0"

            try:
                amount = float(amount_raw)
            except ValueError:
                amount = 0

            if comp_type_id and amount > 0:
                detail_lines.append((comp_type_id, amount))

        # Validation
        if not payment_date:
            flash("Payment date is required.", "error")
        elif not employee_id:
            flash("Employee is required.", "error")
        elif not detail_lines:
            flash("Enter at least one compensation line with type and amount.", "error")
        else:
            # Update header
            cur.execute("""
                UPDATE employee_compensation
                SET employee_id = %s,
                    compensation_date = %s,
                    notes = %s
                WHERE compensation_id = %s
                  AND spa_id = %s
            """, (
                employee_id,
                payment_date,
                notes,
                compensation_id,
                spa_id
            ))

            # Remove old detail lines
            cur.execute("""
                DELETE FROM employee_compensation_lines
                WHERE compensation_id = %s
            """, (compensation_id,))

            # Insert updated detail lines
            for comp_type_id, amount in detail_lines:
                cur.execute("""
                    INSERT INTO employee_compensation_lines (
                        compensation_id,
                        compensation_type_id,
                        amount
                    )
                    VALUES (%s, %s, %s)
                """, (
                    compensation_id,
                    comp_type_id,
                    amount
                ))

            conn.commit()
            cur.close()
            conn.close()

            flash("Compensation updated successfully.", "success")
            return redirect(url_for("employee_compensation_history"))

    # Load header record
    cur.execute("""
        SELECT compensation_id, employee_id, compensation_date, notes
        FROM employee_compensation
        WHERE compensation_id = %s
          AND spa_id = %s
    """, (compensation_id, spa_id))
    compensation = cur.fetchone()

    # Load detail lines
    cur.execute("""
        SELECT compensation_type_id, amount
        FROM employee_compensation_lines
        WHERE compensation_id = %s
        ORDER BY compensation_type_id
    """, (compensation_id,))
    existing_lines = cur.fetchall()

    cur.close()
    conn.close()

    # Pad to 4 rows for form display
    detail_rows = list(existing_lines)
    while len(detail_rows) < 4:
        detail_rows.append((None, ""))

    return render_template(
        "edit_employee_compensation.html",
        compensation=compensation,
        employees=employees,
        compensation_types=compensation_types,
        detail_rows=detail_rows
    )














#   -----------------------------------------
#       EXPORT EMPLOYEE COMPENSATION HISTORY
#
#     EXPORT TO CSV   EPXORT
#
#
#   -----------------------------------------



@app.route("/export_employee_compensation_history_csv")
def export_employee_compensation_history_csv():
    spa_id = get_current_spa_id()

    today = date.today()
    first_day = today.replace(day=1)

    employee_id = request.args.get("employee_id", "").strip()
    start_date = request.args.get("start_date", first_day.strftime("%Y-%m-%d")).strip()
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d")).strip()

    rows = get_employee_compensation_history_data(
        spa_id=spa_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Compensation ID",
        "Compensation Date",
        "Employee First Name",
        "Employee Last Name",
        "Compensation Type",
        "Amount",
        "Notes",
        "Created At"
    ])

    for row in rows:
        writer.writerow([
            row[0],
            row[1].strftime("%Y-%m-%d") if row[1] else "",
            row[2] or "",
            row[3] or "",
            row[4] or "",
            float(row[5] or 0),
            row[6] or "",
            row[7].strftime("%Y-%m-%d %I:%M %p") if row[7] else ""
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=employee_compensation_history.csv"
        }
    )









#   ----------------------------------------
#   EXPORT   EXPORT  EXPORT TO EXCEL
#
#   EXPORT EMPLOYEE COMPENSATION HISTORY
#
#            EXPORT TO EXCEL
#
#   ---------------------------------------



@app.route("/export_employee_compensation_history_excel")
def export_employee_compensation_history_excel():
    spa_id = get_current_spa_id()

    today = date.today()
    first_day = today.replace(day=1)

    employee_id = request.args.get("employee_id", "").strip()
    start_date = request.args.get("start_date", first_day.strftime("%Y-%m-%d")).strip()
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d")).strip()

    rows = get_employee_compensation_history_data(
        spa_id=spa_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Compensation History"

    ws.append([
        "Compensation ID",
        "Compensation Date",
        "Employee First Name",
        "Employee Last Name",
        "Compensation Type",
        "Amount",
        "Notes",
        "Created At"
    ])

    for row in rows:
        ws.append([
            row[0],
            row[1].strftime("%Y-%m-%d") if row[1] else "",
            row[2] or "",
            row[3] or "",
            row[4] or "",
            float(row[5] or 0),
            row[6] or "",
            row[7].strftime("%Y-%m-%d %I:%M %p") if row[7] else ""
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=employee_compensation_history.xlsx"
        }
    )










#  ------------------------------------------
#          ADD EMPLOYEE
#  ------------------------------------------


@app.route("/employees/add", methods=["GET", "POST"])
def add_employee():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        address_line1 = request.form.get("address_line1")
        address_line2 = request.form.get("address_line2")
        city = request.form.get("city")
        state = request.form.get("state")
        zip_code = request.form.get("zip_code")
        phone = request.form.get("phone")
        email = request.form.get("email")
        job_title = request.form.get("job_title")
        hire_date = request.form.get("hire_date")
        termination_date = request.form.get("termination_date")
        status = request.form.get("status")
        birthday = request.form.get("birthday")
        ssn_on_file = True if request.form.get("ssn_on_file") == "on" else False
        esthetician_license_number = request.form.get("esthetician_license_number")
        license_expiration_date = request.form.get("license_expiration_date")
        year_graduated = request.form.get("year_graduated")
        certifications = request.form.get("certifications")
        pay_type = request.form.get("pay_type")
        pay_rate = request.form.get("pay_rate")
        notes = request.form.get("notes")

        if not first_name or not last_name:
            flash("First name and last name are required.", "error")
            cur.close()
            conn.close()
            return redirect(url_for("add_employee"))

        cur.execute("""
            INSERT INTO employees (
                first_name,
                last_name,
                address_line1,
                address_line2,
                city,
                state,
                zip_code,
                phone,
                email,
                job_title,
                hire_date,
                termination_date,
                status,
                birthday,
                ssn_on_file,
                esthetician_license_number,
                license_expiration_date,
                year_graduated,
                certifications,
                pay_type,
                pay_rate,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            first_name,
            last_name,
            address_line1,
            address_line2,
            city,
            state,
            zip_code,
            phone,
            email,
            job_title,
            hire_date or None,
            termination_date or None,
            status,
            birthday or None,
            ssn_on_file,
            esthetician_license_number,
            license_expiration_date or None,
            year_graduated or None,
            certifications,
            pay_type,
            pay_rate or None,
            notes
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Employee added successfully.", "success")
        return redirect(url_for("employees_home"))

    cur.execute("SELECT status_name FROM employee_status ORDER BY status_name ASC")
    statuses = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("add_employee.html", statuses=statuses)



#  ------------------------------------------
#          EDIT EMPLOYEE
#  ------------------------------------------

@app.route("/employees/edit/<int:employee_id>", methods=["GET", "POST"])
def edit_employee(employee_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        address_line1 = request.form.get("address_line1")
        address_line2 = request.form.get("address_line2")
        city = request.form.get("city")
        state = request.form.get("state")
        zip_code = request.form.get("zip_code")
        phone = request.form.get("phone")
        email = request.form.get("email")
        job_title = request.form.get("job_title")
        hire_date = request.form.get("hire_date")
        termination_date = request.form.get("termination_date")
        status = request.form.get("status")
        birthday = request.form.get("birthday")
        ssn_on_file = True if request.form.get("ssn_on_file") == "on" else False
        esthetician_license_number = request.form.get("esthetician_license_number")
        license_expiration_date = request.form.get("license_expiration_date")
        year_graduated = request.form.get("year_graduated")
        certifications = request.form.get("certifications")
        pay_type = request.form.get("pay_type")
        pay_rate = request.form.get("pay_rate")
        notes = request.form.get("notes")

        cur.execute("""
            UPDATE employees
            SET first_name = %s,
                last_name = %s,
                address_line1 = %s,
                address_line2 = %s,
                city = %s,
                state = %s,
                zip_code = %s,
                phone = %s,
                email = %s,
                job_title = %s,
                hire_date = %s,
                termination_date = %s,
                status = %s,
                birthday = %s,
                ssn_on_file = %s,
                esthetician_license_number = %s,
                license_expiration_date = %s,
                year_graduated = %s,
                certifications = %s,
                pay_type = %s,
                pay_rate = %s,
                notes = %s
            WHERE employee_id = %s
        """, (
            first_name,
            last_name,
            address_line1,
            address_line2,
            city,
            state,
            zip_code,
            phone,
            email,
            job_title,
            hire_date or None,
            termination_date or None,
            status,
            birthday or None,
            ssn_on_file,
            esthetician_license_number,
            license_expiration_date or None,
            year_graduated or None,
            certifications,
            pay_type,
            pay_rate or None,
            notes,
            employee_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Employee updated successfully.", "success")
        return redirect(url_for("employees_home"))

    cur.execute("""
        SELECT
            employee_id,
            first_name,
            last_name,
            address_line1,
            address_line2,
            city,
            state,
            zip_code,
            phone,
            email,
            job_title,
            hire_date,
            termination_date,
            status,
            birthday,
            ssn_on_file,
            esthetician_license_number,
            license_expiration_date,
            year_graduated,
            certifications,
            pay_type,
            pay_rate,
            notes,
            created_at
        FROM employees
        WHERE employee_id = %s
    """, (employee_id,))
    employee = cur.fetchone()

    if not employee:
        cur.close()
        conn.close()
        flash("Employee not found.", "error")
        return redirect(url_for("employees_home"))

    cur.execute("SELECT status_name FROM employee_status ORDER BY status_name ASC")
    statuses = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("edit_employee.html", employee=employee, statuses=statuses)



            
#  ------------------------------------------
#            DELETE EMPLOYEE
#  ------------------------------------------
            
@app.route("/employees/delete/<int:employee_id>", methods=["POST"])
def delete_employee(employee_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
    conn.commit()

    cur.close()
    conn.close()

    flash("Employee deleted successfully.", "success")
    return redirect(url_for("employees_home"))




#  ------------------------------------------
#
#      EXPENSES  SECTION
#
#
#  ------------------------------------------



    
#  ------------------------------------------
#      EXPENSES  HOME
#  ------------------------------------------

@app.route("/expenses")
def expenses_home():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            expense_id,
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            receipt_file,
            notes,
            created_at
        FROM expenses
        ORDER BY expense_date DESC, expense_id DESC
        LIMIT 25
    """)
    expenses = cur.fetchall()

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE expense_date = CURRENT_DATE
    """)
    today_total = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE DATE_TRUNC('month', expense_date) = DATE_TRUNC('month', CURRENT_DATE)
    """)
    month_total = cur.fetchone()[0]

    cur.close()
    conn.close()

    return render_template(
        "expenses_home.html",
        expenses=expenses,
        today_total=today_total,
        month_total=month_total
    )
        
#  ------------------------------------------
#      ADD  EXPENSES
#  ------------------------------------------

@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense(): 
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()  
            
    if request.method == "POST":
        expense_date = request.form.get("expense_date")
        vendor_name = request.form.get("vendor_name")
        category = request.form.get("category")
        description = request.form.get("description")
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method")
        receipt_file = request.form.get("receipt_file")
        notes = request.form.get("notes")
        
        if not expense_date or not vendor_name or not amount:
            flash("Expense date, vendor name, and amount are required.", "error")
            cur.close()
            conn.close()
            return redirect(url_for("add_expense"))
        
        try:
            amount = Decimal(amount)
        except:
            flash("Amount must be a valid number.", "error")
            cur.close()
            conn.close()
            return redirect(url_for("add_expense"))
            
        cur.execute("""
            INSERT INTO expenses (
                expense_date,
                vendor_name,
                category,
                description,
                amount,
                payment_method,
                receipt_file,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            expense_date,
            vendor_name,
            category,  
            description,
            amount,
            payment_method,
            receipt_file,
            notes
        ))
        
        conn.commit()
        cur.close()
        conn.close()
    
        flash("Expense added successfully.", "success")
        return redirect(url_for("expenses_home"))
            
    cur.execute("""
        SELECT vendors_name
        FROM vendor_name
        ORDER BY vendors_name ASC
    """)
    vendors = cur.fetchall()

    cur.execute("""
        SELECT expense_cat_name
        FROM expense_categories
        ORDER BY expense_cat_name ASC
    """)
    categories = cur.fetchall()
        
    cur.execute("""
        SELECT payment_method
        FROM payment_methods
        ORDER BY payment_method ASC
    """)
    payment_methods = cur.fetchall()
            
    cur.close()
    conn.close()
        
    return render_template(
        "add_expense.html",  
        today=date.today().isoformat(),
        vendors=vendors, 
        categories=categories,
        payment_methods=payment_methods
    )




        
#  ------------------------------------------
#      EXPENSE REPORT
#  ------------------------------------------

@app.route("/expenses/report", methods=["GET"])
def expense_report():
    spa_id = get_current_spa_id()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    category = request.args.get("category", "").strip()
    vendor_name = request.args.get("vendor_name", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    # Load category dropdown options
    cur.execute("""
        SELECT expense_cat_id, expense_cat_name
        FROM expense_categories
        ORDER BY expense_cat_name
    """)
    category_options = cur.fetchall()

    # -----------------------------
    # Main expense rows
    # -----------------------------
    query = """
        SELECT
            expense_id,
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            receipt_file,
            notes,
            created_at
        FROM expenses
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND expense_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND expense_date <= %s"
        params.append(end_date)

    if category:
        query += " AND category = %s"
        params.append(category)

    if vendor_name:
        query += " AND vendor_name ILIKE %s"
        params.append(f"%{vendor_name}%")

    query += " ORDER BY expense_date DESC, expense_id DESC"

    cur.execute(query, tuple(params))
    expenses = cur.fetchall()

    # -----------------------------
    # Total amount
    # -----------------------------
    total_query = """
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE 1=1
    """
    total_params = []

    if start_date:
        total_query += " AND expense_date >= %s"
        total_params.append(start_date)

    if end_date:
        total_query += " AND expense_date <= %s"
        total_params.append(end_date)

    if category:
        total_query += " AND category = %s"
        total_params.append(category)

    if vendor_name:
        total_query += " AND vendor_name ILIKE %s"
        total_params.append(f"%{vendor_name}%")

    cur.execute(total_query, tuple(total_params))
    report_total = cur.fetchone()[0]

    # -----------------------------
    # Category totals
    # -----------------------------
    category_totals_query = """
        SELECT
            category,
            COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE 1=1
    """
    category_totals_params = []

    if start_date:
        category_totals_query += " AND expense_date >= %s"
        category_totals_params.append(start_date)

    if end_date:
        category_totals_query += " AND expense_date <= %s"
        category_totals_params.append(end_date)

    if category:
        category_totals_query += " AND category = %s"
        category_totals_params.append(category)

    if vendor_name:
        category_totals_query += " AND vendor_name ILIKE %s"
        category_totals_params.append(f"%{vendor_name}%")

    category_totals_query += """
        GROUP BY category
        ORDER BY category
    """

    cur.execute(category_totals_query, tuple(category_totals_params))
    category_totals_rows = cur.fetchall()

    category_totals = {}
    for row in category_totals_rows:
        category_name = row[0] if row[0] else "Uncategorized"
        category_totals[category_name] = row[1]

    cur.close()
    conn.close()

    return render_template(
        "expense_report.html",
        start_date=start_date,
        end_date=end_date,
        category=category,
        vendor_name=vendor_name,
        category_options=category_options,
        expenses=expenses,
        report_total=report_total,
        category_totals=category_totals
    )



#  ------------------------------------------
#         EDIT EXPENSES
#  ------------------------------------------
            
@app.route("/expenses/edit/<int:expense_id>", methods=["GET", "POST"])
def edit_expense(expense_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        expense_date = request.form.get("expense_date")
        vendor_name = request.form.get("vendor_name")
        category = request.form.get("category")
        description = request.form.get("description")
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method")
        receipt_file = request.form.get("receipt_file")
        notes = request.form.get("notes")

        cur.execute("""
            UPDATE expenses
            SET expense_date = %s,
                vendor_name = %s,
                category = %s,
                description = %s,
                amount = %s,
                payment_method = %s,
                receipt_file = %s,
                notes = %s
            WHERE expense_id = %s
        """, (
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            receipt_file,
            notes,
            expense_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Expense updated successfully.", "success")
        return redirect(url_for("expenses_home"))

    cur.execute("""
        SELECT
            expense_id,
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            receipt_file,
            notes,
            created_at
        FROM expenses
        WHERE expense_id = %s
    """, (expense_id,))
    expense = cur.fetchone()

    if not expense:
        cur.close()
        conn.close()
        flash("Expense not found.", "error")
        return redirect(url_for("expenses_home"))

    cur.execute("SELECT vendors_name FROM vendor_name ORDER BY vendors_name ASC")
    vendors = cur.fetchall()

    cur.execute("SELECT expense_cat_name FROM expense_categories ORDER BY expense_cat_name ASC")
    categories = cur.fetchall()

    cur.execute("SELECT payment_method FROM payment_methods ORDER BY payment_method ASC")
    payment_methods = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "edit_expense.html",
        expense=expense,
        vendors=vendors,
        categories=categories,
        payment_methods=payment_methods
    )    


#  ------------------------------------------
#         DELETE EXPENSES
#  ------------------------------------------
            
@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM expenses WHERE expense_id = %s", (expense_id,))
    conn.commit()

    cur.close()
    conn.close()

    flash("Expense deleted successfully.", "success")
    return redirect(url_for("expenses_home"))


#  ------------------------------------------
#         EXPORT  EXPENSES TO CSV
#  ------------------------------------------

from flask import Response, request
import csv
import io

@app.route("/export_expense_report_csv")
def export_expense_report_csv():
    spa_id = get_current_spa_id()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            notes
        FROM expenses
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND expense_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND expense_date <= %s"
        params.append(end_date)

    query += " ORDER BY expense_date DESC, expense_id DESC"

    cur.execute(query, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Expense Date",
        "Vendor Name",
        "Category",
        "Description",
        "Amount",
        "Payment Method",
        "Notes"
    ])

    # Data rows
    for row in rows:
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=expense_report.csv"
        }
    )



#  ------------------------------------------  
#        EXPORT EXPENSES TO XLSX FORMAT
#  ------------------------------------------

from flask import send_file, request
from openpyxl import Workbook
from openpyxl.styles import Font
from io import BytesIO
from collections import defaultdict

@app.route("/export_expense_report_xlsx")
def export_expense_report_xlsx():
    spa_id = get_current_spa_id()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT
            expense_date,
            vendor_name,
            category,
            description,
            amount,
            payment_method,
            notes
        FROM expenses
        WHERE 1=1
    """
    params = []

    if start_date:
        query += " AND expense_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND expense_date <= %s"
        params.append(end_date)

    query += " ORDER BY expense_date DESC, expense_id DESC"

    cur.execute(query, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Expense Report"

    # Title
    ws["A1"] = "Expense Report"
    ws["A1"].font = Font(bold=True, size=14)

    # Date range
    if start_date and end_date:
        ws["A2"] = f"Date Range: {start_date} to {end_date}"
    elif start_date:
        ws["A2"] = f"Date Range: From {start_date}"
    elif end_date:
        ws["A2"] = f"Date Range: Through {end_date}"
    else:
        ws["A2"] = "Date Range: All Expenses"

    # Headers
    headers = [
        "Expense Date",
        "Vendor Name",
        "Category",
        "Description",
        "Amount",
        "Payment Method",
        "Notes"
    ]

    header_row = 4
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_num, value=header)
        cell.font = Font(bold=True)

    # Data rows
    data_start_row = 5
    grand_total = 0
    category_totals = defaultdict(float)

    for row_index, row in enumerate(rows, start=data_start_row):
        expense_date, vendor_name, category, description, amount, payment_method, notes = row

        ws.cell(row=row_index, column=1, value=expense_date)
        ws.cell(row=row_index, column=2, value=vendor_name)
        ws.cell(row=row_index, column=3, value=category)
        ws.cell(row=row_index, column=4, value=description)
        ws.cell(row=row_index, column=5, value=float(amount) if amount is not None else 0)
        ws.cell(row=row_index, column=6, value=payment_method)
        ws.cell(row=row_index, column=7, value=notes)

        ws.cell(row=row_index, column=5).number_format = '$#,##0.00'

        amt = float(amount) if amount is not None else 0
        grand_total += amt
        category_totals[category or "Uncategorized"] += amt

    # Grand total
    total_row = data_start_row + len(rows) + 1
    ws.cell(row=total_row, column=4, value="GRAND TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=5, value=grand_total).font = Font(bold=True)
    ws.cell(row=total_row, column=5).number_format = '$#,##0.00'

    # Category totals section
    category_start_row = total_row + 3
    ws.cell(row=category_start_row, column=1, value="Category Totals").font = Font(bold=True, size=12)

    ws.cell(row=category_start_row + 1, column=1, value="Category").font = Font(bold=True)
    ws.cell(row=category_start_row + 1, column=2, value="Total").font = Font(bold=True)

    current_row = category_start_row + 2
    for category, total in sorted(category_totals.items()):
        ws.cell(row=current_row, column=1, value=category)
        ws.cell(row=current_row, column=2, value=total)
        ws.cell(row=current_row, column=2).number_format = '$#,##0.00'
        current_row += 1

    # Column widths
    widths = {
        "A": 15,
        "B": 22,
        "C": 20,
        "D": 30,
        "E": 14,
        "F": 18,
        "G": 30
    }

    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    # Filename
    filename = "expense_report.xlsx"
    if start_date and end_date:
        filename = f"expense_report_{start_date}_to_{end_date}.xlsx"
    elif start_date:
        filename = f"expense_report_from_{start_date}.xlsx"
    elif end_date:
        filename = f"expense_report_to_{end_date}.xlsx"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )






#  ------------------------------------------
#
#      INCOME SECTION
#
#
#  ------------------------------------------



#  ------------------------------------------
#         ADD INCOME
#  ------------------------------------------


@app.route("/add_income/<int:appointment_id>", methods=["GET", "POST"])
def add_income(appointment_id):
    spa_id = get_current_spa_id()
    selected_date = request.args.get("date") or request.form.get("date") or ""

    conn = get_db_connection()
    cur = conn.cursor()

    # Get appointment and client info
    cur.execute("""
        SELECT
            a.appointment_id,
            a.client_id,
            a.appointment_date,
            a.appointment_time,
            c.first_name,
            c.last_name
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
        WHERE a.appointment_id = %s
          AND a.spa_id = %s
    """, (appointment_id, spa_id))
    appt = cur.fetchone()


    cur.execute("""
        SELECT employee_id,
               first_name || ' ' || last_name AS employee_name
        FROM employees
        WHERE spa_id = %s
        ORDER BY employee_name
    """, (spa_id,))
    employees = cur.fetchall()


    cur.execute("""
        SELECT credit_processor_id, credit_processor_name
        FROM credit_processors
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY credit_processor_name
    """, (spa_id,))
    credit_processors = cur.fetchall()

    if not appt:
        cur.close()
        conn.close()
        flash("Appointment not found.", "error")
        if selected_date:
            return redirect(url_for("daily_schedule", date=selected_date))
        return redirect(url_for("appointments"))

    if request.method == "POST":
        income_date = request.form.get("income_date")
        income_type = request.form.get("income_type")
        description = request.form.get("description")

        service_amount = float(request.form.get("service_amount") or 0)
        retail_amount = float(request.form.get("retail_amount") or 0)
        tax_amount = float(request.form.get("tax_amount") or 0)
        tip_amount = float(request.form.get("tip_amount") or 0)

        total_amount = round(service_amount + retail_amount + tax_amount + tip_amount, 2)

        payment_method = request.form.get("payment_method", "").strip()
        credit_processor_id = request.form.get("credit_processor_id") or None
        processor_payment_id = request.form.get("processor_payment_id") or None

        print("DEBUG payment_method:", payment_method)
        print("DEBUG credit_processor_id:", credit_processor_id)
        print("DEBUG processor_payment_id:", processor_payment_id)
        print("DEBUG total_amount:", total_amount)

        processing_fee_amount = 0.00
        net_received = total_amount
        processor_percentage_fee = 0.00
        processor_flat_fee = 0.00
        processor_additional_fee = 0.00

        card_based_methods = ["card", "credit card", "apple pay", "google pay", "square"]

        if payment_method.lower() in card_based_methods:
            print("DEBUG entered fee calculation block")

            if credit_processor_id:
                cur.execute("""
                    SELECT percentage_fee, flat_fee, additional_fee
                    FROM credit_processors
                    WHERE credit_processor_id = %s
                      AND spa_id = %s
                      AND is_active = TRUE
                """, (credit_processor_id, spa_id))

                processor_row = cur.fetchone()
                print("DEBUG processor_row:", processor_row)

                if processor_row:
                    processor_percentage_fee = float(processor_row[0] or 0)
                    processor_flat_fee = float(processor_row[1] or 0)
                    processor_additional_fee = float(processor_row[2] or 0)

                    processing_fee_amount = round(
                        (total_amount * (processor_percentage_fee / 100))
                        + processor_flat_fee
                        + processor_additional_fee,
                        2
                    )

                    net_received = round(
                        total_amount - processing_fee_amount,
                        2
                    )
            else:
                credit_processor_id = None

        visit_id = None
        employee_id = request.form.get("employee_id") or None
        processor_payment_id = request.form.get("processor_payment_id") or None
        notes = request.form.get("notes") or ""

   
        cur.execute("""
            INSERT INTO income (
                income_date,
                client_id,
                appointment_id,
                visit_id,
                income_type,
                description,
                service_amount,
                retail_amount,
                tax_amount,
                tip_amount,
                total_amount,
                payment_method,
                processor_payment_id,
                notes,
                spa_id,
                employee_id,
                credit_processor_id,
                processing_fee_amount,
                net_received,
                processor_percentage_fee,
                processor_flat_fee,
                processor_additional_fee,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
        """, (
            income_date,
            appt[1],   # client_id
            appt[0],   # appointment_id
            visit_id,
            income_type,
            description,
            service_amount,
            retail_amount,
            tax_amount,
            tip_amount,
            total_amount,
            payment_method,
            processor_payment_id,
            notes,
            spa_id,
            employee_id,
            credit_processor_id,
            processing_fee_amount,
            net_received,
            processor_percentage_fee,
            processor_flat_fee,
            processor_additional_fee
        ))


        conn.commit()
        cur.close()
        conn.close()

        flash("Income added successfully.", "success")
        return redirect(url_for(
            "post_appointment_wrap_up",
            appointment_id=appt[0],
            date=selected_date
        ))


    cur.close()
    conn.close()

    return render_template(
        "add_income.html",
        appt=appt,
        selected_date=selected_date,
        credit_processors=credit_processors,
        employees=employees
    )



#  --------------------------
#
#     EDIT  INCOME
#
#  ------------------------



@app.route("/edit_income/<int:income_id>", methods=["GET", "POST"])
def edit_income(income_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        income_date = request.form.get("income_date") or None
        income_type = request.form.get("income_type", "").strip()  or "General"
        employee_id = request.form.get("employee_id") or None

        service_amount = float(request.form.get("service_amount") or 0)
        retail_amount = float(request.form.get("retail_amount") or 0)
        tax_amount = float(request.form.get("tax_amount") or 0)
        tip_amount = float(request.form.get("tip_amount") or 0)

        total_amount = round(service_amount + retail_amount + tax_amount + tip_amount, 2)

        payment_method = request.form.get("payment_method", "").strip()
        credit_processor_id = request.form.get("credit_processor_id") or None
        processor_payment_id = request.form.get("processor_payment_id") or None

        processing_fee_amount = 0.00
        net_received = total_amount
        processor_percentage_fee = 0.00
        processor_flat_fee = 0.00
        processor_additional_fee = 0.00

        card_based_methods = ["card", "credit card", "apple pay", "google pay", "square"]

        if payment_method.lower() in card_based_methods:
            if credit_processor_id:
                cur.execute("""
                    SELECT percentage_fee, flat_fee, additional_fee
                    FROM credit_processors
                    WHERE credit_processor_id = %s
                      AND spa_id = %s
                      AND is_active = TRUE
                """, (credit_processor_id, spa_id))
                processor_row = cur.fetchone()

                if processor_row:
                    processor_percentage_fee = float(processor_row[0] or 0)
                    processor_flat_fee = float(processor_row[1] or 0)
                    processor_additional_fee = float(processor_row[2] or 0)

                    processing_fee_amount = round(
                        (total_amount * (processor_percentage_fee / 100))
                        + processor_flat_fee
                        + processor_additional_fee,
                        2
                    )
                    net_received = round(total_amount - processing_fee_amount, 2)
        else:
            credit_processor_id = None
            processor_payment_id = None

        description = request.form.get("description") or None
        notes = request.form.get("notes") or None
        client_id = request.form.get("client_id") or None

        cur.execute("""
            UPDATE income
            SET
                income_date = %s,
                income_type = %s,
                description = %s,
                service_amount = %s,
                retail_amount = %s,
                tax_amount = %s,
                tip_amount = %s,
                total_amount = %s,
                payment_method = %s,
                processor_payment_id = %s,
                notes = %s,
                employee_id = %s,
                credit_processor_id = %s,
                processing_fee_amount = %s,
                net_received = %s,
                processor_percentage_fee = %s,
                processor_flat_fee = %s,
                processor_additional_fee = %s,
                client_id = %s
            WHERE income_id = %s
              AND spa_id = %s
        """, (
            income_date,
            income_type,
            description,
            service_amount,
            retail_amount,
            tax_amount,
            tip_amount,
            total_amount,
            payment_method,
            processor_payment_id,
            notes,
            employee_id,
            credit_processor_id,
            processing_fee_amount,
            net_received,
            processor_percentage_fee,
            processor_flat_fee,
            processor_additional_fee,
            client_id,
            income_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Income record updated successfully.", "success")
        return redirect(url_for("income_report"))

    cur.execute("""
        SELECT
            i.income_id,
            i.income_date,
            i.income_type,
            i.description,
            i.service_amount,
            i.retail_amount,
            i.tax_amount,
            i.tip_amount,
            i.total_amount,
            i.payment_method,
            i.processor_payment_id,
            i.notes,
            i.client_id,
            i.employee_id,
            i.credit_processor_id,
            c.first_name,
            c.last_name
        FROM income i
        LEFT JOIN clients c ON i.client_id = c.client_id
        WHERE i.income_id = %s
          AND i.spa_id = %s
    """, (income_id, spa_id))
    income_record = cur.fetchone()

    cur.execute("""
        SELECT client_id, first_name, last_name
        FROM clients
        WHERE spa_id = %s
        ORDER BY last_name, first_name
    """, (spa_id,))
    clients = cur.fetchall()

    cur.execute("""
        SELECT employee_id, first_name, last_name
        FROM employees
        WHERE spa_id = %s
        ORDER BY last_name, first_name
    """, (spa_id,))
    employees = cur.fetchall()

    cur.execute("""
        SELECT credit_processor_id, credit_processor_name
        FROM credit_processors
        WHERE spa_id = %s
          AND is_active = TRUE
        ORDER BY credit_processor_name
    """, (spa_id,))
    credit_processors = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "edit_income.html",
        income_record=income_record,
        clients=clients,
        employees=employees,
        credit_processors=credit_processors
    )





    
#  --------------------------
#     INCOME EXPORT TO CSV      
# ROUTE: income_report/csv    
#
#  ------------------------


@app.route("/income_report/csv")
def income_report_csv():
    spa_id = get_current_spa_id()
    today = date.today()
    first_day = today.replace(day=1)

    start_date = request.args.get("start_date", first_day.strftime("%Y-%m-%d"))
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d"))
    income_type = request.args.get("income_type", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    filter_sql = "WHERE i.spa_id = %s AND i.income_date BETWEEN %s AND %s"
    params = [spa_id, start_date, end_date]

    if income_type:
        filter_sql += " AND i.income_type = %s"
        params.append(income_type)

    cur.execute(f"""
        SELECT
            i.income_id,
            i.income_date,
            COALESCE(c.first_name || ' ' || c.last_name, 'No Client') AS client_name,
            COALESCE(e.first_name || ' ' || e.last_name, 'Unassigned') AS employee_name,
            COALESCE(i.income_type, '') AS income_type,
            COALESCE(i.description, '') AS description,
            COALESCE(i.payment_method, '') AS payment_method,
            COALESCE(i.service_amount, 0.00) AS service_amount,
            COALESCE(i.tip_amount, 0.00) AS tip_amount,
            COALESCE(i.retail_amount, 0.00) AS retail_amount,
            COALESCE(i.tax_amount, 0.00) AS tax_amount,
            COALESCE(i.total_amount, 0.00) AS total_amount,
            COALESCE(i.notes, '') AS notes
        FROM income i
        LEFT JOIN clients c ON i.client_id = c.client_id
        LEFT JOIN employees e ON i.employee_id = e.employee_id
        {filter_sql}
        ORDER BY i.income_date DESC, i.income_id DESC
    """, params)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Income ID",
        "Income Date",
        "Client Name",
        "Employee",
        "Income Type",
        "Description",
        "Payment Method",
        "Service Amount",
        "Tip Amount",
        "Retail Amount",
        "Tax Amount",
        "Total Amount",
        "Notes"
    ])

    for row in rows:
        writer.writerow(row)

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=income_report.csv"}
    )







# -----------------------
# INCOME EXPORT TO EXCEL
#  ROUTE: income_report/excel
#
#
#  ----------------------


@app.route("/income_report/excel")
def income_report_excel():
    spa_id = get_current_spa_id()
    today = date.today()
    first_day = today.replace(day=1)

    start_date = request.args.get("start_date", first_day.strftime("%Y-%m-%d"))
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d"))
    income_type = request.args.get("income_type", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    filter_sql = "WHERE i.spa_id = %s AND i.income_date BETWEEN %s AND %s"
    params = [spa_id, start_date, end_date]

    if income_type:
        filter_sql += " AND i.income_type = %s"
        params.append(income_type)

    cur.execute(f"""
        SELECT
            i.income_id,
            i.income_date,
            COALESCE(c.first_name || ' ' || c.last_name, 'No Client') AS client_name,
            COALESCE(e.first_name || ' ' || e.last_name, 'Unassigned') AS employee_name,
            COALESCE(i.income_type, '') AS income_type,
            COALESCE(i.description, '') AS description,
            COALESCE(i.payment_method, '') AS payment_method,
            COALESCE(i.service_amount, 0.00) AS service_amount,
            COALESCE(i.tip_amount, 0.00) AS tip_amount,
            COALESCE(i.retail_amount, 0.00) AS retail_amount,
            COALESCE(i.tax_amount, 0.00) AS tax_amount,
            COALESCE(i.total_amount, 0.00) AS total_amount,
            COALESCE(i.notes, '') AS notes
        FROM income i
        LEFT JOIN clients c ON i.client_id = c.client_id
        LEFT JOIN employees e ON i.employee_id = e.employee_id
        {filter_sql}
        ORDER BY i.income_date DESC, i.income_id DESC
    """, params)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Income Report"

    ws.append([
        "Income ID",
        "Income Date",
        "Client Name",
        "Employee",
        "Income Type",
        "Description",
        "Payment Method",
        "Service Amount",
        "Tip Amount",
        "Retail Amount",
        "Tax Amount",
        "Total Amount",
        "Notes"
    ])

    for row in rows:
        ws.append(list(row))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="income_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )







#  --------------------------
#
#     DELETE  INCOME
#
#  ------------------------

@app.route("/delete_income/<int:income_id>", methods=["POST"])
def delete_income(income_id):
    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip()
    income_type = request.form.get("income_type", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM income WHERE income_id = %s", (income_id,))
    conn.commit()

    cur.close()
    conn.close()

    flash("Income record deleted.", "success")

    return redirect(url_for(
        "income_report",
        start_date=start_date,
        end_date=end_date,
        income_type=income_type
    ))






#-----------------------------
#
#  INCOME REPORT
#
#
#  --------------------------




from datetime import date
from flask import render_template, request
from db import get_db_connection


@app.route("/income_report")
def income_report():
    spa_id = get_current_spa_id()
    today = date.today()
    first_day = today.replace(day=1)

    start_date = request.args.get("start_date") or first_day.strftime("%Y-%m-%d")
    end_date = request.args.get("end_date") or today.strftime("%Y-%m-%d")
    income_type = request.args.get("income_type", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    # Get distinct income types for dropdown
    cur.execute("""
        SELECT DISTINCT income_type
        FROM income
        WHERE spa_id = %s
          AND income_type IS NOT NULL
          AND income_type <> ''
        ORDER BY income_type
    """, (spa_id,))
    income_type_options = [row[0] for row in cur.fetchall()]

    # Build filter
    filter_sql = "WHERE spa_id = %s AND income_date BETWEEN %s AND %s"
    params = [spa_id, start_date, end_date]

    if income_type:
        filter_sql += " AND income_type = %s"
        params.append(income_type)

    # Summary totals
    cur.execute(f"""
        SELECT
            COUNT(*) AS total_entries,
            COALESCE(SUM(service_amount), 0.00) AS total_services,
            COALESCE(SUM(retail_amount), 0.00) AS total_retail,
            COALESCE(SUM(tip_amount), 0.00) AS total_tips,
            COALESCE(SUM(tax_amount), 0.00) AS total_tax,
            COALESCE(SUM(total_amount), 0.00) AS gross_collected,
            COALESCE(SUM(processing_fee_amount), 0.00) AS total_processing_fees,
            COALESCE(SUM(net_received), 0.00) AS total_net_received,
            COALESCE(SUM(service_amount + retail_amount), 0.00) AS spa_income
        FROM income
        {filter_sql}
    """, params)
    summary = cur.fetchone()

    # Income type breakdown
    cur.execute(f"""
        SELECT
            COALESCE(income_type, 'Unspecified') AS income_type,
            COUNT(*) AS entry_count,
            COALESCE(SUM(service_amount + retail_amount), 0.00) AS spa_income,
            COALESCE(SUM(tip_amount), 0.00) AS total_tips,
            COALESCE(SUM(total_amount), 0.00) AS gross_collected,
            COALESCE(SUM(processing_fee_amount), 0.00) AS total_processing_fees,
            COALESCE(SUM(net_received), 0.00) AS total_net_received
        FROM income
        {filter_sql}
        GROUP BY income_type
        ORDER BY gross_collected DESC
    """, params)
    income_type_breakdown = cur.fetchall()

    # Payment method breakdown
    cur.execute(f"""
        SELECT
            COALESCE(payment_method, 'Unspecified') AS payment_method,
            COUNT(*) AS entry_count,
            COALESCE(SUM(service_amount + retail_amount), 0.00) AS spa_income,
            COALESCE(SUM(tip_amount), 0.00) AS total_tips,
            COALESCE(SUM(total_amount), 0.00) AS gross_collected,
            COALESCE(SUM(processing_fee_amount), 0.00) AS total_processing_fees,
            COALESCE(SUM(net_received), 0.00) AS total_net_received
        FROM income
        {filter_sql}
        GROUP BY payment_method
        ORDER BY gross_collected DESC
    """, params)
    payment_breakdown = cur.fetchall()

    # Credit processor breakdown
    cur.execute(f"""
        SELECT
            COALESCE(cp.credit_processor_name, 'None') AS credit_processor_name,
            COUNT(*) AS entry_count,
            COALESCE(SUM(total_amount), 0.00) AS gross_collected,
            COALESCE(SUM(processing_fee_amount), 0.00) AS total_processing_fees,
            COALESCE(SUM(net_received), 0.00) AS total_net_received
        FROM income i
        LEFT JOIN credit_processors cp
            ON i.credit_processor_id = cp.credit_processor_id
        {filter_sql.replace("spa_id", "i.spa_id").replace("income_date", "i.income_date").replace("income_type", "i.income_type")}
        GROUP BY cp.credit_processor_name
        ORDER BY total_processing_fees DESC, gross_collected DESC
    """, params)
    processor_breakdown = cur.fetchall()

    # Detailed report rows
    cur.execute(f"""
        SELECT
            i.income_id,
            i.income_date,
            COALESCE(c.first_name || ' ' || c.last_name, 'No Client') AS client_name,
            COALESCE(e.first_name || ' ' || e.last_name, 'Unassigned') AS employee_name,
            COALESCE(i.income_type, '') AS income_type,
            COALESCE(i.description, '') AS description,
            COALESCE(i.payment_method, '') AS payment_method,
            COALESCE(cp.credit_processor_name, '') AS credit_processor_name,
            COALESCE(i.processor_payment_id, '') AS processor_payment_id,
            COALESCE(i.service_amount, 0.00) AS service_amount,
            COALESCE(i.tip_amount, 0.00) AS tip_amount,
            COALESCE(i.retail_amount, 0.00) AS retail_amount,
            COALESCE(i.tax_amount, 0.00) AS tax_amount,
            COALESCE(i.total_amount, 0.00) AS total_amount,
            COALESCE(i.processing_fee_amount, 0.00) AS processing_fee_amount,
            COALESCE(i.net_received, 0.00) AS net_received,
            COALESCE(i.notes, '') AS notes
        FROM income i
        LEFT JOIN clients c ON i.client_id = c.client_id
        LEFT JOIN employees e ON i.employee_id = e.employee_id
        LEFT JOIN credit_processors cp ON i.credit_processor_id = cp.credit_processor_id
        {filter_sql.replace("spa_id", "i.spa_id").replace("income_date", "i.income_date").replace("income_type", "i.income_type")}
        ORDER BY i.income_date DESC, i.income_id DESC
    """, params)
    income_rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "income_report.html",
        start_date=start_date,
        end_date=end_date,
        income_type=income_type,
        income_type_options=income_type_options,
        summary=summary,
        income_type_breakdown=income_type_breakdown,
        payment_breakdown=payment_breakdown,
        processor_breakdown=processor_breakdown,
        income_rows=income_rows
    )









#  -----------------------------
#     ADD GENERAL INCOME
#     
#  -----------------------------

from flask import render_template, request, redirect, url_for, flash
from decimal import Decimal, InvalidOperation
from db import get_db_connection


@app.route("/add_general_income", methods=["GET", "POST"])
def add_general_income():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    # Load dropdowns / clients for form display
    cur.execute("""
        SELECT client_id, first_name, last_name
        FROM clients
        ORDER BY last_name, first_name
    """)
    clients = cur.fetchall()

    cur.execute("""
        SELECT income_type_name
        FROM income_types
        ORDER BY income_type_name
    """)
    income_types = cur.fetchall()

    cur.execute("""
        SELECT payment_method
        FROM payment_methods
        ORDER BY payment_method
    """)
    payment_methods = cur.fetchall()

    if request.method == "POST":
        income_date = request.form.get("income_date")
        client_id = request.form.get("client_id")
        income_type = request.form.get("income_type")
        description = request.form.get("description", "").strip()
        service_amount = request.form.get("service_amount", "0").strip()
        retail_amount = request.form.get("retail_amount", "0").strip()
        tax_amount = request.form.get("tax_amount", "0").strip()
        total_amount = request.form.get("total_amount", "0").strip()
        payment_method = request.form.get("payment_method")
        square_payment_id = request.form.get("square_payment_id", "").strip()
        notes = request.form.get("notes", "").strip()

        try:
            service_amount = Decimal(service_amount) if service_amount else Decimal("0.00")
            retail_amount = Decimal(retail_amount) if retail_amount else Decimal("0.00")
            tax_amount = Decimal(tax_amount) if tax_amount else Decimal("0.00")
            total_amount = Decimal(total_amount) if total_amount else Decimal("0.00")
        except InvalidOperation:
            flash("Please enter valid numeric amounts.", "error")
            cur.close()
            conn.close()
            return render_template(
                "add_general_income.html",
                clients=clients,
                income_types=income_types,
                payment_methods=payment_methods
            )

        if not income_date:
            flash("Income date is required.", "error")
            cur.close()
            conn.close()
            return render_template(
                "add_general_income.html",
                clients=clients,
                income_types=income_types,
                payment_methods=payment_methods
            )

        if not income_type:
            flash("Income type is required.", "error")
            cur.close()
            conn.close()
            return render_template(
                "add_general_income.html",
                clients=clients,
                income_types=income_types,
                payment_methods=payment_methods
            )

        if not payment_method:
            flash("Payment method is required.", "error")
            cur.close()
            conn.close()
            return render_template(
                "add_general_income.html",
                clients=clients,
                income_types=income_types,
                payment_methods=payment_methods
            )

        if total_amount < 0:
            flash("Total amount cannot be negative.", "error")
            cur.close()
            conn.close()
            return render_template(
                "add_general_income.html",
                clients=clients,
                income_types=income_types,
                payment_methods=payment_methods
            )

        # Optional client_id handling
        if client_id == "":
            client_id = None

        cur.execute("""
            INSERT INTO income (
                income_date,
                client_id,
                appointment_id,
                visit_id,
                income_type,
                description,
                service_amount,
                retail_amount,
                tax_amount,
                total_amount,
                payment_method,
                square_payment_id,
                notes
            )
            VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            income_date,
            client_id,
            income_type,
            description,
            service_amount,
            retail_amount,
            tax_amount,
            total_amount,
            payment_method,
            square_payment_id,
            notes
        ))

        conn.commit()
        flash("General income entry added successfully.", "success")

        cur.close()
        conn.close()
        return redirect(url_for("add_general_income"))

    cur.close()
    conn.close()

    return render_template(
        "add_general_income.html",
        clients=clients,
        income_types=income_types,
        payment_methods=payment_methods
    )




#  -----------------------------
#
#
#     CALENDAR
#
#  -----------------------------



from datetime import timedelta, datetime
from flask import render_template, request, redirect, url_for

@app.route("/calendar")
def calendar_view():
    spa_id = get_current_spa_id()
    week_start_str = request.args.get("week_start")
    goto_date = request.args.get("goto_date")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    spa_now = get_spa_now()
    today = spa_now.date()
    now_time = spa_now.time()
    current_timezone = get_current_spa_timezone()

    # Find current week's Sunday
    today_days_since_sunday = (today.weekday() + 1) % 7
    current_week_start = today - timedelta(days=today_days_since_sunday)

    # Determine which week to display
    if goto_date:
        selected_date = datetime.strptime(goto_date, "%Y-%m-%d").date()
        days_since_sunday = (selected_date.weekday() + 1) % 7
        start_of_week = selected_date - timedelta(days=days_since_sunday)
    elif week_start_str:
        start_of_week = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    else:
        start_of_week = current_week_start

    week_days = [start_of_week + timedelta(days=i) for i in range(7)]

    prev_week_start = start_of_week - timedelta(days=7)
    next_week_start = start_of_week + timedelta(days=7)

    conn = get_db_connection()
    cur = conn.cursor()

    filtered_appointments = []

    if start_date and end_date:
        cur.execute("""
            SELECT
                a.appointment_date,
                a.appointment_time,
                c.first_name,
                c.last_name,
                s.service_name,
                a.status,
                a.appointment_id
            FROM appointments a
            JOIN clients c ON a.client_id = c.client_id
            LEFT JOIN services s ON a.service_id = s.service_id
            WHERE a.spa_id = %s
              AND a.appointment_date BETWEEN %s AND %s
            ORDER BY a.appointment_date, a.appointment_time
        """, (spa_id, start_date, end_date))
        filtered_appointments = cur.fetchall()

    # Show booked appointments for the displayed week
    cur.execute("""
        SELECT
            a.appointment_date,
            a.appointment_time,
            c.first_name,
            c.last_name,
            s.service_name,
            a.status,
            a.appointment_id
        FROM appointments a
        JOIN clients c ON a.client_id = c.client_id
        LEFT JOIN services s ON a.service_id = s.service_id
        WHERE a.spa_id = %s
          AND a.appointment_date BETWEEN %s AND %s
        ORDER BY a.appointment_date, a.appointment_time
    """, (spa_id, week_days[0], week_days[-1]))
    appointments = cur.fetchall()

    # Next booked appointment banner
    cur.execute("""
        SELECT
            c.first_name,
            c.last_name,
            a.appointment_date,
            a.appointment_time,
            s.service_name
        FROM appointments a
        JOIN clients c ON a.client_id = c.client_id
        LEFT JOIN services s ON a.service_id = s.service_id
        WHERE a.spa_id = %s
          AND a.status = 'booked'
          AND (
                a.appointment_date > %s
                OR (
                    a.appointment_date = %s
                    AND a.appointment_time >= %s
                )
              )
        ORDER BY a.appointment_date, a.appointment_time
        LIMIT 1
    """, (spa_id, today, today, now_time))
    next_appt = cur.fetchone()

    # Overdue booked appointment count
    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE spa_id = %s
          AND status = 'booked'
          AND (
                appointment_date < %s
                OR (
                    appointment_date = %s
                    AND appointment_time < %s
                )
              )
    """, (spa_id, today, today, now_time))
    overdue_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    formatted_spa_time = spa_now.strftime("%A, %B %d, %Y %I:%M %p")


    return render_template(
        "calendar.html",
        week_days=week_days,
        appointments=appointments,
        today=today,
        now_time=now_time,
        spa_now=spa_now,
        formatted_spa_time=formatted_spa_time,
        current_timezone=current_timezone,
        next_appt=next_appt,
        overdue_count=overdue_count,
        filtered_appointments=filtered_appointments,
        goto_date=goto_date,
        start_of_week=start_of_week,
        current_week_start=current_week_start,
        prev_week_start=prev_week_start,
        next_week_start=next_week_start
    )







#  -----------------------------
#     
#     
#     DAILY SCHEDULE
#  
#  -----------------------------



from datetime import datetime, date

@app.route("/daily_schedule")
def daily_schedule():
    spa_id = get_current_spa_id()
    selected_date = request.args.get("date")

    if selected_date:
        display_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
    else:
        display_date = get_spa_today()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            a.appointment_id,
            a.client_id,
            c.first_name,
            c.last_name,
            s.service_name,
            a.appointment_time,
            a.duration_minutes,
            a.room_number,
            a.status,
            a.notes
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        WHERE a.appointment_date = %s
          AND a.spa_id = %s
        ORDER BY a.appointment_time
    """, (display_date, spa_id))

    appointments = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "daily_schedule.html",
        appointments=appointments,
        display_date=display_date
    )







#  -----------------------------
#    
#
#     DASHBOARD
#
#  -----------------------------



from flask import render_template
from db import get_db_connection
from datetime import date, timedelta

@app.route("/dashboard")
def dashboard():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    spa_now = get_spa_now()
    today = spa_now.date()
    now_time = spa_now.time()

    current_year = today.year
    current_month = today.month
    today_day = today.day

    if current_month == 12:
        next_month = 1
        next_month_year = current_year + 1
    else:
        next_month = current_month + 1
        next_month_year = current_year

    # Total clients
    cur.execute("""
        SELECT COUNT(*)
        FROM clients
        WHERE spa_id = %s;
    """, (spa_id,))
    total_clients = cur.fetchone()[0]

    cur.execute("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.birth_date,
            cbo.offer_sent
        FROM clients c
        LEFT JOIN client_birthday_offers cbo
            ON c.client_id = cbo.client_id
            AND cbo.birthday_year = %s
        WHERE c.spa_id = %s
          AND c.birth_date IS NOT NULL
          AND c.active_client = TRUE
    """, (current_year, spa_id))

    all_birthdays = cur.fetchall()

    birthday_alert_count = 0

    for row in all_birthdays:
        birth_date = row[3]
        offer_sent = row[4]

        if not birth_date:
            continue

        birth_month = birth_date.month

        # current month birthdays not yet sent
        if birth_month == current_month and not offer_sent:
            birthday_alert_count += 1

        # after the 15th, also include next month birthdays
        elif today.day >= 15 and birth_month == next_month and not offer_sent:
            birthday_alert_count += 1

    # Today's appointments
    cur.execute("""
        SELECT
            a.appointment_id,
            c.first_name,
            c.last_name,
            s.service_name,
            a.appointment_date,
            a.appointment_time,
            a.status
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        WHERE a.spa_id = %s
          AND a.appointment_date = %s
        ORDER BY a.appointment_time ASC;
    """, (spa_id, today))
    todays_appointments = cur.fetchall()

    # Upcoming appointments (future only)
    cur.execute("""
        SELECT
            a.appointment_id,
            c.first_name,
            c.last_name,
            s.service_name,
            a.appointment_date,
            a.appointment_time,
            a.status
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        WHERE a.spa_id = %s
          AND a.appointment_date > %s
          AND a.status NOT IN ('cancelled', 'completed')
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        LIMIT 10;
    """, (spa_id, today))
    upcoming_appointments = cur.fetchall()

    # Completed appointments count
    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE spa_id = %s
          AND status = 'completed';
    """, (spa_id,))
    completed_count = cur.fetchone()[0]

    # Top services
    cur.execute("""
        SELECT
            COALESCE(s.service_name, 'Unknown Service') AS service_name,
            COUNT(*) AS total_booked
        FROM appointments a
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        WHERE a.spa_id = %s
        GROUP BY s.service_name
        ORDER BY total_booked DESC
        LIMIT 5;
    """, (spa_id,))
    top_services = cur.fetchall()

    # Optional summary counts
    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE spa_id = %s
          AND appointment_date = %s;
    """, (spa_id, today))
    today_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE spa_id = %s
          AND appointment_date > %s
          AND status NOT IN ('cancelled', 'completed');
    """, (spa_id, today))
    upcoming_count = cur.fetchone()[0]

    # Next appointment
    cur.execute("""
        SELECT
            c.first_name,
            c.last_name,
            a.appointment_date,
            a.appointment_time,
            s.service_name
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        WHERE a.spa_id = %s
          AND a.status = 'booked'
          AND (
                a.appointment_date > %s
                OR (
                    a.appointment_date = %s
                    AND a.appointment_time >= %s
                )
              )
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
        LIMIT 1;
    """, (spa_id, today, today, now_time))
    next_appt = cur.fetchone()

    # Revenue today (completed appointments only)
    cur.execute("""
        SELECT COALESCE(SUM(price_at_booking), 0)
        FROM appointments
        WHERE spa_id = %s
          AND appointment_date = %s
          AND status = 'completed';
    """, (spa_id, today))
    revenue_today = cur.fetchone()[0]


    cur.execute("""
    SELECT COUNT(*)
        FROM gift_certificates gc
        LEFT JOIN gift_certificate_statuses gcs
            ON gc.gift_certificate_status_id = gcs.gift_certificate_status_id
        WHERE gc.spa_id = %s
          AND gc.expires_date IS NOT NULL
          AND gc.expires_date >= CURRENT_DATE
          AND gc.expires_date <= CURRENT_DATE + INTERVAL '60 days'
          AND gcs.status_name IN ('Active', 'Printed')
          AND gc.remaining_balance > 0
    """, (spa_id,))
    expiring_gc_count = cur.fetchone()[0]



    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        expiring_gc_count=expiring_gc_count,
        total_clients=total_clients,
        todays_appointments=todays_appointments,
        upcoming_appointments=upcoming_appointments,
        completed_count=completed_count,
        top_services=top_services,
        today_count=today_count,
        birthday_alert_count=birthday_alert_count,
        upcoming_count=upcoming_count,
        next_appt=next_appt,
        revenue_today=revenue_today
    )




#  ------------------------------
#
#       REPORTS
#
#  -----------------------------


from datetime import date, datetime, timedelta

@app.route("/reports")
def reports():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = today.replace(day=1)

    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

    # Today's completed appointments
    cur.execute("""
        SELECT 
            a.appointment_id,
            c.first_name,
            c.last_name,
            s.service_name,
            a.appointment_date,
            a.appointment_time,
            a.room_number,
            a.price_at_booking
        FROM appointments a
        JOIN clients c ON a.client_id = c.client_id
        LEFT JOIN services s ON a.service_id = s.service_id
        WHERE a.appointment_date = %s
          AND a.status = 'completed'
        ORDER BY a.appointment_time
    """, (today,))
    daily_completed = cur.fetchall() or []

    # Weekly totals
    cur.execute("""
        SELECT
            COUNT(*) AS total_appointments,
            COUNT(*) FILTER (WHERE status = 'booked') AS booked_count,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
            COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count
        FROM appointments
        WHERE appointment_date BETWEEN %s AND %s
    """, (week_start, week_end))
    weekly_totals = cur.fetchone()
    if not weekly_totals:
        weekly_totals = (0, 0, 0, 0)

    # Most booked services
    cur.execute("""
        SELECT
            COALESCE(s.service_name, 'Unknown Service') AS service_name,
            COUNT(*) AS total_booked
        FROM appointments a
        LEFT JOIN services s ON a.service_id = s.service_id
        WHERE a.status IN ('booked', 'completed')
        GROUP BY COALESCE(s.service_name, 'Unknown Service')
        ORDER BY total_booked DESC, service_name ASC
        LIMIT 10
    """)
    most_booked_services = cur.fetchall() or []

    # Cancelled appointments count
    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'cancelled'
    """)
    cancelled_result = cur.fetchone()
    cancelled_count = cancelled_result[0] if cancelled_result else 0

    # Daily revenue
    cur.execute("""
        SELECT COALESCE(SUM(price_at_booking), 0)
        FROM appointments
        WHERE appointment_date = %s
          AND status = 'completed'
    """, (today,))
    daily_revenue = cur.fetchone()[0] or 0

    # Weekly revenue
    cur.execute("""
        SELECT COALESCE(SUM(price_at_booking), 0)
        FROM appointments
        WHERE appointment_date BETWEEN %s AND %s
          AND status = 'completed'
    """, (week_start, week_end))
    weekly_revenue = cur.fetchone()[0] or 0

    # Monthly revenue
    cur.execute("""
        SELECT COALESCE(SUM(price_at_booking), 0)
        FROM appointments
        WHERE appointment_date >= %s
          AND appointment_date < %s
          AND status = 'completed'
    """, (month_start, next_month_start))
    monthly_revenue = cur.fetchone()[0] or 0

    # Monthly completed count
    cur.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE appointment_date >= %s
          AND appointment_date < %s
          AND status = 'completed'
    """, (month_start, next_month_start))
    monthly_completed_count = cur.fetchone()[0] or 0

    # Average ticket this month
    cur.execute("""
        SELECT COALESCE(AVG(price_at_booking), 0)
        FROM appointments
        WHERE appointment_date >= %s
          AND appointment_date < %s
          AND status = 'completed'
          AND price_at_booking IS NOT NULL
    """, (month_start, next_month_start))
    average_ticket = cur.fetchone()[0] or 0

    # Revenue by service for current month
    cur.execute("""
        SELECT
            COALESCE(s.service_name, 'Unknown Service') AS service_name,
            COUNT(*) AS completed_count,
            COALESCE(SUM(a.price_at_booking), 0) AS total_revenue
        FROM appointments a
        LEFT JOIN services s ON a.service_id = s.service_id
        WHERE a.appointment_date >= %s
          AND a.appointment_date < %s
          AND a.status = 'completed'
        GROUP BY COALESCE(s.service_name, 'Unknown Service')
        ORDER BY total_revenue DESC, service_name ASC
    """, (month_start, next_month_start))
    revenue_by_service = cur.fetchall() or []

    cur.close()
    conn.close()

    return render_template(
        "reports.html",
        today=today,
        week_start=week_start,
        week_end=week_end,
        month_start=month_start,
        daily_completed=daily_completed,
        weekly_totals=weekly_totals,
        most_booked_services=most_booked_services,
        cancelled_count=cancelled_count,
        daily_revenue=daily_revenue,
        weekly_revenue=weekly_revenue,
        monthly_revenue=monthly_revenue,
        monthly_completed_count=monthly_completed_count,
        average_ticket=average_ticket,
        revenue_by_service=revenue_by_service
    )


#  -------------------------
#
#    REPORTS BY DATE/RANGE
#
#  ------------------------

from datetime import datetime

@app.route("/reports/range", methods=["GET", "POST"])
def reports_range():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()

    preset = request.form.get("preset") or request.args.get("preset")
    start_date = request.form.get("start_date") or request.args.get("start_date")
    end_date = request.form.get("end_date") or request.args.get("end_date")

    # Quick preset buttons
    if preset == "today":
        start_date = today.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

    elif preset == "this_week":
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        start_date = week_start.strftime("%Y-%m-%d")
        end_date = week_end.strftime("%Y-%m-%d")

    elif preset == "this_month":
        month_start = today.replace(day=1)
        if today.month == 12:
            next_month_start = date(today.year + 1, 1, 1)
        else:
            next_month_start = date(today.year, today.month + 1, 1)
        month_end = next_month_start - timedelta(days=1)

        start_date = month_start.strftime("%Y-%m-%d")
        end_date = month_end.strftime("%Y-%m-%d")

    elif preset == "last_30":
        start_date = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

    formatted_start = None
    formatted_end = None

    if start_date and end_date:
        try:
            formatted_start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%B %d, %Y")
            formatted_end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%B %d, %Y")
        except:
            formatted_start = start_date
            formatted_end = end_date

    report_data = None

    if start_date and end_date:
        # Totals
        cur.execute("""
            SELECT
                COUNT(*) AS total_appointments,
                COUNT(*) FILTER (WHERE status = 'booked') AS booked_count,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count
            FROM appointments
            WHERE appointment_date BETWEEN %s AND %s
        """, (start_date, end_date))
        totals = cur.fetchone() or (0, 0, 0, 0)

        # Revenue
        cur.execute("""
            SELECT COALESCE(SUM(price_at_booking), 0)
            FROM appointments
            WHERE appointment_date BETWEEN %s AND %s
              AND status = 'completed'
        """, (start_date, end_date))
        total_revenue = cur.fetchone()[0] or 0

        # Average ticket
        cur.execute("""
            SELECT COALESCE(AVG(price_at_booking), 0)
            FROM appointments
            WHERE appointment_date BETWEEN %s AND %s
              AND status = 'completed'
              AND price_at_booking IS NOT NULL
        """, (start_date, end_date))
        average_ticket = cur.fetchone()[0] or 0

        # Most booked services
        cur.execute("""
            SELECT
                COALESCE(s.service_name, 'Unknown Service') AS service_name,
                COUNT(*) AS total_booked
            FROM appointments a
            LEFT JOIN services s ON a.service_id = s.service_id
            WHERE a.appointment_date BETWEEN %s AND %s
              AND a.status IN ('booked', 'completed')
            GROUP BY COALESCE(s.service_name, 'Unknown Service')
            ORDER BY total_booked DESC, service_name ASC
            LIMIT 10
        """, (start_date, end_date))
        most_booked_services = cur.fetchall() or []

        # Revenue by service
        cur.execute("""
            SELECT
                COALESCE(s.service_name, 'Unknown Service') AS service_name,
                COUNT(*) AS completed_count,
                COALESCE(SUM(a.price_at_booking), 0) AS total_revenue
            FROM appointments a
            LEFT JOIN services s ON a.service_id = s.service_id
            WHERE a.appointment_date BETWEEN %s AND %s
              AND a.status = 'completed'
            GROUP BY COALESCE(s.service_name, 'Unknown Service')
            ORDER BY total_revenue DESC, service_name ASC
        """, (start_date, end_date))
        revenue_by_service = cur.fetchall() or []

        report_data = {
            "totals": totals,
            "total_revenue": total_revenue,
            "average_ticket": average_ticket,
            "most_booked_services": most_booked_services,
            "revenue_by_service": revenue_by_service
        }

    cur.close()
    conn.close()

    return render_template(
        "reports_range.html",
        start_date=start_date,
        end_date=end_date,
        formatted_start=formatted_start,
        formatted_end=formatted_end,
        preset=preset,
        report_data=report_data
    )



#  -----------------------------
#     CLIENT SECTION
#
#     CLIENT HEALTH PROFILE
#
#  -----------------------------



@app.route("/client_health_profile/<int:client_id>", methods=["GET", "POST"])
def client_health_profile(client_id):
    appointment_id = request.args.get("appointment_id") or request.form.get("appointment_id")
    selected_date = request.args.get("date") or request.form.get("date")
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        sex = request.form.get("sex") or None
        skin_type_id = request.form.get("skin_type_id") or None
        fitzpatrick_id = request.form.get("fitzpatrick_id") or None
        skin_concerns = request.form.get("skin_concerns")
        skin_conditions = request.form.get("skin_conditions")
        allergies = request.form.get("allergies")
        medications = request.form.get("medications")
        current_medical_conditions = request.form.get("current_medical_conditions")
        past_medical_treatments = request.form.get("past_medical_treatments")

        recent_injections = "recent_injections" in request.form
        recent_laser = "recent_laser" in request.form
        pregnant = "pregnant" in request.form
        nursing = "nursing" in request.form
        using_retinol = "using_retinol" in request.form
        using_accutane = "using_accutane" in request.form

        sun_exposure_level = request.form.get("sun_exposure_level")
        last_facial_date = request.form.get("last_facial_date") or None

        notes1 = request.form.get("notes1")
        notes2 = request.form.get("notes2")
        notes3 = request.form.get("notes3")

        cur.execute("""
            SELECT health_profile_id
            FROM client_health_profile
            WHERE client_id = %s
        """, (client_id,))
        existing_profile = cur.fetchone()

        if existing_profile:
            cur.execute("""
                UPDATE client_health_profile
                SET
                    sex = %s,
                    skin_type_id = %s,
                    fitzpatrick_id = %s,
                    skin_concerns = %s,
                    skin_conditions = %s,
                    allergies = %s,
                    medications = %s,
                    current_medical_conditions = %s,
                    past_medical_treatments = %s,
                    recent_injections = %s,
                    recent_laser = %s,
                    pregnant = %s,
                    nursing = %s,
                    using_retinol = %s,
                    using_accutane = %s,
                    sun_exposure_level = %s,
                    last_facial_date = %s,
                    notes1 = %s,
                    notes2 = %s,
                    notes3 = %s,
                    last_updated = CURRENT_DATE
                WHERE client_id = %s
            """, (
                sex,
                skin_type_id,
                fitzpatrick_id,
                skin_concerns,
                skin_conditions,
                allergies,
                medications,
                current_medical_conditions,
                past_medical_treatments,
                recent_injections,
                recent_laser,
                pregnant,
                nursing,
                using_retinol,
                using_accutane,
                sun_exposure_level,
                last_facial_date,
                notes1,
                notes2,
                notes3,
                client_id
            ))
        else:
            cur.execute("""
                INSERT INTO client_health_profile (
                    client_id,
                    sex,
                    skin_type_id,
                    fitzpatrick_id,
                    skin_concerns,
                    skin_conditions,
                    allergies,
                    medications,
                    current_medical_conditions,
                    past_medical_treatments,
                    recent_injections,
                    recent_laser,
                    pregnant,
                    nursing,
                    using_retinol,
                    using_accutane,
                    sun_exposure_level,
                    last_facial_date,
                    notes1,
                    notes2,
                    notes3
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                client_id,
                sex,
                skin_type_id,
                fitzpatrick_id,
                skin_concerns,
                skin_conditions,
                allergies,
                medications,
                current_medical_conditions,
                past_medical_treatments,
                recent_injections,
                recent_laser,
                pregnant,
                nursing,
                using_retinol,
                using_accutane,
                sun_exposure_level,
                last_facial_date,
                notes1,
                notes2,
                notes3
            ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Pre-session intake saved successfully.", "success")

        if appointment_id:
            return redirect(
                url_for(
                    "post_appointment_wrap_up",
                    appointment_id=appointment_id,
                    date=selected_date
                )
            )

        return redirect(url_for("clients_home"))

    cur.execute("""
        SELECT client_id, first_name, last_name
        FROM clients
        WHERE client_id = %s
    """, (client_id,))
    client = cur.fetchone()

    cur.execute("""
        SELECT sex_type_id, sex_type
        FROM sex
        ORDER BY sex_type
    """)
    sex_options = cur.fetchall()

    cur.execute("""
        SELECT skin_type_id, skin_type_name
        FROM skin_types
        ORDER BY skin_type_name
    """)
    skin_types = cur.fetchall()

    cur.execute("""
        SELECT fitzpatrick_id, fitzpatrick_level, description
        FROM fitzpatrick_types
        ORDER BY fitzpatrick_id
    """)
    fitzpatrick_types = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM client_health_profile
        WHERE client_id = %s
    """, (client_id,))
    profile = cur.fetchone()

    cur.close()
    conn.close()

    return render_template(
        "client_health_profile.html",
        client=client,
        appointment_id=appointment_id,
        selected_date=selected_date,
        profile=profile,
        sex_options=sex_options,
        skin_types=skin_types,
        fitzpatrick_types=fitzpatrick_types
    )






    
#  ------------------------------------
#      APPOINTMEENTS
#
#    
#  -----------------------------------


from datetime import date

@app.route("/appointments")
def appointments():
    spa_id = get_current_spa_id()

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    show_all = request.args.get("show_all", "").strip()
    today_str = date.today().isoformat()

    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT
            a.appointment_id,
            a.client_id,
            c.first_name,
            c.last_name,
            s.service_name,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.notes
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        LEFT JOIN service_name_types s
            ON a.service_id = s.service_type_id
           AND a.spa_id = s.spa_id
        WHERE a.spa_id = %s
    """
    params = [spa_id]

    if show_all != "1":
        if start_date and end_date:
            query += " AND a.appointment_date BETWEEN %s AND %s"
            params.extend([start_date, end_date])
        else:
            query += " AND a.appointment_date = %s"
            params.append(today_str)

    query += " ORDER BY a.appointment_date, a.appointment_time"

    cur.execute(query, tuple(params))
    appointments = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "appointments.html",
        appointments=appointments,
        start_date=start_date,
        end_date=end_date,
        today_str=today_str
    )




#  --------------------
#   ADD APPOINTMENT
#
#  ---------------------

@app.route("/add_appointment", methods=["GET", "POST"])
def add_appointment():
    spa_id = get_current_spa_id()
    client_id = request.args.get("client_id") or request.form.get("client_id") or ""
    client_search = (request.args.get("client_search") or request.form.get("client_search") or "").strip()

    conn = get_db_connection()
    cur = conn.cursor()

    selected_date = request.args.get("selected_date", "")

    if request.method == "POST":
        print("FORM KEYS:", list(request.form.keys()))

        client_id = (request.form.get("client_id") or "").strip()
        service_type_id = (request.form.get("service_type_id") or "").strip()
        appointment_date = (request.form.get("appointment_date") or "").strip()
        appointment_time = (request.form.get("appointment_time") or "").strip()
        status = (request.form.get("status") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        incoming_booking_id = request.form.get("incoming_booking_id", "").strip()

        if not service_type_id:
            flash("Service was not submitted. Hard refresh the page and try again.", "error")
            cur.close()
            conn.close()
            return redirect(url_for("add_appointment", selected_date=selected_date))


        cur.execute("""
            INSERT INTO appointments (
                spa_id,
                client_id,
                service_type_id,
                appointment_date,
                appointment_time,
                status,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            spa_id,
            client_id,
            service_type_id,
            appointment_date,
            appointment_time,
            status,
            notes
        ))

        if incoming_booking_id:
            cur.execute("""
                UPDATE incoming_square_bookings
                SET status = 'imported',
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE incoming_booking_id = %s
            """, (incoming_booking_id,))
            session.pop("incoming_booking_data", None)

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("daily_schedule", date=appointment_date))

    client_id = request.args.get("client_id", "")
    incoming_booking_id = request.args.get("incoming_booking_id", "")
    prefill_date = request.args.get("appointment_date", "") or selected_date
    prefill_time = request.args.get("appointment_time", "")
    prefill_service_name = request.args.get("service_name", "")

    client_search = request.args.get("client_search", "").strip()

    if client_search:
        cur.execute("""
            SELECT client_id, first_name, last_name
            FROM clients
            WHERE spa_id = %s
              AND last_name ILIKE %s
            ORDER BY last_name, first_name
        """, (spa_id, f"%{client_search}%"))
    else:
        cur.execute("""
            SELECT client_id, first_name, last_name
            FROM clients
            WHERE spa_id = %s
            ORDER BY last_name, first_name
            LIMIT 25
        """, (spa_id,))

    clients = cur.fetchall()

    cur.execute("""
        SELECT service_type_id, service_name
        FROM service_name_types
        WHERE spa_id = %s
        ORDER BY service_name
    """, (spa_id,))
    service_types = cur.fetchall()


    cur.close()
    conn.close()

    return render_template(
        "add_appointment.html",
        clients=clients,
        service_types=service_types,
        selected_date=selected_date,
        client_id=client_id,
        incoming_booking_id=incoming_booking_id,
        prefill_date=prefill_date,
        prefill_time=prefill_time,
        prefill_service_name=prefill_service_name
    )



#  ---------------------
#
#   EDIT  APPOINTMENT
#
#  -------------------- 

@app.route("/edit_appointment/<int:appointment_id>", methods=["GET", "POST"])
def edit_appointment(appointment_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        appointment_date = request.form["appointment_date"]
        appointment_time = request.form["appointment_time"]
        duration = request.form["duration"]
        room_number = request.form["room_number"]
        notes = request.form["notes"]

        cur.execute("""
            UPDATE appointments
            SET appointment_date = %s,
                appointment_time = %s,
                duration_minutes = %s,
                room_number = %s,
                notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE appointment_id = %s
        """, (appointment_date, appointment_time, duration, room_number, notes, appointment_id))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('daily_schedule', date=appointment_date))

    # GET (load existing data)
    cur.execute("""
        SELECT appointment_id, appointment_date, appointment_time,
               duration_minutes, room_number, notes
        FROM appointments
        WHERE appointment_id = %s
    """, (appointment_id,))
    
    appt = cur.fetchone()

    cur.close()
    conn.close()

    return render_template("edit_appointment.html", appt=appt)



#  ---------------------
#   
#   DELETE  APPOINTMENT
#  
#  --------------------

@app.route("/delete_appointment/<int:appointment_id>", methods=["POST"])
def delete_appointment(appointment_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    # get date before deleting for redirect
    cur.execute("""
        SELECT appointment_date
        FROM appointments
        WHERE appointment_id = %s
          AND spa_id = %s
    """, (appointment_id, spa_id))

    appt = cur.fetchone()

    if not appt:
        cur.close()
        conn.close()
        flash("Appointment not found.", "error")
        return redirect(url_for("appointments"))

    cur.execute("""
        DELETE FROM appointments
        WHERE appointment_id = %s
          AND spa_id = %s
    """, (appointment_id, spa_id))

    conn.commit()
    cur.close()
    conn.close()

    flash("Appointment deleted successfully.", "success")

    return redirect(url_for("appointments", date=appt[0]))

#  ---------------------
#
#   CANCEL APPOINTMENT
#
#  --------------------

@app.route("/cancel_appointment/<int:appointment_id>", methods=["POST"])
def cancel_appointment(appointment_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()  
    cur = conn.cursor()

    # Only allow cancelling future appointments
    cur.execute("""
        UPDATE appointments
        SET status = 'cancelled',
            updated_at = CURRENT_TIMESTAMP
        WHERE appointment_id = %s
          AND (appointment_date + appointment_time) > CURRENT_TIMESTAMP
    """, (appointment_id,))
            
    conn.commit()
    cur.close()
    conn.close()
                
    flash("Appointment cancelled.", "warning") 

    return redirect(url_for("calendar_view", offset=0))






#  -----------------
#     
#   RESCHEDULE   APPOINTMENT
#  
#  
#  -----------------

@app.route("/reschedule_appointment/<int:appointment_id>", methods=["GET", "POST"])
def reschedule_appointment(appointment_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        service_type_id = (request.form.get("service_type_id") or "").strip()
        appointment_date = (request.form.get("appointment_date") or "").strip()
        appointment_time = (request.form.get("appointment_time") or "").strip()
        status = (request.form.get("status") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        original_date = (request.form.get("original_date") or "").strip()

        if not service_type_id or not appointment_date or not appointment_time or not status:
            flash("Please complete all required fields.", "error")
            cur.close()
            conn.close()
            return redirect(url_for("reschedule_appointment", appointment_id=appointment_id))

        cur.execute("""
            UPDATE appointments
            SET
                service_type_id = %s,
                appointment_date = %s,
                appointment_time = %s,
                status = %s,
                notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE appointment_id = %s
              AND spa_id = %s
        """, (
            service_type_id,
            appointment_date,
            appointment_time,
            status,
            notes,
            appointment_id,
            spa_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Appointment rescheduled successfully.", "success")

        if appointment_date:
            return redirect(url_for("daily_schedule", date=appointment_date))

        if original_date:
            return redirect(url_for("daily_schedule", date=original_date))

        return redirect(url_for("appointments"))

    cur.execute("""
        SELECT
            a.appointment_id,
            a.client_id,
            c.first_name,
            c.last_name,
            a.service_type_id,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.notes
        FROM appointments a
        JOIN clients c
          ON a.client_id = c.client_id
        WHERE a.appointment_id = %s
          AND a.spa_id = %s
    """, (appointment_id, spa_id))

    appointment = cur.fetchone()

    if not appointment:
        cur.close()
        conn.close()
        flash("Appointment not found.", "error")
        return redirect(url_for("appointments"))

    cur.execute("""
        SELECT service_type_id, service_name
        FROM service_name_types
        WHERE spa_id = %s
        ORDER BY service_name
    """, (spa_id,))
    service_types = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "reschedule_appointment.html",
        appointment=appointment,
        service_types=service_types
    )












#  -----------------
#
#     COMPLETE APPOINTMENT
#
#
#  -----------------

@app.route("/complete_appointment/<int:appointment_id>", methods=["POST"])
def complete_appointment(appointment_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT appointment_date
        FROM appointments
        WHERE appointment_id = %s
    """, (appointment_id,))
    appt = cur.fetchone()

    cur.execute("""
        UPDATE appointments
        SET status = 'completed',
            updated_at = CURRENT_TIMESTAMP
        WHERE appointment_id = %s
          AND (appointment_date + appointment_time) <= CURRENT_TIMESTAMP
    """, (appointment_id,))

    conn.commit()
    cur.close()
    conn.close()

    if appt:
        return redirect(url_for('daily_schedule', date=appt[0]))
    return redirect(url_for('calendar_view', offset=0))


#  ------------------
#     
#   COMPLETE OVERDUE APPOINTMENTS 
#    
#  -----------------

@app.route("/complete_overdue_appointments", methods=["POST"])
def complete_overdue_appointments():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE appointments
        SET status = 'completed',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'booked'
          AND (appointment_date + appointment_time) < CURRENT_TIMESTAMP
    """)

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('calendar_view', offset=0))



#   -----------------------------
#
#    POST APPOINTMENT WRAP UP
#
#
#
#   ---------------------------



@app.route("/post_appointment_wrap_up/<int:appointment_id>", methods=["GET", "POST"])
def post_appointment_wrap_up(appointment_id):
    spa_id = get_current_spa_id()
    selected_date = request.args.get("date") or request.form.get("date") or ""

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        treatment_notes = request.form.get("treatment_notes", "")
        products_used = request.form.get("products_used", "")
        home_care_advice = request.form.get("home_care_advice", "")
        provider_notes = request.form.get("provider_notes", "")

        cur.execute("""
            INSERT INTO appointment_wrap_up (
                spa_id,
                appointment_id,
                treatment_notes,
                products_used,
                home_care_advice,
                provider_notes
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (appointment_id)
            DO UPDATE SET
                treatment_notes = EXCLUDED.treatment_notes,
                products_used = EXCLUDED.products_used,
                home_care_advice = EXCLUDED.home_care_advice,
                provider_notes = EXCLUDED.provider_notes
        """, (
            spa_id,
            appointment_id,
            treatment_notes,
            products_used,
            home_care_advice,
            provider_notes
        ))


        cur.execute("""
            UPDATE appointments
            SET status = 'Completed'
            WHERE appointment_id = %s
              AND spa_id = %s
        """, (appointment_id, spa_id))

        conn.commit()
        cur.close()
        conn.close()

        flash("Wrap-Up was saved successfully.", "success")
        return redirect(url_for("post_appointment_wrap_up_saved", appointment_id=appointment_id))

        if selected_date:
            return redirect(url_for("daily_schedule", date=selected_date))

        return redirect(url_for("post_appointment_wrap_up", appointment_id=appointment_id))

    cur.execute("""
        SELECT
            a.appointment_id,
            a.appointment_date,
            a.appointment_time,
            c.client_id,
            c.first_name,
            c.last_name
        FROM appointments a
        JOIN clients c
            ON a.client_id = c.client_id
           AND a.spa_id = c.spa_id
        WHERE a.appointment_id = %s
          AND a.spa_id = %s
    """, (appointment_id, spa_id))
    appointment = cur.fetchone()

    cur.execute("""
        SELECT
            treatment_notes,
            products_used,
            home_care_advice,
            provider_notes
        FROM appointment_wrap_up
        WHERE appointment_id = %s
          AND spa_id = %s
    """, (appointment_id, spa_id))
    wrap_up = cur.fetchone()

    cur.close()
    conn.close()

    if not appointment:
        flash("Appointment not found.", "error")
        if selected_date:
            return redirect(url_for("daily_schedule", date=selected_date))
        return redirect(url_for("appointments"))

    return render_template(
        "post_appointment_wrap_up.html",
        appointment=appointment,
        wrap_up=wrap_up,
        selected_date=selected_date
    )





#  ----------------------------
#      POST APPOINTMENT SAVED
#    
#   
#   ---------------------------




@app.route("/post_appointment_wrap_up_saved/<int:appointment_id>")
def post_appointment_wrap_up_saved(appointment_id):


    return render_template(
        "post_appointment_wrap_up_saved.html",
        appointment_id=appointment_id
    )




#  ------------------
#      CLIENT SECTION
#
#    Client History
#  -----------------

@app.route("/client_history")
def client_history():
    spa_id = get_current_spa_id()
    search = request.args.get("search", "")

    conn = get_db_connection()
    cur = conn.cursor()

    if search:
        cur.execute("""
            SELECT client_id, first_name, last_name
            FROM clients
            WHERE LOWER(first_name) LIKE %s
               OR LOWER(last_name) LIKE %s
               OR phone LIKE %s
            ORDER BY last_name
        """, (f"%{search.lower()}%", f"%{search.lower()}%", f"%{search}%"))
    else:
        cur.execute("""
            SELECT client_id, first_name, last_name
            FROM clients
            ORDER BY last_name
        """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("client_history.html", rows=rows, search=search)

#  ------------------
#   Client History Detail page 1
#  -----------------


@app.route("/client_history/<int:client_id>")
def client_history_detail(client_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT client_id, first_name, last_name, phone, email, birth_date
        FROM clients
        WHERE client_id = %s
          AND spa_id = %s
    """, (client_id, spa_id))
    client = cur.fetchone()

    cur.execute("""
        SELECT
            a.appointment_id,
            a.appointment_date,
            a.appointment_time,
            s.service_name,
            a.duration_minutes,
            a.room_number,
            a.status,
            a.notes,
            aw.treatment_notes,
            aw.products_used,
            aw.home_care_advice,
            aw.provider_notes
        FROM appointments a
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        LEFT JOIN appointment_wrap_up aw
            ON a.appointment_id = aw.appointment_id
           AND a.spa_id = aw.spa_id
        WHERE a.client_id = %s
          AND a.spa_id = %s
        ORDER BY a.appointment_date DESC NULLS LAST,
                 a.appointment_time DESC NULLS LAST
    """, (client_id, spa_id))
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "client_history_detail.html",
        rows=rows,
        client=client,
        client_id=client_id
    )






#  ------------------
#    Client History Detail page 2
#  -----------------


@app.route("/client_history_two/<int:client_id>")
def client_history_detail_two(client_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT client_id, first_name, last_name, phone, email, birth_date
        FROM clients
        WHERE client_id = %s
          AND spa_id = %s
    """, (client_id, spa_id))
    client = cur.fetchone()

    cur.execute("""
        SELECT
            a.appointment_id,
            a.appointment_date,
            a.appointment_time,
            s.service_name,
            a.duration_minutes,
            a.room_number,
            a.status,
            a.notes,
            aw.treatment_notes,
            aw.products_used,
            aw.home_care_advice,
            aw.provider_notes
        FROM appointments a
        LEFT JOIN services s
            ON a.service_id = s.service_id
           AND a.spa_id = s.spa_id
        LEFT JOIN appointment_wrap_up aw
            ON a.appointment_id = aw.appointment_id
           AND a.spa_id = aw.spa_id
        WHERE a.client_id = %s
          AND a.spa_id = %s
        ORDER BY a.appointment_date DESC NULLS LAST,
                 a.appointment_time DESC NULLS LAST
    """, (client_id, spa_id))
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "client_history_detail_two.html",
        rows=rows,
        client=client,
        client_id=client_id
    )





#  ---------------------------------
#   ADD NEW CLIENT STEP 1  
#         PAGE 1
#  --------------------------------

@app.route("/add_new_client", methods=["GET", "POST"])
def add_new_client():
    spa_id = get_current_spa_id()
    selected_date = request.args.get("selected_date") or request.form.get("selected_date") or ""
    if request.method == "POST":
        session["new_client_step1"] = {
            "first_name": request.form.get("first_name", ""),
            "last_name": request.form.get("last_name", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "birth_date": request.form.get("birth_date", ""),
            "address": request.form.get("address", ""),
            "city": request.form.get("city", ""),
            "state": request.form.get("state", "TX"),
            "zip": request.form.get("zip", "")
        }
        return redirect(url_for("add_new_client_step2", selected_date=selected_date))

    step1_data = session.get("new_client_step1", {})

    if not step1_data:
        incoming_booking_data = session.get("incoming_booking_data", {})
        if incoming_booking_data:
            step1_data = {
                "first_name": incoming_booking_data.get("first_name", ""),
                "last_name": incoming_booking_data.get("last_name", ""),
                "phone": incoming_booking_data.get("phone", ""),
                "email": incoming_booking_data.get("email", ""),
                "birth_date": "",
                "address": "",
                "city": "",
                "state": "TX",
                "zip": ""
            }

    return render_template("add_new_client.html", selected_date=selected_date,  step1_data=step1_data)




#  ---------------------------------
#   ADD NEW CLIENT STEP 2  
#         PAGE 2
#  --------------------------------


@app.route("/add_new_client_step2", methods=["GET", "POST"])
def add_new_client_step2():
    spa_id = get_current_spa_id()
    selected_date = request.args.get("selected_date") or request.form.get("selected_date") or ""

    if "new_client_step1" not in session:
        return redirect(url_for("add_new_client"))

    if request.method == "POST":
        session["new_client_step2"] = {
            "emergency_contact_name": request.form.get("emergency_contact_name", ""),
            "emergency_contact_phone": request.form.get("emergency_contact_phone", ""),
            "referred_by": request.form.get("referred_by", ""),
            "notes_one": request.form.get("notes_one", ""),
            "notes_two": request.form.get("notes_two", ""),
            "notes_three": request.form.get("notes_three", ""),
            "active_client": request.form.get("active_client", "true")
        }

        action = request.form.get("action")

        if action == "back":
            return redirect(url_for("add_new_client"))

        if action == "save":
            step1 = session.get("new_client_step1", {})
            step2 = session.get("new_client_step2", {})
            incoming_booking_data = session.get("incoming_booking_data", {})

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO clients (
                    first_name,
                    last_name,
                    phone,
                    email,
                    birth_date,
                    address,
                    city,
                    state,
                    zip,
                    emergency_contact_name,
                    emergency_contact_phone,
                    referred_by,
                    notes_one,
                    notes_two,
                    notes_three,
                    active_client
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING client_id
            """, (
                step1.get("first_name", ""),
                step1.get("last_name", ""),
                step1.get("phone", ""),
                step1.get("email", ""),
                step1.get("birth_date") or None,
                step1.get("address", ""),
                step1.get("city", ""),
                step1.get("state", ""),
                step1.get("zip", ""),
                step2.get("emergency_contact_name", ""),
                step2.get("emergency_contact_phone", ""),
                step2.get("referred_by", ""),
                step2.get("notes_one", ""),
                step2.get("notes_two", ""),
                step2.get("notes_three", ""),
                True if step2.get("active_client") == "true" else False
            ))

            new_client_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            flash("Client added successfully!")

            session.pop("new_client_step1", None)
            session.pop("new_client_step2", None)

            if incoming_booking_data:
                return redirect(url_for(
                    "add_appointment",
                    client_id=new_client_id,
                    incoming_booking_id=incoming_booking_data.get("incoming_booking_id", ""),
                    appointment_date=incoming_booking_data.get("appointment_date", ""),
                    appointment_time=incoming_booking_data.get("appointment_time", ""),
                    service_name=incoming_booking_data.get("service_name", "")
                ))

            session.pop("incoming_booking_data", None)

            if selected_date:
                return redirect(url_for(
                    "add_appointment",
                    client_id=new_client_id,
                    selected_date=selected_date
                ))



            return redirect(url_for("client_history"))

    step2_data = session.get("new_client_step2", {})


    return render_template(
        "add_new_client_step2.html", 
        step2_data=step2_data,
        selected_date=selected_date
    )




#  -----------------
#   EDIT CLIENT
#
#  ----------------


@app.route("/edit_client/<int:client_id>", methods=["GET", "POST"])
def edit_client(client_id):
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        first_name = request.form.get("first_name", "")
        last_name = request.form.get("last_name", "")
        phone = request.form.get("phone", "")
        email = request.form.get("email", "")
        birth_date = request.form.get("birth_date") or None
        address = request.form.get("address", "")
        city = request.form.get("city", "")
        state = request.form.get("state", "")
        zip_code = request.form.get("zip", "")
        emergency_contact_name = request.form.get("emergency_contact_name", "")
        emergency_contact_phone = request.form.get("emergency_contact_phone", "")
        referred_by = request.form.get("referred_by", "")
        notes_one = request.form.get("notes_one", "")
        notes_two = request.form.get("notes_two", "")
        notes_three = request.form.get("notes_three", "")
        active_client = True if request.form.get("active_client") == "true" else False

        cur.execute("""
            UPDATE clients
            SET first_name = %s,
                last_name = %s,
                phone = %s,
                email = %s,
                birth_date = %s,
                address = %s,
                city = %s,
                state = %s,
                zip = %s,
                emergency_contact_name = %s,
                emergency_contact_phone = %s,
                referred_by = %s,
                notes_one = %s,
                notes_two = %s,
                notes_three = %s,
                active_client = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE client_id = %s
        """, (
            first_name,
            last_name,
            phone,
            email,
            birth_date,
            address,
            city,
            state,
            zip_code,
            emergency_contact_name,
            emergency_contact_phone,
            referred_by,
            notes_one,
            notes_two,
            notes_three,
            active_client,
            client_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Client updated successfully!")

        return redirect(url_for("client_history"))

    cur.execute("""
        SELECT
            first_name,
            last_name,
            phone,
            email,
            birth_date,
            address,
            city,
            state,
            zip,
            emergency_contact_name,
            emergency_contact_phone,
            referred_by,
            notes_one,
            notes_two,
            notes_three,
            active_client
        FROM clients
        WHERE client_id = %s
    """, (client_id,))

    client = cur.fetchone()

    cur.close()
    conn.close()

    return render_template("edit_client.html", client=client, client_id=client_id)




#  -----------------------
#
#  DELETE CLIENT
#
#  -----------------------

@app.route("/delete_client/<int:client_id>", methods=["POST"])
def delete_client(client_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM clients WHERE client_id = %s", (client_id,))
    flash("Client deleted successfully!")

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("client_history"))










#  -----------------
#   TIME ZONES
#       
#  ----------------





#  -----------------
#    TIME ZONES
#
#  ----------------



from datetime import datetime
from zoneinfo import ZoneInfo

def get_current_spa_timezone():
    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT timezone_name
        FROM spas
        WHERE spa_id = %s
    """, (spa_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    if row and row[0]:
        return row[0]

    return "America/Chicago"


def get_spa_now():
    timezone_name = get_current_spa_timezone()
    return datetime.now(ZoneInfo(timezone_name))


def get_utc_now():
    return datetime.now(ZoneInfo("UTC"))


#   ---------------------------------
#
#    ADMIN PAGE
#
#   --------------------------------



@app.route("/admin")
def admin():

    spa_id = get_current_spa_id()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT timezone_name
        FROM spas
        WHERE spa_id = %s
    """, (spa_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    current_timezone = row[0] if row and row[0] else "America/Chicago"
    utc_now = get_utc_now()
    spa_now = datetime.now(ZoneInfo(current_timezone))


 
    return render_template(
        "admin.html",
        current_timezone=current_timezone,
        utc_now=utc_now,
        spa_now=spa_now
    )      







#  --------------
#
#  SKIN TYPES   DROP DOWN
#
#   DROP DOWN
#  -------------

@app.route("/skin_types", methods=["GET", "POST"])
def skin_types():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        skin_type_name = request.form["skin_type_name"]

        cur.execute("""
            INSERT INTO skin_types (skin_type_name)
            VALUES (%s)
        """, (skin_type_name,))
        conn.commit()

        cur.close()
        conn.close()
        return redirect(url_for("skin_types"))

    cur.execute("""
        SELECT skin_type_id, skin_type_name
        FROM skin_types
        ORDER BY skin_type_id
    """)
    skin_types_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("skin_types.html", skin_types=skin_types_list)

#  ---------------------
#  DELETE SKIN TYPE
#  ---------------------

@app.route("/delete_skin_type/<int:skin_type_id>", methods=["POST"])
def delete_skin_type(skin_type_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM skin_types
        WHERE skin_type_id = %s
    """, (skin_type_id,))
    conn.commit()

    cur.close()
    conn.close()

    return redirect(url_for("skin_types"))

#  -------------------
#
#  FITZPATRICK DROP DOWN
#
#  ------------------

@app.route("/fitzpatrick_types", methods=["GET", "POST"])
def fitzpatrick_types():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        fitzpatrick_level = request.form["fitzpatrick_level"]
        description = request.form["description"]

        cur.execute("""
            INSERT INTO fitzpatrick_types (fitzpatrick_level, description)
            VALUES (%s, %s)
        """, (fitzpatrick_level, description))

        conn.commit()
        cur.close()
        conn.close()

        flash("Fitzpatrick type added successfully.")
        return redirect(url_for("fitzpatrick_types"))

    cur.execute("""
        SELECT fitzpatrick_id, fitzpatrick_level, description
        FROM fitzpatrick_types
        ORDER BY fitzpatrick_id
    """)
    fitzpatrick_types = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("fitzpatrick_types.html", fitzpatrick_types=fitzpatrick_types)

#  ----------------------
#
#    DELETE FITZPATRICK TYPE
#
#  ---------------------

@app.route("/delete_fitzpatrick_types/<int:fitzpatrick_id>", methods=["POST"])
def delete_fitzpatrick_types(fitzpatrick_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()
        
    cur.execute("""
        DELETE FROM fitzpatrick_types
        WHERE fitzpatrick_id = %s
    """, (fitzpatrick_id,))
                
    conn.commit()
    cur.close()
    conn.close()

    flash("Fitzpatrick type deleted successfully!")
    return redirect(url_for("fitzpatrick_types"))



#  -----------------------
#
#    EDIT FITZPATRICK TYPE
#
#  -----------------------

@app.route("/edit_fitzpatrick_types/<int:fitzpatrick_id>", methods=["GET", "POST"])
def edit_fitzpatrick_types(fitzpatrick_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        fitzpatrick_level = request.form["fitzpatrick_level"]
        description = request.form["description"]

        cur.execute("""
            UPDATE fitzpatrick_types
            SET fitzpatrick_level = %s,
                description = %s
            WHERE fitzpatrick_id = %s
        """, (fitzpatrick_level, description, fitzpatrick_id))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("fitzpatrick_types"))

    cur.execute("""
        SELECT fitzpatrick_id, fitzpatrick_level, description
        FROM fitzpatrick_types
        WHERE fitzpatrick_id = %s
    """, (fitzpatrick_id,))
    fitzpatrick = cur.fetchone()

    cur.close()
    conn.close()

    flash("Fitzpatrick type updated successfully.")
    return redirect(url_for("fitzpatrick_types"))


    return render_template("edit_fitzpatrick_types.html", fitzpatrick=fitzpatrick)


#  -----------------------
#     	DROP DOWN
#  
#    REFERRAL SOURCES
#  -----------------------

@app.route("/referral_sources", methods=["GET", "POST"])
def referral_sources():
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        referral_source_name = request.form["referral_source_name"]

        cur.execute("""
            INSERT INTO referral_sources (referral_source_name)
            VALUES (%s)
        """, (referral_source_name,))
        conn.commit()

        cur.close()
        conn.close()
        return redirect(url_for("referral_sources"))

    cur.execute("""
        SELECT referral_source_id, referral_source_name
        FROM referral_sources
        ORDER BY referral_source_id
    """)
    referral_sources_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("referral_sources.html", referral_sources=referral_sources_list)

#  --------------------
#
#   DELETE REFERRAL SOURCE
#
#  -------------------

@app.route("/delete_referral_source/<int:referral_source_id>", methods=["POST"])
def delete_referral_source(referral_source_id):
    spa_id = get_current_spa_id()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM referral_sources
        WHERE referral_source_id = %s
    """, (referral_source_id,))
    conn.commit()

    cur.close()
    conn.close()

    return redirect(url_for("referral_sources"))



#  -------------------
#   CLEARS ADD NEW FORM
#  ------------------

@app.route("/cancel_new_client")
def cancel_new_client():
    spa_id = get_current_spa_id()
    session.pop("new_client_step1", None)
    session.pop("new_client_step2", None)
    return redirect(url_for("home"))




@app.route("/clear_new_client")
def clear_new_client():
    spa_id = get_current_spa_id()
    session.pop("new_client_step1", None)
    session.pop("new_client_step2", None)
    return redirect(url_for("add_new_client"))






#   ----------------------------
#  ------------------------------
#  ---------------------------------
#    END   END   END   END   END
#  --------------------------------


if __name__ == "__main__":
    app.run(debug=True, port=5001)
