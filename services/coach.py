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


def get_day_greeting():
    hour = datetime.now().hour

    if hour < 12:
        return "Good morning."
    elif hour < 17:
        return "Good afternoon."
    return "Good evening."


def add_observation(observations, category, priority, status, message, action_url=None):
    observations.append({
        "category": category,
        "priority": priority,
        "status": status,
        "message": message,
        "action_url": action_url
    })


def review_business_schedule(observations, business_schedule_due=None, business_schedule_upcoming=None):
    business_schedule_due = business_schedule_due or []
    business_schedule_upcoming = business_schedule_upcoming or []

    if business_schedule_due:
        first_item = business_schedule_due[0]

        add_observation(
            observations,
            category="Business Schedule",
            priority=100,
            status="attention",
            message=f"One business responsibility needs attention today: {first_item[2]}.",
            action_url=None
        )
        return

    if business_schedule_upcoming:
        next_item = business_schedule_upcoming[0]

        add_observation(
            observations,
            category="Business Schedule",
            priority=35,
            status="upcoming",
            message=f"Your next business schedule item is {next_item[2]}.",
            action_url=None
        )
        return

    add_observation(
        observations,
        category="Business Schedule",
        priority=10,
        status="good",
        message="Your business schedule looks clear right now.",
        action_url=None
    )


def review_priority_actions(
    observations,
    priority_actions=None,
    action_url=None
):
    priority_actions = priority_actions or []

    if not priority_actions:
        add_observation(
            observations,
            category="Priority Actions",
            priority=20,
            status="informational",
            message=(
                "There are no important tasks requiring "
                "your immediate attention today."
            ),
            action_url=None
        )
        return

    task_count = len(priority_actions)
    first_task = priority_actions[0]
    first_task_name = first_task[2]

    if task_count == 1:
        message = (
            f"One important task requires your attention: "
            f"{first_task_name}."
        )

        question = "Would you like to review it now?"

    else:
        message = (
            f"{task_count} important tasks require your attention. "
            f"The first is {first_task_name}."
        )

        question = "Would you like to review the remaining tasks now?"

    add_observation(
        observations,
        category="Priority Actions",
        priority=100,
        status="attention",
        message=message,
        action_url=action_url,
        question=question
    )



def review_today_schedule(observations, dashboard):
    appointments_today = dashboard.get("appointments_today", 0) or 0
    expected_revenue = dashboard.get("expected_revenue", 0) or 0
    next_appointment = dashboard.get("next_appointment")

    if appointments_today == 0:
        add_observation(
            observations,
            category="Today's Schedule",
            priority=60,
            status="opportunity",
            message=(
                "There are no appointments scheduled today, "
                "giving you an opportunity to focus on your business."
            ),
            action_url=None
        )
        return

    if appointments_today >= 5:
        message = (
            f"You have a full schedule today with "
            f"{appointments_today} appointments"
        )
    else:
        message = (
            f"You have {appointments_today} appointment"
            f"{'' if appointments_today == 1 else 's'} scheduled today"
        )

    if expected_revenue and expected_revenue > 0:
        message += (
            f", with projected revenue of "
            f"${expected_revenue:,.2f}"
        )

    message += "."

    if next_appointment:
        next_time = format_appointment_time(next_appointment[0])

        if next_time:
            message += f" Your next appointment is at {next_time}."

    add_observation(
        observations,
        category="Today's Schedule",
        priority=30,
        status="informational",
        message=message,
        action_url=None
    )




def build_coach(
    dashboard,
    business_schedule_due=None,
    business_schedule_upcoming=None,
    priority_actions=None
):
    observations = []

    review_today_schedule(
        observations,
        dashboard=dashboard
    )

    review_business_schedule(
        observations,
        business_schedule_due=business_schedule_due,
        business_schedule_upcoming=business_schedule_upcoming
    )

    review_priority_actions(
        observations,
        priority_actions=priority_actions
    )

    attention_observations = [
        item for item in observations
        if item["status"] == "attention"
    ]

    informational_observations = [
        item for item in observations
        if item["status"] in (
            "informational",
            "good",
            "upcoming",
            "opportunity"
        )
    ]

    if attention_observations:
        best_observation = max(
            attention_observations,
            key=lambda item: item["priority"]
        )

        coach = {
            "title": "🍑 Coach",
            "message": (
                f"{get_day_greeting()} "
                "I've completed today's business review. "
                f"{best_observation['message']}"
            ),
            "question": "Would you like to review it?",
            "yes_label": "Yes",
            "yes_url": best_observation.get("action_url"),
            "no_label": "No",
            "reason": best_observation["category"],
            "priority": best_observation["priority"],
            "observations": observations
        }

        return coach

    if informational_observations:
        best_info = max(
            informational_observations,
            key=lambda item: item["priority"]
        )

        coach = {
            "title": "🍑 Coach",
            "message": (
                f"{get_day_greeting()} "
                "I've completed today's business review. "
                f"{best_info['message']}"
            ),
            "question": None,
            "yes_label": "Yes",
            "yes_url": None,
            "no_label": "No",
            "reason": best_info["category"],
            "priority": best_info["priority"],
            "observations": observations
        }

        return coach

    coach = {
        "title": "🍑 Coach",
        "message": (
            f"{get_day_greeting()} "
            "I've completed today's business review. "
            "Nothing needs your attention right now."
        ),
        "question": None,
        "yes_label": "Yes",
        "yes_url": None,
        "no_label": "No",
        "reason": "All Clear",
        "priority": 10,
        "observations": observations
    }

    return coach