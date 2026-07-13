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


def get_review_intro(spa_now):
    """
    Returns Coach's opening business review statement
    based on the business-local time.
    """

    hour = spa_now.hour

    if hour < 12:
        return "I've completed today's business review."

    elif hour < 17:
        return "I've updated your business review."

    return (
        "I've wrapped up today's business review "
        "and looked ahead to tomorrow."
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
            "that still need to be closed out."
        ),
        action_url=None

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
                next_appointment[0]
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

def build_day_assessment(
    appointment_count,
    recommendations,
    spa_now
):
    recommendation_count = len(recommendations)

    if appointment_count == 0:
        return get_day_assessment_intro(spa_now)

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
    priority_actions=None,
    spa_now=None
):
   
    if spa_now is None:
        raise ValueError("build_coach requires spa_now")

    observations = []

    # ---------------------------------------------------------
    # Complete the business review
    # ---------------------------------------------------------
    review_overdue_appointments(
        observations,
        dashboard=dashboard,
    )

    review_today_schedule(
        observations,
        dashboard=dashboard,
        spa_now=spa_now
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
    today_summary = build_today_summary(
        dashboard,
    )

    day_assessment = build_day_assessment(
        appointment_count=today_summary["appointment_count"],
        recommendations=recommendations,
        spa_now=spa_now
    )

    recommendation_intro = build_recommendation_summary(
        recommendations
    )

    current_recommendation = (
        recommendations[0]
        if recommendations
        else None
    )

    greeting = get_day_greeting(spa_now)

    schedule_observation = next(
        (
            item["message"]
            for item in observations
            if item["category"] in (
                "Today's Schedule",
                "Tomorrow's Schedule"
            )
        ),
        ""
    )

    message_parts = [
        greeting,
        get_review_intro(spa_now),
        schedule_observation,
        day_assessment,
        recommendation_intro["summary"]
    ]

    message = " ".join(
        part.strip()
        for part in message_parts
        if part and part.strip()
    )

    # ---------------------------------------------------------
    # Build the opening Coach interaction
    # ---------------------------------------------------------
    if current_recommendation:
        opening_question = "Would you like to review it?"
        conversation_state = "recommendation_offer"
    else:
        opening_question = None
        conversation_state = "complete"

    return {
        "title": "🍑 Coach",
        "greeting": greeting,


        "day_assessment": day_assessment,

        "recommendation_summary": (
            recommendation_intro["summary"]
        ),

        "message": message,

        "question": opening_question,
        "yes_label": "Yes",
        "no_label": "No",

        # Yes reveals the recommendation without navigating.
        "yes_url": None,

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

        "conversation_state": conversation_state,

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
            "message": str(action.get("value", "")),
            "button": "View",
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


    cards.sort(
        key=lambda c: c["priority"],
        reverse=True
    )

    return cards[:4]
