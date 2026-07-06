# q_launch_registry.py

Q_LAUNCH_ITEMS = [
    {
        "title": "Morning Briefing",
        "endpoint": "morning_briefing",
        "category": "Business",
        "group": "Favorites",
        "icon": "🌅",
        "keywords": [
            "dashboard",
            "briefing",
            "today",
            "daily",
            "summary"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Daily overview of appointments, revenue, reminders, and business health."
    },

    {
        "title": "Send SMS",
        "endpoint": "sms_home",
        "category": "Communications",
        "group": "Messaging",
        "icon": "💬",
        "keywords": [
            "sms",
            "text",
            "message",
            "client message",
            "send text"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Send compliant SMS messages to selected clients."
    },

    {
        "title": "SMS_Templates",
        "endpoint": "sms_home",
        "endpoint_args": {
            "channel": "sms"
        },
        "category": "Communications",
        "group": "Messaging",
        "icon": "📝",
        "keywords": [
            "sms",
            "templates",
            "text templates",
            "message templates"
        ],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review and manage approved SMS templates."
    },

    {
        "title": "Client Contact Preferences",
        "endpoint": "client_contact_preferences",
        "category": "Communications",
        "group": "Messaging",
        "icon": "📝",
        "keywords": [
            "contact",
            "preferences",
            "opt",
            "opt-in",
            "opt-out",
            "sms",
            "email",
            "text",
            "unsubscribe",
            "subscribe",
            "consent",
            "marketing",
            "communication"
        ],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review and manage approved client contact preferences."
    },

    {
        "title": "System Activity",
        "endpoint": "system_activity",
        "category": "Administration",
        "group": "System",
        "icon": "⚙️",
        "keywords": [
            "activity",
            "logs",
            "system",
            "security",
            "audit",
            "warnings",
            "alerts"
        ],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review recent system activity, warnings, and alerts."
    },
]