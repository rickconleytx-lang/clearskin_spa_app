# q_launch_registry.py

Q_LAUNCH_ITEMS = [

    {
        "title": "Morning Briefing",
        "endpoint": "morning_briefing",
        "category": "- Business",
        "group": "Favorites",
        "icon": "🌅",
        "keywords": [
            "dashboard",
            "briefing",
            "today",
            "daily",
            "Coach",
            "coach",
            "coach peach",
            "Coach Peach",
            "overdue",
            "imports",
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
        "category": "- Communications",
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
        "category": "- Communications",
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
        "category": "- Communications",
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
        "category": "- Administration",
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


    {
        "title": "Business Summary",
        "endpoint": "reports",
        "category": "- Main",
        "group": "Home",
        "icon": "🏠",
        "keywords": [
            "home", 
            "main", 
            "business score",
            "score",
            "graph",
            "performance",
            "business",
            "business performance",
            "reports",
            "week",
            "daily",
            "today",
            "monthly",
            "month",
            "revenue",
            "appointments",
            "cancellation",
            "no shows",
            "total clients",
            "clients",
            "goals",
            "overview", 
            "dashboard"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "View the main Peach Suite Pro dashboard."
    },

    
    {
        "title": "Calendar",
        "endpoint": "calendar_view",
        "category": "- Scheduling",
        "group": "Appointments",
        "icon": "📅",
        "keywords": ["calendar", "schedule", "appointments", "booking"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "View and manage the appointment calendar."
    },

    {
        "title": "Appointments",
        "endpoint": "appointments",
        "category": "- Scheduling",
        "group": "Appointments",
        "icon": "🗓️",
        "keywords": [
            "appointments", 
            "bookings", 
            "overdue",
            "overdue appointments",
            "add",
            "edit appointment",
            "edit",
            "reschedule",
            "delete",
            "view",
            "manage",
            "cancel",
            "delete",
            "history",
            "appointment history",
            "date",
            "schedule", 
            "reschedule", 
            "cancel"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Search, view, and manage appointments."
    },

    {
        "title": "Client Management",
        "endpoint": "clients_home",
        "category": "- Clients",
        "group": "Client Management",
        "icon": "👥",
        "keywords": [
            "clients", 
            "customers", 
            "add",
            "view",
            "delete",
            "manage",
            "gift certificates",
            "birthday",
            "contact preferences",
            "SMS",
            "Email",
            "add appointment",
            "record",
            "health intake",
            "visit",
            "visit summary",
            "forms",
            "consent history",
            "full record",
            "add new client",
            "Opt In/Out",
            "people", 
            "client management"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Search and manage client records."
    },

    {
        "title": "Add Client",
        "endpoint": "add_new_client",
        "category": "- Clients",
        "group": "Client Management",
        "icon": "➕",
        "keywords": ["add client", "new client", "create client", "customer"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Create a new client profile."
    },

    {
        "title": "Client Contact Preferences",
        "endpoint": "client_contact_preferences",
        "category": "- Communications",
        "group": "Messaging",
        "icon": "📝",
        "keywords": [
            "opt-out",
            "opt-in",
            "opt",
            "sms",
            "email",
            "messaging",
            "contact preferences",
            "consent"
        ],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review and manage approved client contact preferences."
    },

    {
        "title": "Communications",
        "endpoint": "communications",
        "category": "- Communications",
        "group": "Messaging",
        "icon": "💬",
        "keywords": ["communications", "messages", "sms", "email", "contact"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Open the communications center."
    },

    {
        "title": "Send SMS",
        "endpoint": "sms_home",
        "category": "Communications",
        "group": "SMS",
        "icon": "📱",
        "keywords": ["sms", "text", "send sms", "message clients"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Send compliant SMS messages to clients."
    },

    {
        "title": "Send Email",
        "endpoint": "general_email",
        "category": "Communications",
        "group": "Email",
        "icon": "✉️",
        "keywords": ["email", "send email", "message clients", "general email"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Send email messages to clients."
    },

    {
        "title": "SMS History",
        "endpoint": "sms_home",
        "category": "Communications",
        "group": "SMS",
        "icon": "📜",
        "keywords": ["sms history", "text history", "sent sms", "message log"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review sent SMS messages."
    },

    {
        "title": "Email History",
        "endpoint": "email_history",
        "category": "Communications",
        "group": "Email",
        "icon": "📨",
        "keywords": ["email history", "sent email", "email log"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review sent email messages."
    },

    {
        "title": "Reminder Queue",
        "endpoint": "reminder_queue",
        "category": "Communications",
        "group": "Automation",
        "icon": "⏰",
        "keywords": ["reminders", "queue", "automation", "appointment reminders"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review pending client reminders and follow-ups."
    },

    {
        "title": "Messaging Compliance",
        "endpoint": "messaging_compliance_dashboard",
        "category": "Admin",
        "group": "Compliance",
        "icon": "🛡️",
        "keywords": ["compliance", "sms compliance", "10dlc", "messaging"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage messaging compliance and onboarding."
    },

    {
        "title": "SMS Template Library",
        "endpoint": "messaging_compliance_dashboard",
        "endpoint_args": {"channel": "sms"},
        "category": "Communications",
        "group": "Templates",
        "icon": "📱",
        "keywords": ["sms templates", "template library", "text templates"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage approved SMS message templates."
    },

    {
        "title": "Email Template Library",
        "endpoint": "messaging_compliance_dashboard",
        "endpoint_args": {"channel": "email"},
        "category": "Communications",
        "group": "Templates",
        "icon": "✉️",
        "keywords": ["email templates", "template library", "message templates"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage approved email message templates."
    },

    {
        "title": "Income",
        "endpoint": "income_home",
        "category": "Financials",
        "group": "Revenue",
        "icon": "💵",
        "keywords": ["income", "revenue", "sales", "tax", "sales tax", "money"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review and manage income records."
    },

    {
        "title": "Expenses",
        "endpoint": "expenses_home",
        "category": "Financials",
        "group": "Expenses",
        "icon": "💸",
        "keywords": [
            "expenses", 
            "bills", 
            "costs", 
            "recurring",
            "recurring expenses",
            "schedule",
            "expense schedule",
            "rent",
            "equipment",
            "supplies",
            "square",
            "processor fees",
            "spending"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review and manage business expenses."
    },

    {
        "title": "Inventory",
        "endpoint": "inventory_home",
        "category": "Inventory",
        "group": "Products",
        "icon": "📦",
        "keywords": [
            "inventory", 
            "products", 
            "stock", 
            "cost",
            "restock",
            "returned",
            "damaged",
            "wholesale",
            "quantity",
            "vendor",
            "manufactorer",
            "company",
            "supplier",
            "low",
            "scan",
            "smartphone",
            "camera",
            "reorder",
            "out of stock",
            "stock",
            "tax", 
            "retail",
            "sales", 
            "supplies"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Manage products, stock, and inventory movements."
    },

    {
        "title": "Reports",
        "endpoint": "income_report",
        "category": "Reports",
        "group": "Business Reports",
        "icon": "📊",
        "keywords": [
            "reports", 
            "analytics", 
            "summary", 
            "income", 
            "retail",
            "wholesale",
            "gross",
            "services",
            "tax", 
            "tips", 
            "IRS",
            "revenue", 
            "business reports"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Open the reports center."
    },

    {
        "title": "Financial Reports",
        "endpoint": "financial_reports_home",
        "category": "Reports",
        "group": "Financials",
        "icon": "📈",
        "keywords": [
            "financial reports", 
            "revenue reports", 
            "income reports", 
            "expense reports"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review financial reporting pages."
    },

    {
        "title": "Employees",
        "endpoint": "employees_home",
        "category": "Business",
        "group": "Team",
        "icon": "👤",
        "keywords": ["employees", "staff", "team", "pay", "compensation", "workers"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Manage employee and team information."
    },

    {
        "title": "Help Center",
        "endpoint": "help_center",
        "category": "Support",
        "group": "Help",
        "icon": "❔",
        "keywords": ["help", "support", "documentation", "instructions"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Search help pages and documentation."
    },

    {
        "title": "Feedback",
        "endpoint": "feedback",
        "category": "Support",
        "group": "Feedback",
        "icon": "💡",
        "keywords": ["feedback", "suggestion", "bug", "idea"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Submit feedback, issues, or feature ideas."
    },

    {
        "title": "Admin",
        "endpoint": "admin",
        "category": "Admin",
        "group": "Administration",
        "icon": "⚙️",
        "keywords": ["admin", "settings", "management", "control"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Open the admin center."
    },

    {
        "title": "System Activity",
        "endpoint": "system_activity",
        "category": "Admin",
        "group": "System",
        "icon": "🧾",
        "keywords": ["system activity", "logs", "activity", "history", "timeline"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review system activity and internal history."
    },

    {
        "title": "System Logs",
        "endpoint": "system_activity",
        "category": "Admin",
        "group": "System",
        "icon": "🧾",
        "keywords": ["system logs", "logs", "errors", "warnings", "activity"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review application logs, warnings, and errors."
    },

    {
        "title": "Credit Processors",
        "endpoint": "credit_processors",
        "category": "Admin",
        "group": "Financial Settings",
        "icon": "💳",
        "keywords": ["credit processors", "payment processors", "square", "fees"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage payment processor settings."
    },

    {
        "title": "Business Settings",
        "endpoint": "spa_management",
        "category": "Admin",
        "group": "Business Settings",
        "icon": "🏢",
        "keywords": ["business settings", "spa settings", "profile", "timezone", "settings"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage business profile and configuration."
    },

    {
        "title": "Gift Certificates",
        "endpoint": "gift_certificates_home",
        "category": "Sales",
        "group": "Gift Certificates",
        "icon": "🎁",
        "keywords": [
            "gift",
            "gift certificate",
            "gift card",
            "certificate",
            "voucher",
            "present"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Sell, redeem, and manage gift certificates."
    },

    {
        "title": "Birthday Messages",
        "endpoint": "birthday_offers_home",
        "category": "Communications",
        "group": "Automation",
        "icon": "🎂",
        "keywords": [
            "birthday",
            "birthday sms",
            "birthday email",
            "birthday messages",
            "automation"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Review and send birthday communications."
    },

    {
        "title": "Income",
        "endpoint": "income_home",
        "category": "Financials",
        "group": "Accounting",
        "icon": "💰",
        "keywords": [
            "income",
            "revenue",
            "sales",
            "payments",
            "money",
            "tips",
            "retail",
            "tax",
            "sales tax",
            "deposit"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Record and review business income."
    },

    {
        "title": "Expenses",
        "endpoint": "expenses_home",
        "category": "Financials",
        "group": "Accounting",
        "icon": "💸",
        "keywords": [
            "expenses",
            "bills",
            "vendors",
            "costs",
            "recurring",
            "redurring expense",
            "rent",
            "supplies",
            "payments",
            "spending"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Record and review business expenses."
    },

    {
        "title": "Recurring Expenses",
        "endpoint": "automatic_expenses",
        "category": "Financials",
        "group": "Accounting",
        "icon": "💸",
        "keywords": [
            "expenses",
            "bills",
            "vendors",
            "costs",
            "recurring",
            "redurring expense",
            "rent",
            "supplies",
            "payments",
            "spending"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Record and review business expenses."
    },

    {
        "title": "Add Recurring Expense",
        "endpoint": "add_automatic_expense",
        "category": "- Financials",
        "group": "Accounting",
        "icon": "💸",
        "keywords": [
            "expenses",
            "bills",
            "vendors",
            "costs",
            "recurring",
            "redurring expense",
            "rent",
            "supplies",
            "payments",
            "spending"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Record and review business expenses."
    },

    {
        "title": "Reports Center",
        "endpoint": "reports",
        "category": "Reports",
        "group": "Business Reports",
        "icon": "📊",
        "keywords": [
            "reports",
            "analytics",
            "statistics",
            "business reports",
            "summary",
            "kpi"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Open the business reports center."
    },

    {
        "title": "Business Summary",
        "endpoint": "reports",
        "category": "Reports",
        "group": "Dashboards",
        "icon": "📈",
        "keywords": [
            "business summary",
            "summary",
            "dashboard",
            "performance",
            "kpi",
            "metrics"
        ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "View business performance and key metrics."
    },

    {
        "title": "Revenue Dashboard",
        "endpoint": "income_home",
        "category": "Reports",
        "group": "Financial Reports",
        "icon": "📉",
        "keywords": [
            "revenue",
            "income",
            "sales",
            "retail",
            "tips",
            "tax",
            "sales tax",
            "financial",
            "dashboard"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Analyze revenue trends and financial performance."
    },

    {
        "title": "Spanish Help Pages",
        "endpoint": "help_center",
        "category": "Support",
        "group": "Help",
        "icon": "🇪🇸",
        "keywords": ["spanish", "español", "language", "help", "ayuda", "es"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Find Spanish-language help and support content."
    },

    {
        "title": "Language Settings",
        "endpoint": "my_settings",
        "category": "Admin",
        "group": "Settings",
        "icon": "🌐",
        "keywords": ["language", "spanish", "english", "es", "en", "translation"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage language and localization settings."
    },

    {
        "title": "Help Center",
        "endpoint": "help_center",
        "category": "Support",
        "group": "Help",
        "icon": "❔",
        "keywords": ["help", "support", "documentation", "instructions", "guide"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Search help pages and documentation."
    },

    {
        "title": "Inventory Scanner",
        "endpoint": "inventory_scan",
        "category": "Inventory",
        "group": "Tools",
        "icon": "📷",
        "keywords": [
            "scan", 
            "scanner", 
            "sku", 
            "barcode", 
            "qr", 
            "inventory",
            "smartphone",
            "iPhone",
            "camera"
        ],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Scan SKU, barcode, or QR codes for inventory tools."
    },

    {
        "title": "SKU Management",
        "endpoint": "inventory_scan",
        "category": "Inventory",
        "group": "Products",
        "icon": "🏷️",
        "keywords": ["sku", "product code", "barcode", "inventory", "products"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Manage product SKUs and item identifiers."
    },

    {
        "title": "QR Codes",
        "endpoint": "inventory_scan",
        "category": "Business",
        "group": "Tools",
        "icon": "🔲",
        "keywords": ["qr", "qr code", "scan", "code", "client form", "intake"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Manage QR codes for forms, links, and client tools."
    },

    {
        "title": "Loans",
        "endpoint": "financials_home",
        "category": "Financials",
        "group": "Loans",
        "icon": "🏦",
        "keywords": ["loan", "loans", "debt", "payment", "financing"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Track business loans and loan payments."
    },

    {
        "title": "Finance Center",
        "endpoint": "financials_home",
        "category": "Financials",
        "group": "Accounting",
        "icon": "💼",
        "keywords": [
            "finance", 
            "financials", 
            "accounting", 
            "money", 
            "income", 
            "expenses"
            ],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Open the financial management center."
    },

    {
        "title": "Owner Finance",
        "endpoint": "financials_home",
        "category": "Financials",
        "group": "Owner",
        "icon": "👑",
        "keywords": ["owner", "owner finance", "draw", "contribution", "equity", "distribution"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Track owner contributions, draws, and owner-related finance activity."
    },

    {
        "title": "Dropdown List Management",
        "endpoint": "admin",
        "category": "Admin",
        "group": "Configuration",
        "icon": "📋",
        "keywords": ["dropdown", "drop down", "lists", "list management", "settings", "options"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage configurable dropdown lists and system options."
    },

    {
        "title": "Client Forms",
        "endpoint": "client_management",
        "category": "Clients",
        "group": "Forms",
        "icon": "🧾",
        "keywords": ["client forms", "forms", "intake", "waiver", "consent", "qr"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Manage client intake forms, waivers, and form links."
    },

    {
        "title": "Privacy Policy",
        "endpoint": "help_center",
        "category": "Support",
        "group": "Legal",
        "icon": "🔒",
        "keywords": ["privacy", "privacy policy", "data", "legal"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "View the privacy policy."
    },
    
    {
        "title": "Terms and Conditions",
        "endpoint": "help_center",
        "category": "Support",
        "group": "Legal",
        "icon": "📄",
        "keywords": ["terms", "conditions", "terms and conditions", "legal", "agreement"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "View the terms and conditions."
    },


    {
        "title": "Feedback",
        "endpoint": "feedback",
        "category": "Support",
        "group": "Feedback",
        "icon": "💡",
        "keywords": ["feedback", "recommendations", "suggestions", "ideas", "bugs"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Submit feedback, recommendations, bugs, or feature ideas."
    },

    {
        "title": "Contact Preferences",
        "endpoint": "client_contact_preferences",
        "category": "Communications",
        "group": "Client Contact",
        "icon": "☎️",
        "keywords": ["contact", "contact preferences", "sms", "email", "call", "opt in", "opt out"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage client contact and communication preferences."
    },

    {
        "title": "Square Integration",
        "endpoint": "credit_processors",
        "category": "Integrations",
        "group": "Square",
        "icon": "⬛",
        "keywords": ["square", "payment", "credit card", "card reader", "pos"],
        "favorite": False,
        "admin_only": True,
        "active": False,
        "description": "Manage Square payment and appointment integration."
    },

    {
        "title": "GoDaddy Imports",
        "endpoint": "godaddy_imports",
        "category": "Integrations",
        "group": "GoDaddy",
        "icon": "🌐",
        "keywords": ["godaddy", "import", "booking import", "view godaddy import", "raw", "godaddy raw"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review appointments imported from GoDaddy booking emails."
    },

    {
        "title": "Credit Card Processors",
        "endpoint": "credit_processors",
        "category": "Admin",
        "group": "Payments",
        "icon": "💳",
        "keywords": ["credit card", "payment", "processor", "payments", "fees", "square"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage credit card processors and payment settings."
    },

    {
        "title": "Add New Client",
        "endpoint": "add_new_client",
        "category": "Clients",
        "group": "Client Management",
        "icon": "➕",
        "keywords": ["add client", "add new client", "new client", "create client"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Add a new client record."
    },

    {
        "title": "Add Appointment",
        "endpoint": "add_appointment",
        "category": "Scheduling",
        "group": "Appointments",
        "icon": "➕",
        "keywords": ["add appointment", "new appointment", "book appointment", "schedule appointment"],
        "favorite": True,
        "admin_only": False,
        "active": True,
        "description": "Create a new appointment."
    },

    {
        "title": "Reschedule Appointment",
        "endpoint": "appointments",
        "category": "Scheduling",
        "group": "Appointments",
        "icon": "🔁",
        "keywords": ["reschedule appointment", "move appointment", "change appointment time"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Find an appointment to reschedule."
    },

    {
        "title": "Cancel Appointment",
        "endpoint": "appointments",
        "category": "Scheduling",
        "group": "Appointments",
        "icon": "🚫",
        "keywords": ["cancel appointment", "delete appointment", "appointment cancellation"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Find an appointment to cancel."
    },

    {
        "title": "Edit Appointment",
        "endpoint": "appointments",
        "category": "Scheduling",
        "group": "Appointments",
        "icon": "✏️",
        "keywords": ["edit appointment", "change appointment", "update appointment"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Find and edit an existing appointment."
    },

    {
        "title": "Employees",
        "endpoint": "employee_admin",
        "category": "Employees",
        "group": "Team",
        "icon": "👥",
        "keywords": ["employee", "employees", "staff", "team"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "View and manage employees."
    },

    {
        "title": "Add New Employee",
        "endpoint": "add_employee",
        "category": "Employees",
        "group": "Team",
        "icon": "➕",
        "keywords": ["add employee", "add new employee", "new employee", "staff"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Add a new employee record."
    },

    {
        "title": "Employee Pay",
        "endpoint": "employee_pay_summary",
        "category": "Employees",
        "group": "Compensation",
        "icon": "💵",
        "keywords": ["employee pay", "payroll", "employee compensation", "wages", "tips"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Review employee pay, compensation, and payroll details."
    },

    {
        "title": "Tips",
        "endpoint": "employee_pay_summary",
        "category": "Financials",
        "group": "Compensation",
        "icon": "💰",
        "keywords": ["tips", "gratuity", "employee tips", "tip income"],
        "favorite": False,
        "admin_only": False,
        "active": True,
        "description": "Track tips and gratuities."
    },

    {
        "title": "Services",
        "endpoint": "employee_pay_summary",
        "category": "Business",
        "group": "Services",
        "icon": "🧴",
        "keywords": ["services", "service list", "facials", "treatments", "pricing"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage services, treatments, durations, and pricing."
    },

    {
        "title": "Users",
        "endpoint": "add_user",
        "category": "Admin",
        "group": "Users",
        "icon": "👤",
        "keywords": ["users", "add user", "login", "account", "security"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Manage application users and access."
    },
    
    {
        "title": "Add User",
        "endpoint": "add_user",
        "category": "Admin",
        "group": "Users",
        "icon": "➕",
        "keywords": ["add user", "new user", "create user", "login account"],
        "favorite": False,
        "admin_only": True,
        "active": True,
        "description": "Create a new application user."
    }














]   