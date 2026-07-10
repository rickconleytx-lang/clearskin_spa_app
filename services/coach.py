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


def add_observation(
    observations,
    category,
    priority,
    status,
    message,
    action_url=None,
    question=None
):
    observations.append({
        "category": category,
        "priority": priority,
        "status": status,
        "message": message,
        "action_url": action_url,
        "question": question
    })


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
        action_url = action.get("url")
        action_priority = action.get("priority", 80)

        if action_value == 1:
            message = (
                f"One item requires attention: {action_name}."
            )
        else:
            message = (
                f"{action_value} items require attention: "
                f"{action_name}."
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
            question=(
                f"Would you like to review "
                f"{action_name.lower()}?"
            )
        )


def review_today_schedule(observations, dashboard):
    appointment_count = dashboard.get("appointments_today", 0) or 0
    projected_revenue = dashboard.get("expected_income_today", 0) or 0
    next_appointment = dashboard.get("next_appointment")

    if appointment_count == 0:
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

    if appointment_count >= 5:
        message = (
            f"You have a full schedule today with "
            f"{appointment_count} appointments"
        )
    else:
        message = (
            f"You have {appointment_count} appointment"
            f"{'' if appointment_count == 1 else 's'} scheduled today"
        )

    if projected_revenue > 0:
        message += (
            f", with projected revenue of "
            f"${projected_revenue:,.2f}"
        )

    message += "."

    if next_appointment:
        next_time = format_appointment_time(next_appointment[0])

        if next_time:
            message += f" Your next appointment begins at {next_time}."

    add_observation(
        observations,
        category="Today's Schedule",
        priority=30,
        status="informational",
        message=message,
        action_url=None
    )




def build_today_summary(dashboard):
    appointment_count = dashboard.get("appointments_today", 0) or 0
    projected_revenue = dashboard.get("expected_income_today", 0) or 0
    next_appointment = dashboard.get("next_appointment")

    if appointment_count == 1:
        appointment_summary = (
            f"You have 1 appointment scheduled today with projected "
            f"revenue of ${projected_revenue:,.2f}."
        )
    else:
        appointment_summary = (
            f"You have {appointment_count} appointments scheduled today "
            f"with projected revenue of ${projected_revenue:,.2f}."
        )

    next_appointment_time = None

    if next_appointment and next_appointment[0]:
        next_appointment_time = format_appointment_time(
            next_appointment[0]
        )

    if next_appointment_time:
        next_appointment_summary = (
            f"Your next appointment begins at "
            f"{next_appointment_time}."
        )
    elif appointment_count > 0:
        next_appointment_summary = (
            "There are no additional appointments remaining today."
        )
    else:
        next_appointment_summary = (
            "You do not have any appointments scheduled today."
        )

    return {
        "appointment_count": appointment_count,
        "projected_revenue": projected_revenue,
        "appointment_summary": appointment_summary,
        "next_appointment_summary": next_appointment_summary
    }



def build_recommendation_summary(recommendations):
    recommendation_count = len(recommendations)

    if recommendation_count == 1:
        return {
            "count": 1,
            "summary": "I have one recommendation ready.",
            "question": "Would you like to review it?"
        }

    if recommendation_count > 1:
        return {
            "count": recommendation_count,
            "summary": (
                f"I have {recommendation_count} "
                "recommendations ready."
            ),
            "question": "Would you like to review them?"
        }

    return {
        "count": 0,
        "summary": "Nothing needs your attention right now.",
        "question": None
    }



def build_day_assessment(appointment_count, recommendations):
    recommendation_count = len(recommendations)

    if appointment_count == 0:
        return (
            "Today may be a good opportunity to focus on client "
            "follow-up and business development."
        )

    if recommendation_count >= 3:
        return (
            "Your schedule is active, and there are a few items "
            "that would benefit from your attention."
        )

    if recommendation_count > 0:
        return "Overall, today looks manageable."

    return "Overall, today looks well balanced."



def build_coach(
    dashboard,
    business_schedule_due=None,
    business_schedule_upcoming=None,
    priority_actions=None
):
    observations = []

    # ---------------------------------------------------------
    # Complete the business review
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # Prioritize all observations
    # ---------------------------------------------------------
    observations.sort(
        key=lambda item: item.get("priority", 0),
        reverse=True
    )

    recommendations = [
        item for item in observations
        if item.get("status") in (
            "attention",
            "opportunity"
        )
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
        item for item in observations
        if item.get("status") in (
            "informational",
            "good",
            "upcoming"
        )
    ]

    # ---------------------------------------------------------
    # Build the executive summary
    # ---------------------------------------------------------
    today_summary = build_today_summary(dashboard)

    day_assessment = build_day_assessment(
        appointment_count=today_summary["appointment_count"],
        recommendations=recommendations
    )

    recommendation_intro = build_recommendation_summary(
        recommendations
    )

    current_recommendation = (
        recommendations[0]
        if recommendations
        else None
    )

    greeting = get_day_greeting()

    message = " ".join([
        greeting,
        "I've completed today's business review.",
        today_summary["appointment_summary"],
        today_summary["next_appointment_summary"],
        day_assessment,
        recommendation_intro["summary"]
    ])

    return {
    "title": "🍑 Coach",
    "greeting": greeting,
    "appointment_summary": (
        today_summary["appointment_summary"]
    ),
    "next_appointment_summary": (
        today_summary["next_appointment_summary"]
    ),
    "day_assessment": day_assessment,
    "recommendation_summary": (
        recommendation_intro["summary"]
    ),
    "message": message,
    "question": recommendation_intro["question"],
    "yes_label": "Yes",
    "no_label": "No",
    "yes_url": (
        current_recommendation.get("action_url")
        if current_recommendation
        else None
    ),
    "reason": (
        current_recommendation.get("category")
        if current_recommendation
        else "All Clear"
    ),
    "priority": (
        current_recommendation.get("priority", 10)
        if current_recommendation
        else 10
    ),
    "conversation_state": (
        "recommendations_ready"
        if recommendations
        else "complete"
    ),
    "current_recommendation_index": 0,
    "total_recommendations": len(recommendations),
    "current_recommendation": current_recommendation,
    "recommendations": recommendations,
    "recommendation_count": (
        recommendation_intro["count"]
    ),
    "informational_observations": (
        informational_observations
    ),
    "observations": observations
}