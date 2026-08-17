from datetime import datetime, time


def format_appointment_time(value):
    if not value:
        return None

    if isinstance(value, time):
        return value.strftime("%-I:%M %p")

    if isinstance(value, datetime):
        return value.strftime("%-I:%M %p")

    if isinstance(value, str):
        for time_format in ("%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.strptime(value, time_format)
                return parsed_time.strftime("%-I:%M %p")
            except ValueError:
                continue

    return str(value)




def get_day_greeting(spa_now):
    hour = spa_now.hour

    if hour < 12:
        return "Good morning."
    elif hour < 17:
        return "Good afternoon." 
    return "Good evening." 



def get_review_intro(
    spa_now,
    coach_open_count=1
):
    """
    Returns Coach's opening statement based on local time
    and today's Daily Briefing visit count.
    """

    hour = spa_now.hour

    # First visit of the business day
    if coach_open_count <= 1:
        if hour < 12:
            return "I've completed today's business review."

        if hour < 17:
            return "I've updated your business review."

        return (
            "I've wrapped up today's business review "
            "and looked ahead to tomorrow."
        )

    # Rotate return-visit wording
    return_visit_number = (coach_open_count - 2) % 4

    if return_visit_number == 0:
        return (
            "Welcome back. I've reviewed the latest "
            "business activity."
        )

    if return_visit_number == 1:
        return (
            "I've taken another look at today's priorities "
            "and current schedule."
        )

    if return_visit_number == 2:
        return (
            "Welcome back. I've refreshed your business review "
            "and checked for anything new."
        )

    return (
        "I've reviewed the business again and updated "
        "today's operational picture."
    )




def get_day_assessment_intro(spa_now):
    hour = spa_now.hour

    if hour < 12:
        return (
            "Today may be a good opportunity to focus on "
            "client follow-up and business development."
        )

    elif hour < 17:
        return (
            "There is still time today to focus on "
            "client follow-up and business development."
        )

    return (
        "This may be a good time to focus on client "
        "follow-up, business development, or preparing "
        "for tomorrow."
    )


def add_observation(
    observations,
    category,
    priority,
    status,
    message,
    action_url=None,
    question=None,
    action_label=None
):
    observations.append({
        "category": category,
        "priority": priority,
        "status": status,
        "message": message,
        "action_url": action_url,
        "question": question,
        "action_label": action_label
    })



def add_recommendation(
    recommendations,
    category,
    priority,
    summary,
    question,
    action_label=None,
    action_url=None,
    recommendation_key=None
):
    recommendations.append({
        "category": category,
        "priority": priority,
        "summary": summary,
        "question": question,
        "action_label": action_label,
        "action_url": action_url,
        "recommendation_key": recommendation_key
    })


def select_top_recommendation(recommendations):
    if not recommendations:
        return None

    return sorted(
        recommendations,
        key=lambda item: item.get("priority", 0),
        reverse=True
    )[0]


def review_business_schedule(
    observations,
    business_schedule_due=None,
    business_schedule_upcoming=None
):
    business_schedule_due = business_schedule_due or []
    business_schedule_upcoming = business_schedule_upcoming or []

    if business_schedule_due:
        first_item = business_schedule_due[0]

        item_title = first_item[2]
        schedule_id = first_item[0]

        add_observation(
            observations,
            category="Business Schedule",
            priority=100,
            status="attention",
            message=(
                f"One business responsibility needs attention today: "
                f"{item_title}."
            ),
            action_url=None,
            question=(
                f"Would you like to review {item_title}?"
            )
        )
        return

    if business_schedule_upcoming:
        next_item = business_schedule_upcoming[0]

        add_observation(
            observations,
            category="Business Schedule",
            priority=35,
            status="upcoming",
            message=(
                f"Your next business schedule item is "
                f"{next_item[2]}."
            ),
            action_url=None,
            question=None
        )
        return

    add_observation(
        observations,
        category="Business Schedule",
        priority=10,
        status="good",
        message=(
            "Your business schedule is clear for the next 14 days."
        ),
        action_url=None,
        question=None
    )


def review_recurring_expense_alerts(
    observations,
    dashboard
):
    recurring_expense_alerts = (
        dashboard.get(
            "recurring_expense_alerts",
            []
        )
        or []
    )

    if not recurring_expense_alerts:
        return

    alert = recurring_expense_alerts[0]

    observations.append({
        "category": "Recurring Expense Posted",
        "priority": 115,
        "status": "attention",
        "message": alert.get(
            "message",
            "A recurring expense was posted automatically."
        ),
        "action_url": None,
        "question": (
            "Would you like to review this automatic "
            "payment update?"
        ),
        "recommendation_type": (
            "recurring_expense_alert"
        ),
        "occurrence_id": alert.get(
            "occurrence_id"
        ),
    })




def review_priority_actions(
    observations,
    priority_actions=None
):
    priority_actions = priority_actions or []

    if not priority_actions:
        add_observation(
            observations,
            category="Priority Actions",
            priority=20,
            status="informational",
            message=(
                "There are no priority actions requiring "
                "your attention right now."
            ),
            action_url=None,
            question=None
        )
        return

    for action in priority_actions:
        action_name = action.get(
            "label",
            "an important business task"
        )

        action_value = action.get("value", 0) or 0
        action_url = action.get(
            "coach_url",
            action.get("url")
        )
        action_priority = action.get("priority", 80)

        coach_message = action.get("coach_message")
        coach_question = action.get("coach_question")

        if coach_message:
            message = str(coach_message)

        elif action_value == 1:
            message = (
                f"One item requires attention: {action_name}."
            )

        else:
            message = (
                f"{action_value} items require attention: "
                f"{action_name}."
            )

        if not coach_question:
            coach_question = (
                f"Would you like to review "
                f"{action_name.lower()}?"
            )

        add_observation(
            observations,
            category=action.get(
                "category",
                "Priority Actions"
            ),
            priority=action_priority,
            status="attention",
            message=message,
            action_url=action_url,
            question=coach_question,
            action_label=action.get(
                "coach_action_label"
            )
        )


def review_overdue_appointments(observations, dashboard):
    overdue_appointments = (
        dashboard.get("overdue_appointments", [])
        or []
    )

    overdue_count = len(overdue_appointments)

    if overdue_count == 0:
        return

    add_observation(
        observations,
        category="Overdue Appointments",
        priority=100,
        status="attention",
        message=(
            f"You have {overdue_count} overdue appointment"
            f"{'' if overdue_count == 1 else 's'} "
            "that are still marked as booked and need to be closed out."
        ),
        question=(
            "Would you like to review "
            f"{'this overdue appointment' if overdue_count == 1 else 'these overdue appointments'} "
            "now?"
        ),
        action_url="/appointments?filter=overdue&from_coach=1"

    )


    overdue_appointments = (
        dashboard.get("overdue_appointments", [])
        or []
    )

    

    overdue_count = len(overdue_appointments)

    if overdue_count == 0:
        return

    add_observation(
        observations,
        category="Overdue Appointments",
        priority=100,
        status="attention",
        message=(
            f"You have {overdue_count} past appointment"
            f"{'' if overdue_count == 1 else 's'} "
            "that are still marked as booked and need to be closed out."
        ),
        question=(
            "Would you like to review "
            f"{'this overdue appointment' if overdue_count == 1 else 'these overdue appointments'} "
            "now?"
        ),
        action_url=None
    )


def review_today_schedule(
    observations,
    dashboard,
    spa_now
):
    if spa_now is None:
        raise ValueError(
            "review_today_schedule requires spa_now"
        )

    appointment_count = (
        dashboard.get("appointments_today", 0) or 0
    )

    remaining_count = (
        dashboard.get("appointments_remaining_today", 0) or 0
    )

    tomorrow_count = (
        dashboard.get("appointments_tomorrow", 0) or 0
    )

    projected_revenue = (
        dashboard.get("expected_income_today", 0) or 0
    )

    remaining_revenue = (
        dashboard.get("expected_income_remaining_today", 0) or 0
    )

    tomorrow_revenue = (
        dashboard.get("expected_income_tomorrow", 0) or 0
    )

    next_appointment = dashboard.get("next_appointment")

    # ---------------------------------------------------------
    # Appointments remain today
    # ---------------------------------------------------------
    if remaining_count > 0:
        if remaining_count >= 5:
            message = (
                f"You have a full remaining schedule with "
                f"{remaining_count} appointments still scheduled today"
            )
        else:
            message = (
                f"You have {remaining_count} appointment"
                f"{'' if remaining_count == 1 else 's'} "
                f"remaining today"
            )

        if remaining_revenue > 0:
            message += (
                f", with projected remaining revenue of "
                f"${remaining_revenue:,.2f}"
            )
        elif projected_revenue > 0:
            message += (
                f". Total projected revenue for today is "
                f"${projected_revenue:,.2f}"
            )

        message += "."

        if next_appointment:
            next_time = format_appointment_time(
            next_appointment.get(
                "appointment_time"
            )
        )

            if next_time:
                message += (
                    f" Your next appointment begins at "
                    f"{next_time}."
                )

        add_observation(
            observations,
            category="Today's Schedule",
            priority=40,
            status="informational",
            message=message,
            action_url=None
        )
        return



    # ---------------------------------------------------------
    # No appointments remain today — look ahead to tomorrow
    # ---------------------------------------------------------
    if appointment_count > 0:
        message = "Today's appointments are complete."
    else:
        message = "There are no appointments scheduled today."

    if tomorrow_count > 0:
        message += (
            f" Tomorrow you have {tomorrow_count} appointment"
            f"{'' if tomorrow_count == 1 else 's'} scheduled"
        )

        if tomorrow_revenue > 0:
            message += (
                f", with projected revenue of "
                f"${tomorrow_revenue:,.2f}"
            )

        message += "."
    else:
        message += (
            " You don't have any appointments scheduled for tomorrow."
        )

    add_observation(
        observations,
        category="Tomorrow's Schedule",
        priority=30,
        status="informational",
        message=message,
        action_url=None
    )





def review_appointment_reminders(
    observations,
    dashboard,
    spa_now
):
    """
    Identify the next appointment that does not have a successful
    reminder recorded for its current appointment date and time.
    """

    if spa_now is None:
        raise ValueError(
            "review_appointment_reminders requires spa_now"
        )

    next_appointment = (
        dashboard.get("next_appointment") or {}
    )

    if not isinstance(next_appointment, dict):
        return

    if not next_appointment:
        return

    if next_appointment.get("reminder_sent"):
        return

    appointment_id = next_appointment.get(
        "appointment_id"
    )

    if not appointment_id:
        return

    appointment_time = next_appointment.get(
        "appointment_time"
    )

    appointment_for = (
        next_appointment.get("appointment_for")
        or next_appointment.get("client_name")
        or "The client"
    )

    phone = (
        next_appointment.get("phone") or ""
    ).strip()

    email = (
        next_appointment.get("email") or ""
    ).strip()

    sms_available = (
        bool(phone)
        and bool(next_appointment.get("sms_opt_in"))
        and not bool(next_appointment.get("sms_opt_out"))
    )

    email_available = (
        bool(email)
        and bool(next_appointment.get("email_opt_in"))
        and not bool(next_appointment.get("email_opt_out"))
    )

    # There is no eligible reminder channel.
    if not sms_available and not email_available:
        return

    formatted_time = format_appointment_time(
        appointment_time
    )

    if sms_available and email_available:
        channel_text = "SMS or email"

    elif sms_available:
        channel_text = "SMS"

    else:
        channel_text = "email"

    message = (
        f"{appointment_for} has an appointment today"
    )

    if formatted_time:
        message += f" at {formatted_time}"

    message += (
        ", and no reminder has been recorded for the current "
        f"appointment time. {channel_text} is available."
    )

    add_observation(
        observations,
        category="Appointment Reminder",
        priority=55,
        status="attention",
        message=message,
        question=(
            "Would you like to prepare this reminder now?"
        ),

        # We will add the direct reminder URL next.
        # Leaving this blank prevents a broken redirect.
        action_url=(
            f"/appointments"
            f"?appointment_id={appointment_id}"
            f"&from_coach=1"
            f"&coach_action=reminder"
        )
    )





def build_today_summary(dashboard):
    return {
        "appointment_count": (
            dashboard.get("appointments_today", 0) or 0
        ),
        "projected_revenue": (
            dashboard.get("expected_income_today", 0) or 0
        ),
        "next_appointment": (
            dashboard.get("next_appointment")
        )
    }


def build_recommendation_summary(recommendations):
    """
    Builds a short internal summary.

    Coach immediately presents the first recommendation instead
    of announcing that a recommendation queue exists.
    """

    recommendation_count = len(recommendations)

    if recommendation_count == 0:
        return {
            "count": 0,
            "summary": "Nothing needs your attention right now.",
            "question": None
        }

    return {
        "count": recommendation_count,
        "summary": "",
        "question": None
    }



def build_day_assessment(
    appointment_count,
    recommendations,
    spa_now
):
    recommendation_count = len(
        recommendations
    )

    highest_priority = (
        recommendations[0]
        if recommendations
        else None
    )

    priority_category = (
        highest_priority.get("category", "")
        if highest_priority
        else ""
    )

    # ---------------------------------------------------------
    # No appointments scheduled today
    # ---------------------------------------------------------
    if appointment_count == 0:

        if priority_category == "Overdue Appointments":
            return (
                "You have overdue appointments that still need "
                "to be closed out, so I recommend reviewing those "
                "before moving on to client follow-up or business "
                "development."
            )

        if priority_category == "GoDaddy Imports":
            return (
                "Your schedule is open today, making this a good "
                "time to review the imported appointments that "
                "still need your attention."
            )

        if priority_category == "Business Schedule":
            return (
                "Your schedule is open today, so I recommend "
                "addressing the business tasks that are currently "
                "due before moving on to other projects."
            )

        if priority_category == "Recurring Expenses":
            return (
                "Your schedule is open today, making this a good "
                "time to review the recurring expense item that "
                "needs your attention."
            )

        if highest_priority:
            return (
                "Your schedule is open today, so I recommend "
                f"reviewing {priority_category.lower()} before "
                "moving on to client follow-up or business "
                "development."
            )

        return get_day_assessment_intro(
            spa_now
        )

    # ---------------------------------------------------------
    # Active appointment schedule
    # ---------------------------------------------------------
    if recommendation_count >= 3:
        return (
            "Your schedule is active, and there are several "
            "business items that would benefit from your attention."
        )

    if priority_category == "Overdue Appointments":
        return (
            "Your schedule looks manageable, but you have overdue "
            "appointments that still need to be closed out."
        )

    if priority_category == "GoDaddy Imports":
        return (
            "Your schedule looks manageable, but imported "
            "appointments are still waiting for your review."
        )

    if recommendation_count > 0:
        return (
            "Overall, today looks manageable. I found one business "
            "item that would benefit from your attention."
        )

    return (
        "Overall, today looks well balanced."
    )



def review_seven_day_outlook(
    observations,
    dashboard
):
    """
    Review the rolling seven-day appointment outlook.

    The main outlook remains informational. Open days may create
    a low-priority scheduling opportunity, but they are not treated
    as an operational problem.
    """

    outlook = dashboard.get(
        "seven_day_outlook"
    ) or {}

    if not outlook:
        return

    total_appointments = int(
        outlook.get("total_appointments") or 0
    )

    projected_revenue = float(
        outlook.get("projected_revenue") or 0
    )

    busiest_day = (
        outlook.get("busiest_day")
    )

    highest_revenue_day = outlook.get(
        "highest_revenue_day"
    )

    next_open_day = outlook.get(
        "next_open_day"
    )

    all_days = outlook.get("days") or []

    open_days = outlook.get("open_days") or []

    outlook_start_date = outlook.get(
        "start_date"
    )

    future_open_days = []

    for open_day in open_days:
        if isinstance(open_day, dict):
            open_day_date = open_day.get("date")

            # Exclude today from the forward-looking open-day message.
            if (
                outlook_start_date is not None
                and open_day_date is not None
                and open_day_date <= outlook_start_date
            ):
                continue

        future_open_days.append(
            open_day
        )

    open_day_count = len(
        future_open_days
    )

    booked_day_count = int(
        outlook.get("booked_day_count") or 0
    )


    open_day_names = []

    for open_day in future_open_days:
        if isinstance(open_day, dict):
            day_name = (
                open_day.get("day_name")
                or open_day.get("display_date")
                or open_day.get("date_display")
                or open_day.get("date")
            )
        else:
            day_name = str(open_day)

        if day_name:
            open_day_names.append(
                str(day_name)
            )

    open_day_count = len(
        future_open_days
    )


    booked_day_count = int(
        outlook.get("booked_day_count") or 0
    )

    # Used only for the future open-day wording.
    open_day_count = len(
        future_open_days
    )

    days_in_window = int(
        outlook.get("days_in_window") or 7
    )

    # Use the true booked-day count from the dashboard.
    booked_day_count = int(
        outlook.get("booked_day_count") or 0
    )

    # ---------------------------------------------------------
    # Format open-day names safely
    # ---------------------------------------------------------
    open_day_names = []

    for open_day in future_open_days:

        if isinstance(open_day, dict):
            day_name = (
                open_day.get("day_name")
                or open_day.get("display_date")
                or open_day.get("date")
            )
        else:
            day_name = str(open_day)

        if day_name:
            open_day_names.append(
                str(day_name)
            )

    # ---------------------------------------------------------
    # Completely open seven-day schedule
    # ---------------------------------------------------------
    if total_appointments == 0:

        observations.append({
            "category": "7-Day Outlook",
            "status": "informational",
            "priority": 20,
            "message": (
                "There are currently no booked appointments "
                "during the next seven days. Your upcoming "
                "schedule remains open."
            )
        })

        return

    # ---------------------------------------------------------
    # Informational scheduling opportunity
    # ---------------------------------------------------------
    if open_day_count >= 3:
        observations.append({
            "category": "Scheduling Opportunity",
            "status": "informational",
            "priority": 25,
            "message": (
                f"You currently have {open_day_count} future "
                "open days during the next seven days. Consider "
                "using that availability for client follow-up, "
                "rebooking outreach, or business development."
            )
        })


    appointment_word = (
        "appointment"
        if total_appointments == 1
        else "appointments"
    )

    message_parts = [
        (
            f"You have {total_appointments} "
            f"{appointment_word} scheduled during the next "
            f"seven days, with projected revenue of "
            f"${projected_revenue:,.2f}."
        )
    ]

    # ---------------------------------------------------------
    # Busiest day
    # ---------------------------------------------------------

    if busiest_day:
        busiest_count = int(
            busiest_day.get("appointment_count") or 0
        )

        busiest_day_name = (
            busiest_day.get("day_name")
            or busiest_day.get("display_date")
            or "The busiest day"
        )

        days_with_busiest_count = [
            day
            for day in outlook.get("days", [])
            if int(day.get("appointment_count") or 0)
            == busiest_count
            and busiest_count > 0
        ]

        if (
            busiest_count == 1
            and len(days_with_busiest_count) > 1
        ):
            message_parts.append(
                (
                    f"The appointments are evenly spread across "
                    f"{len(days_with_busiest_count)} days, with one "
                    "appointment scheduled on each day."
                )
            )

        elif len(days_with_busiest_count) > 1:
            tied_day_names = ", ".join(
                day.get("day_name", "")
                for day in days_with_busiest_count
                if day.get("day_name")
            )

            message_parts.append(
                (
                    f"{tied_day_names} are tied as the busiest days "
                    f"with {busiest_count} appointments each."
                )
            )

        else:
            busiest_word = (
                "appointment"
                if busiest_count == 1
                else "appointments"
            )

            message_parts.append(
                (
                    f"{busiest_day_name} is currently the busiest "
                    f"day with {busiest_count} {busiest_word}."
                )
            )

        if highest_revenue_day:
            highest_revenue_amount = float(
                highest_revenue_day.get(
                    "projected_revenue"
                ) or 0
            )

            highest_revenue_name = (
                highest_revenue_day.get("day_name")
                or highest_revenue_day.get("display_date")
                or "The highest-revenue day"
            )

            busiest_date = (
                busiest_day.get("date")
                if busiest_day
                else None
            )

            highest_revenue_date = (
                highest_revenue_day.get("date")
            )

            # Mention it separately only when it adds new information.
            if (
                highest_revenue_amount > 0
                and highest_revenue_date != busiest_date
            ):
                message_parts.append(
                    (
                        f"{highest_revenue_name} currently has the "
                        f"highest projected revenue at "
                        f"${highest_revenue_amount:,.2f}."
                    )
                )   

    # ---------------------------------------------------------
    # Active and open days
    # ---------------------------------------------------------
    

    if open_day_count > 0:

        next_open_day_name = None

        if next_open_day:
            next_open_day_name = (
                next_open_day.get("day_name")
                or next_open_day.get("display_date")
                or next_open_day.get("date_display")
            )

        if next_open_day_name:
            if open_day_count == 1:
                message_parts.append(
                    (
                        f"Your next open day is "
                        f"{next_open_day_name}."
                    )
                )
            else:
                remaining_open_days = (
                    open_day_count - 1
                )

                message_parts.append(
                    (
                        f"Your next open day is "
                        f"{next_open_day_name}, with "
                        f"{remaining_open_days} additional open "
                        f"{'day' if remaining_open_days == 1 else 'days'} "
                        f"during the outlook period."
                    )
                )

    elif open_day_names:
        if len(open_day_names) == 1:
            message_parts.append(
                (
                    f"{open_day_names[0]} currently has no "
                    "booked appointments."
                )
            )
        else:
            open_days_text = ", ".join(
                open_day_names[:3]
            )

            remaining_count = max(
                len(open_day_names) - 3,
                0
            )

            if remaining_count:
                message_parts.append(
                    (
                        f"Open days include {open_days_text}, "
                        f"with {remaining_count} additional "
                        f"open {'day' if remaining_count == 1 else 'days'}."
                    )
                )
            else:
                message_parts.append(
                    (
                        f"The open days are currently "
                        f"{open_days_text}."
                    )
                )

    elif open_day_names:
        first_open_days = ", ".join(
            open_day_names[:3]
        )

        remaining_count = (
            len(open_day_names) - 3
        )

        message_parts.append(
            (
                f"Open days include {first_open_days}, "
                f"with {remaining_count} additional "
                f"open {'day' if remaining_count == 1 else 'days'}."
            )
        )

    else:
        message_parts.append(
            (
                f"{open_day_count} days currently have no "
                "booked appointments."
            )
        )

    observations.append({
        "category": "7-Day Outlook",
        "status": "upcoming",
        "priority": 30,
        "message": " ".join(
            message_parts
        )
    })

    # ---------------------------------------------------------
    # Informational scheduling opportunity
    # ---------------------------------------------------------
    if open_day_count >= 3:

        observations.append({
            "category": "Scheduling Opportunity",
            "status": "informational",
            "priority": 25,
            "message": (
                f"You currently have {open_day_count} future "
                "open days during the next seven days. Consider "
                "using that availability for client follow-up, "
                "rebooking outreach, or business development."
            )
        })


#############################################
#################################################
#
#   BUILD COACH
#
#
###############################################



def build_coach(
    dashboard,
    business_schedule_due=None,
    business_schedule_upcoming=None,
    priority_actions=None,
    spa_now=None,
    coach_session=None
):

    if spa_now is None:
        raise ValueError("build_coach requires spa_now")

    coach_session = coach_session or {}

    coach_open_count = coach_session.get(
        "open_count",
        1
    ) or 1

    is_return_visit = coach_open_count > 1

    print(
        "[COACH DEBUG] open_count:",
        coach_open_count
    )

    observations = []

    # ---------------------------------------------------------
    # Complete the business review
    # ---------------------------------------------------------
    review_overdue_appointments(
        observations,
        dashboard=dashboard
    )

    review_today_schedule(
        observations,
        dashboard=dashboard,
        spa_now=spa_now
    )

    review_appointment_reminders(
        observations,
        dashboard=dashboard,
        spa_now=spa_now
    )

    review_seven_day_outlook(
        observations,
        dashboard=dashboard
    )

    review_business_schedule(
        observations,
        business_schedule_due=business_schedule_due,
        business_schedule_upcoming=business_schedule_upcoming
    )

    review_recurring_expense_alerts(
        observations,
        dashboard=dashboard
    )

    review_priority_actions(
        observations,
        priority_actions=priority_actions
    )

    review_priority_actions(
        observations,
        priority_actions=priority_actions
    )

    # ---------------------------------------------------------
    # Remove duplicate observations
    # ---------------------------------------------------------
    unique_observations = []
    seen_observations = set()

    for observation in observations:

        observation_key = (
            observation.get("category"),
            observation.get("status"),
            observation.get("message"),
            observation.get("action_url")
        )

        if observation_key in seen_observations:
            continue

        seen_observations.add(
            observation_key
        )

        unique_observations.append(
            observation
        )

    observations = unique_observations

    # ---------------------------------------------------------
    # Prioritize all observations
    # ---------------------------------------------------------
    observations.sort(
        key=lambda item: item.get("priority", 0),
        reverse=True
    )

    acknowledged_categories = set(
        coach_session.get(
            "acknowledged_categories",
            []
        ) or []
    )


    recommendation_mentions = (
        coach_session.get(
            "recommendation_mentions",
            {}
        ) or {}
    )

    if not isinstance(
        recommendation_mentions,
        dict
    ):
        recommendation_mentions = {}

    try:
        overdue_mention_count = int(
            recommendation_mentions.get(
                "Overdue Appointments",
                0
            ) or 0
        )
    except (TypeError, ValueError):
        overdue_mention_count = 0

    auto_paused_categories = set()

    if overdue_mention_count >= 1:
        auto_paused_categories.add(
            "Overdue Appointments"
        )

    print(
        "[COACH MENTION DEBUG]",
        recommendation_mentions
    )

    print(
        "[COACH AUTO PAUSED]",
        auto_paused_categories
    )

    print(
        "[COACH ACK DEBUG]",
        acknowledged_categories
    )

    recommendations = [
        item
        for item in observations
        if item.get("status") in (
            "attention",
            "opportunity"
        )
        and item.get("category")
        not in acknowledged_categories
        and item.get("category")
        not in auto_paused_categories
    ]

    for index, recommendation in enumerate(
        recommendations,
        start=1
    ):
        recommendation["queue_position"] = index
        recommendation["recommendation_id"] = (
            f"recommendation_{index}"
        )

    informational_observations = [
        item
        for item in observations
        if item.get("status") in (
            "informational",
            "good",
            "upcoming"
        )
    ]

    # ---------------------------------------------------------
    # Build the executive summary
    # ---------------------------------------------------------
    today_summary = build_today_summary(
        dashboard
    )

    day_assessment = build_day_assessment(
        appointment_count=today_summary[
            "appointment_count"
        ],
        recommendations=recommendations,
        spa_now=spa_now
    )

    recommendation_intro = (
        build_recommendation_summary(
            recommendations
        )
    )

    # ---------------------------------------------------------
    # Rotate recommendations when Coach is reopened
    # ---------------------------------------------------------
    current_recommendation_index = 0
    current_recommendation = None

    current_recommendation_mention_count = 0
    is_pause_offer = False

    if recommendations:

        saved_index = coach_session.get(
            "current_recommendation_index"
        )

        if saved_index is not None:
            try:
                current_recommendation_index = int(
                    saved_index
                )
            except (TypeError, ValueError):
                current_recommendation_index = 0

            current_recommendation_index %= len(
                recommendations
            )

        else:
            current_recommendation_index = (
                coach_open_count - 1
            ) % len(recommendations)

        current_recommendation = recommendations[
            current_recommendation_index
        ]

        # ---------------------------------------------------------
        # Check how often this recommendation was mentioned today
        # ---------------------------------------------------------
        recommendation_mentions = (
            coach_session.get(
                "recommendation_mentions",
                {}
            ) or {}
        )

        if not isinstance(
            recommendation_mentions,
            dict
        ):
            recommendation_mentions = {}

        current_recommendation_mention_count = 0
        

        if current_recommendation:
            current_category = (
                current_recommendation.get(
                    "category",
                    ""
                )
            )

            try:
                current_recommendation_mention_count = int(
                    recommendation_mentions.get(
                        current_category,
                        0
                    ) or 0
                )
            except (TypeError, ValueError):
                current_recommendation_mention_count = 0





    greeting = get_day_greeting(
        spa_now
    )

    # ---------------------------------------------------------
    # Select the most useful schedule message
    # ---------------------------------------------------------
    schedule_observation = next(
        (
            item.get("message", "")
            for item in observations
            if item.get("category") in (
                "Today's Schedule",
                "Tomorrow's Schedule"
            )
        ),
        ""
    )

    seven_day_observation = next(
        (
            item.get("message", "")
            for item in observations
            if item.get("category") == "7-Day Outlook"
        ),
        ""
    )

    review_intro = get_review_intro(
        spa_now,
        coach_open_count=coach_open_count
    )

    print(
        "[COACH DEBUG] review_intro:",
        review_intro
    )

    message_parts = [
        greeting,
        review_intro,
        schedule_observation,
        seven_day_observation,
        day_assessment
    ]

    if not current_recommendation:
        message_parts.append(
            recommendation_intro["summary"]
        )

    message = " ".join(
        part.strip()
        for part in message_parts
        if part and part.strip()
    )

    # ---------------------------------------------------------
    # Build the opening Coach interaction
    # ---------------------------------------------------------
    recommendation_title = None
    recommendation_message = None
    opening_question = None



    yes_label = "Yes"
    no_label = "No"

    if current_recommendation:

        recommendation_title = (
            current_recommendation.get(
                "category",
                "Business Recommendation"
            )
        )

        recommendation_message = (
            current_recommendation.get(
                "message",
                "This item needs your attention."
            )
        )

        if is_pause_offer:
            recommendation_title = (
                "Overdue Appointment Reminders"
            )

            opening_question = (
                "I’ve mentioned the overdue appointments "
                "a few times today. Would you like me to "
                "pause these reminders until tomorrow?"
            )

            yes_label = "Pause Until Tomorrow"
            no_label = "Keep Reminding Me"
            conversation_state = "pause_offer"

        else:
            opening_question = (
                current_recommendation.get(
                    "question"
                )
                or
                "Would you like to review this recommendation now?"
            )

            conversation_state = (
                "recommendation_offer"
            )

    else:
        conversation_state = "complete"

    return {
        "title": "🍑 Coach",
        "greeting": greeting,

        "day_assessment": day_assessment,

        "recommendation_summary": (
            recommendation_intro["summary"]
        ),

        "message": message,

        "recommendation_title": (
            recommendation_title
        ),

        "recommendation_message": (
            recommendation_message
        ),

        "is_return_visit": is_return_visit,
        "open_count": coach_open_count,

        "question": opening_question,
        "yes_label": yes_label,
        "no_label": no_label,

        "is_pause_offer": is_pause_offer,

        "current_recommendation_mention_count": (
            current_recommendation_mention_count
        ),

        "yes_url": (
            current_recommendation.get(
                "action_url"
            )
            if current_recommendation
            else None
        ),

        "reason": (
            current_recommendation.get(
                "category"
            )
            if current_recommendation
            else "All Clear"
        ),

        "priority": (
            current_recommendation.get(
                "priority",
                10
            )
            if current_recommendation
            else 10
        ),

        "conversation_state": (
            conversation_state
        ),

        "current_recommendation_index": (
            current_recommendation_index
        ),

        "total_recommendations": len(
            recommendations
        ),

        "has_more_recommendations": (
            len(recommendations) > 1
        ),

        "current_recommendation": (
            current_recommendation
        ),

        "recommendations": recommendations,

        "recommendation_count": (
            recommendation_intro["count"]
        ),

        "informational_observations": (
            informational_observations
        ),

        "observations": observations
    }






def build_action_cards(
    dashboard,
    priority_actions=None
):
    """
    Build the four highest-priority action cards for
    the Daily Briefing.
    """

    priority_actions = priority_actions or []

    cards = []

    # Existing priority actions become cards
    for action in priority_actions:
        cards.append({
            "priority": action.get("priority", 50),
            "icon": action.get("icon", "📌"),
            "title": action.get("label", "Action"),
            "message": str(
                action.get(
                    "card_message",
                    action.get("value", "")
                )
            ),
            "button": action.get("button", "View"),
            "url": action.get("url")
        })

    # Overdue Appointments Card
    overdue_appointments = dashboard.get(
        "overdue_appointments",
        []
    )

    overdue_count = len(overdue_appointments)

    if overdue_count > 0:
        cards.append({
            "priority": 100,
            "icon": "⚠️",
            "title": "Overdue Appointments",
            "message": (
                f"{overdue_count} appointment"
                f"{'' if overdue_count == 1 else 's'} "
                "require review."
            ),
            "button": "Review",
            "url": "/appointments?filter=overdue&from_coach=1"
        })

    # Revenue Card
    if dashboard["appointments_today"] > 0:

        cards.append({
            "priority": 20,
            "icon": "💰",
            "title": "Today's Revenue",
            "message": (
                f"{dashboard['appointments_today']} appointment"
                f"{'' if dashboard['appointments_today'] == 1 else 's'} • "
                f"${dashboard['expected_revenue']:.2f} projected"
            ),
            "button": "View",
            "url": "/reports"
        })

        # Seven-Day Outlook Card
    seven_day_outlook = (
        dashboard.get("seven_day_outlook") or {}
    )

    seven_day_appointments = int(
        seven_day_outlook.get(
            "total_appointments",
            0
        ) or 0
    )

    seven_day_revenue = float(
        seven_day_outlook.get(
            "projected_revenue",
            0
        ) or 0
    )

    seven_day_start = seven_day_outlook.get(
        "start_date"
    )

    seven_day_end = seven_day_outlook.get(
        "end_date"
    )

    appointments_tomorrow = int(
        dashboard.get(
            "appointments_tomorrow",
            0
        ) or 0
    )

    if (
        seven_day_appointments > appointments_tomorrow
        and seven_day_start
        and seven_day_end
    ):
        cards.append({
            "priority": 15,
            "icon": "📅",
            "title": "Next 7 Days",
            "message": (
                f"{seven_day_appointments} appointment"
                f"{'' if seven_day_appointments == 1 else 's'} • "
                f"${seven_day_revenue:,.2f} projected"
            ),
            "button": "View",
            "url": (
                "/appointments?"
                f"start_date={seven_day_start.isoformat()}"
                f"&end_date={seven_day_end.isoformat()}"
                "&from_coach=1"
            )
        })



    cards.sort(
        key=lambda c: c["priority"],
        reverse=True
    )

    return cards[:4]
