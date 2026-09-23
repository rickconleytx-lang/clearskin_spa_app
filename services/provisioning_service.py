import re
import unicodedata


class ProvisioningError(Exception):
    """Raised when Peach Suite Pro business provisioning is invalid."""


PUBLIC_WEBSITE_DEFAULTS = {
    "website_color_scheme": "peach_cream",
    "include_marketing_sms_in_10dlc_application": False,
    "website_tagline": "Professional Services",
    "hero_headline": (
        "Welcome. We're glad you're here."
    ),
    "hero_description": (
        "Explore our services, learn more about our business, "
        "and book an appointment online."
    ),
    "intro_heading": (
        "Personalized service for every client"
    ),
    "intro_description": (
        "Learn more about our services and choose the options "
        "that best fit your needs."
    ),
    "show_promotional_section": False,
    "promotional_heading": "",
    "promotional_text": "",
    "show_about_section": True,
    "about_heading": "About Our Business",
    "about_description": (
        "We are committed to providing professional, "
        "personalized service in a welcoming environment."
    ),
    "about_image_url": "",
    "about_image_alt": "",
    "services_heading": "Services designed around you",
    "services_description": (
        "Explore the services currently offered by our business."
    ),
    "show_services_two_section": False,
    "services_two_heading": "Additional Services",
    "services_two_description": "",
    "show_services_three_section": False,
    "services_three_heading": "More Services",
    "services_three_description": "",
    "booking_heading": "Ready to schedule?",
    "booking_description": (
        "Choose a service and select an available appointment time."
    ),
    "show_additional_menu_section": False,
    "additional_menu_heading": "Additional Menu",
    "additional_menu_description": "",
    "appointment_contact_email": "",
    "appointment_contact_phone": "",
}


DEFAULT_CLIENT_STATUSES = (
    "Current",
    "Previous",
    "Prior Client",
    "Inactive",
    "Event Contact",
)


DEFAULT_PSP_ACCESS_AREA_LEVELS = (
    ("employees_compensation", 1),
    ("financial_management", 1),
    ("add_income", 1),
    ("add_expense", 1),
    ("business_goals", 1),
    ("business_users", 1),
    ("business_security", 1),
)


def _required_text(value, field_name):
    value = str(value or "").strip()
    if not value:
        raise ProvisioningError(
            f"{field_name} is required."
        )
    return value


def build_registration_number(business_name, spa_id):
    words = str(business_name or "").split()
    initials = "".join(
        word[0].upper()
        for word in words
        if word and word[0].isalnum()
    )
    initials = initials[:3]
    if not initials:
        initials = "BUS"
    return f"PSP-{initials}-{int(spa_id):06d}"


def build_unique_workspace_public_slug(
    cursor,
    business_name,
    business_unit_id,
):
    """
    Build one globally unique PeachBook / PeachWeb identifier
    using the caller's existing transaction.
    """
    normalized_name = unicodedata.normalize(
        "NFKD",
        str(business_name or ""),
    )
    normalized_name = (
        normalized_name
        .encode("ascii", "ignore")
        .decode("ascii")
    )

    base_slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        normalized_name,
    ).strip("-").lower()

    if not base_slug:
        base_slug = f"business-{business_unit_id}"

    base_slug = base_slug[:100].strip("-")

    if not base_slug:
        base_slug = f"business-{business_unit_id}"

    reserved_labels = {
        "app",
        "admin",
        "api",
        "www",
        "mail",
        "smtp",
        "imap",
        "pop",
        "status",
        "support",
    }

    candidate_number = 0

    while True:
        if candidate_number == 0:
            candidate = base_slug
        elif candidate_number == 1:
            candidate = (
                f"{base_slug}-{business_unit_id}"
            )
        else:
            candidate = (
                f"{base_slug}-"
                f"{business_unit_id}-"
                f"{candidate_number}"
            )

        candidate = candidate[:120].strip("-")
        hostname = f"{candidate}.peachsuitepro.com"

        if candidate in reserved_labels:
            candidate_number = max(
                candidate_number + 1,
                1,
            )
            continue

        cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM booking_settings
                    WHERE public_booking_slug = %s
                ),
                EXISTS (
                    SELECT 1
                    FROM public_website_domains
                    WHERE hostname = %s
                )
            """,
            (
                candidate,
                hostname,
            ),
        )

        slug_exists, hostname_exists = (
            cursor.fetchone()
        )

        if not slug_exists and not hostname_exists:
            return candidate

        candidate_number += 1


def seed_client_status_defaults(cursor, spa_id):
    """
    Create the standard tenant Client Status options.
    Safe to call repeatedly.
    """
    for status_name in DEFAULT_CLIENT_STATUSES:
        cursor.execute(
            """
            INSERT INTO client_statuses (
                spa_id,
                status_name,
                is_active
            )
            SELECT
                %s,
                %s,
                TRUE
            WHERE NOT EXISTS (
                SELECT 1
                FROM client_statuses
                WHERE spa_id = %s
                  AND LOWER(BTRIM(status_name))
                      = LOWER(BTRIM(%s))
            )
            """,
            (
                spa_id,
                status_name,
                spa_id,
                status_name,
            ),
        )


def ensure_owner_employee_role(cursor, spa_id):
    """
    Ensure the permanent Employee Role slot 1 exists for one business.

    The caller owns the transaction boundary.
    """
    cursor.execute(
        """
        SELECT employee_role_id
        FROM employee_roles
        WHERE spa_id = %s
          AND role_slot = 1
        LIMIT 1
        """,
        (spa_id,),
    )
    row = cursor.fetchone()

    if row:
        employee_role_id = row[0]

        cursor.execute(
            """
            UPDATE employee_roles
            SET role_name = 'Owner',
                is_active = TRUE,
                display_order = 10
            WHERE employee_role_id = %s
              AND spa_id = %s
              AND role_slot = 1
            """,
            (
                employee_role_id,
                spa_id,
            ),
        )

        return employee_role_id

    cursor.execute(
        """
        INSERT INTO employee_roles (
            spa_id,
            role_name,
            is_active,
            display_order,
            role_slot
        )
        VALUES (%s, 'Owner', TRUE, 10, 1)
        RETURNING employee_role_id
        """,
        (spa_id,),
    )

    return cursor.fetchone()[0]


def seed_psp_access_area_defaults(
    cursor,
    *,
    spa_id,
    business_unit_id,
):
    """
    Seed the seven restricted PSP Access Areas for one workspace.

    New workspaces begin conservatively at Access Level 1, matching
    the original psp_access_levels_v1 migration. The operation is
    idempotent so it is safe to call during provisioning.
    """
    cursor.executemany(
        """
        INSERT INTO psp_access_area_settings (
            spa_id,
            business_unit_id,
            area_key,
            required_access_level
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (
            spa_id,
            business_unit_id,
            area_key
        )
        DO NOTHING
        """,
        [
            (
                spa_id,
                business_unit_id,
                area_key,
                required_access_level,
            )
            for (
                area_key,
                required_access_level,
            ) in DEFAULT_PSP_ACCESS_AREA_LEVELS
        ],
    )


def _provision_new_business_workspace_foundation(
    cursor,
    *,
    spa_id,
    business_name,
    administrator_user_id=None,
    actor_user_id=None,
    contact_email="",
    contact_phone="",
):
    """
    Provision the default workspace plus PeachBook and PeachWeb
    foundations.

    When administrator_user_id is supplied, also create the legacy
    administrator workspace membership at the same point in the
    provisioning sequence.

    This private helper intentionally does not commit or roll back.
    The caller owns the transaction boundary.
    """
    defaults = PUBLIC_WEBSITE_DEFAULTS

    cursor.execute(
        """
        INSERT INTO business_units (
            spa_id,
            unit_name,
            unit_type,
            is_default,
            is_active,
            created_by,
            updated_by
        )
        VALUES (
            %s,
            %s,
            'organization',
            TRUE,
            TRUE,
            %s,
            %s
        )
        RETURNING business_unit_id
        """,
        (
            spa_id,
            business_name,
            actor_user_id,
            actor_user_id,
        ),
    )
    business_unit_id = cursor.fetchone()[0]

    seed_psp_access_area_defaults(
        cursor,
        spa_id=spa_id,
        business_unit_id=business_unit_id,
    )

    if administrator_user_id is not None:
        cursor.execute(
            """
            INSERT INTO business_unit_memberships (
                spa_id,
                business_unit_id,
                user_id,
                membership_role_code,
                is_active,
                granted_by
            )
            VALUES (
                %s,
                %s,
                %s,
                'organization_admin',
                TRUE,
                %s
            )
            """,
            (
                spa_id,
                business_unit_id,
                administrator_user_id,
                actor_user_id,
            ),
        )

    public_slug = build_unique_workspace_public_slug(
        cursor,
        business_name,
        business_unit_id,
    )

    cursor.execute(
        """
        INSERT INTO booking_settings (
            spa_id,
            business_unit_id,
            public_booking_slug,
            created_by,
            updated_by
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """,
        (
            spa_id,
            business_unit_id,
            public_slug,
            actor_user_id,
            actor_user_id,
        ),
    )

    cursor.execute(
        """
        INSERT INTO public_website_settings (
            spa_id,
            business_unit_id,
            website_tagline,
            hero_headline,
            hero_description,
            intro_heading,
            intro_description,
            show_promotional_section,
            promotional_heading,
            promotional_text,
            show_about_section,
            about_heading,
            about_description,
            services_heading,
            services_description,
            show_services_two_section,
            services_two_heading,
            services_two_description,
            show_services_three_section,
            services_three_heading,
            services_three_description,
            booking_heading,
            booking_description,
            show_additional_menu_section,
            additional_menu_heading,
            additional_menu_description,
            website_color_scheme,
            include_marketing_sms_in_10dlc_application,
            appointment_contact_email,
            appointment_contact_phone
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        """,
        (
            spa_id,
            business_unit_id,
            defaults["website_tagline"],
            defaults["hero_headline"],
            defaults["hero_description"],
            defaults["intro_heading"],
            defaults["intro_description"],
            defaults["show_promotional_section"],
            defaults["promotional_heading"],
            defaults["promotional_text"],
            defaults["show_about_section"],
            defaults["about_heading"],
            defaults["about_description"],
            defaults["services_heading"],
            defaults["services_description"],
            defaults["show_services_two_section"],
            defaults["services_two_heading"],
            defaults["services_two_description"],
            defaults["show_services_three_section"],
            defaults["services_three_heading"],
            defaults["services_three_description"],
            defaults["booking_heading"],
            defaults["booking_description"],
            defaults["show_additional_menu_section"],
            defaults["additional_menu_heading"],
            defaults["additional_menu_description"],
            defaults["website_color_scheme"],
            defaults[
                "include_marketing_sms_in_10dlc_application"
            ],
            str(contact_email or "").strip(),
            str(contact_phone or "").strip(),
        ),
    )

    hostname = f"{public_slug}.peachsuitepro.com"

    cursor.execute(
        """
        INSERT INTO public_website_domains (
            spa_id,
            business_unit_id,
            hostname,
            domain_type,
            is_primary,
            is_active
        )
        VALUES (
            %s,
            %s,
            %s,
            'hosted_subdomain',
            TRUE,
            TRUE
        )
        """,
        (
            spa_id,
            business_unit_id,
            hostname,
        ),
    )

    return {
        "business_unit_id": business_unit_id,
        "public_booking_slug": public_slug,
        "public_website_hostname": hostname,
    }


def provision_new_business_owner_employee(
    cursor,
    *,
    spa_id,
    business_unit_id,
    owner_first_name,
    owner_last_name,
    owner_email="",
    owner_phone="",
    actor_user_id=None,
):
    """
    Create the permanent Owner employee identity for a new business.

    The Owner employee always uses Employee Role slot 1 and PSP
    Access Level 1. This helper creates no PSP user account.

    The caller owns the transaction boundary.
    """
    owner_first_name = _required_text(
        owner_first_name,
        "Owner first name",
    )
    owner_last_name = _required_text(
        owner_last_name,
        "Owner last name",
    )
    owner_email = str(owner_email or "").strip().lower()
    owner_phone = str(owner_phone or "").strip()

    cursor.execute(
        """
        SELECT business_unit_id
        FROM business_units
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND is_active = TRUE
        LIMIT 1
        """,
        (
            spa_id,
            business_unit_id,
        ),
    )

    if not cursor.fetchone():
        raise ProvisioningError(
            "The Owner workspace is unavailable."
        )

    owner_employee_role_id = ensure_owner_employee_role(
        cursor,
        spa_id,
    )

    cursor.execute(
        """
        INSERT INTO employees (
            spa_id,
            first_name,
            last_name,
            employee_role_id,
            is_active,
            phone,
            email,
            status,
            created_by,
            updated_by
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            TRUE,
            %s,
            %s,
            NULL,
            %s,
            %s
        )
        RETURNING employee_id
        """,
        (
            spa_id,
            owner_first_name,
            owner_last_name,
            owner_employee_role_id,
            owner_phone or None,
            owner_email or None,
            actor_user_id,
            actor_user_id,
        ),
    )

    owner_employee_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO employee_business_unit_memberships (
            spa_id,
            business_unit_id,
            employee_id,
            is_active,
            assigned_by,
            access_level
        )
        VALUES (%s, %s, %s, TRUE, %s, 1)
        """,
        (
            spa_id,
            business_unit_id,
            owner_employee_id,
            actor_user_id,
        ),
    )

    cursor.execute(
        """
        UPDATE business_units
        SET owner_employee_id = %s,
            updated_by = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE spa_id = %s
          AND business_unit_id = %s
          AND is_active = TRUE
        """,
        (
            owner_employee_id,
            actor_user_id,
            spa_id,
            business_unit_id,
        ),
    )

    if cursor.rowcount != 1:
        raise ProvisioningError(
            "The Owner workspace could not be linked."
        )

    return {
        "owner_employee_id": owner_employee_id,
        "owner_employee_role_id": owner_employee_role_id,
        "owner_access_level": 1,
    }


def provision_new_business_workspace_without_user(
    cursor,
    *,
    spa_id,
    business_name,
    actor_user_id=None,
    contact_email="",
    contact_phone="",
):
    """
    Provision a new business workspace before any PSP user exists.

    This is the delegated/invitation onboarding foundation. It creates
    the workspace, PeachBook foundation, and PeachWeb foundation but
    deliberately creates no business_unit_membership.

    The caller owns the transaction boundary.
    """
    return _provision_new_business_workspace_foundation(
        cursor,
        spa_id=spa_id,
        business_name=business_name,
        administrator_user_id=None,
        actor_user_id=actor_user_id,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )


def provision_new_business_workspace_foundation(
    cursor,
    *,
    spa_id,
    administrator_user_id,
    business_name,
    actor_user_id=None,
    contact_email="",
    contact_phone="",
):
    """
    Preserve the existing direct-provisioning workspace behavior.

    The initial administrator receives an organization_admin
    membership while the normal workspace, PeachBook, and PeachWeb
    foundations are created.

    The caller owns the transaction boundary.
    """
    if administrator_user_id is None:
        raise ProvisioningError(
            "Administrator user is required for direct provisioning."
        )

    return _provision_new_business_workspace_foundation(
        cursor,
        spa_id=spa_id,
        business_name=business_name,
        administrator_user_id=administrator_user_id,
        actor_user_id=actor_user_id,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )


def _provision_new_business_record(
    cursor,
    *,
    business_name,
    owner_first_name,
    owner_last_name,
    owner_email,
    subscription_tier_code,
    organization_type_code,
    subscription_status,
    timezone_name,
    owner_phone="",
):
    """
    Create the tenant-level business record and shared defaults.

    Inputs are expected to be normalized and validated by the public
    provisioning workflow. The caller owns the transaction boundary.
    """
    cursor.execute(
        """
        SELECT spa_id
        FROM spas
        WHERE LOWER(spa_name) = LOWER(%s)
        LIMIT 1
        """,
        (business_name,),
    )

    if cursor.fetchone():
        raise ProvisioningError(
            "A business with this name already exists."
        )

    cursor.execute(
        """
        SELECT user_id
        FROM users
        WHERE LOWER(email) = LOWER(%s)
           OR LOWER(username) = LOWER(%s)
        LIMIT 1
        """,
        (
            owner_email,
            owner_email,
        ),
    )

    if cursor.fetchone():
        raise ProvisioningError(
            "A user with this email address already exists."
        )

    cursor.execute(
        """
        SELECT subscription_tier_id
        FROM subscription_tiers
        WHERE tier_code = %s
          AND is_active = TRUE
        LIMIT 1
        """,
        (subscription_tier_code,),
    )

    tier_row = cursor.fetchone()

    if not tier_row:
        raise ProvisioningError(
            "The selected subscription tier is unavailable."
        )

    subscription_tier_id = tier_row[0]

    cursor.execute(
        """
        SELECT organization_type_id
        FROM organization_types
        WHERE type_code = %s
          AND is_active = TRUE
        LIMIT 1
        """,
        (organization_type_code,),
    )

    organization_row = cursor.fetchone()

    if not organization_row:
        raise ProvisioningError(
            "The selected organization type is unavailable."
        )

    organization_type_id = organization_row[0]

    cursor.execute(
        """
        INSERT INTO spas (
            spa_name,
            owner_first_name,
            owner_last_name,
            owner_phone,
            owner_email,
            timezone_name,
            subscription_status,
            subscription_tier_id,
            organization_type_id,
            active
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, TRUE
        )
        RETURNING spa_id
        """,
        (
            business_name,
            owner_first_name,
            owner_last_name,
            owner_phone or None,
            owner_email,
            timezone_name,
            subscription_status,
            subscription_tier_id,
            organization_type_id,
        ),
    )

    spa_id = cursor.fetchone()[0]

    ensure_owner_employee_role(
        cursor,
        spa_id,
    )

    seed_client_status_defaults(
        cursor,
        spa_id,
    )

    registration_number = build_registration_number(
        business_name,
        spa_id,
    )

    cursor.execute(
        """
        UPDATE spas
        SET registration_number = %s
        WHERE spa_id = %s
        """,
        (
            registration_number,
            spa_id,
        ),
    )

    return {
        "spa_id": spa_id,
        "registration_number": registration_number,
    }


def provision_new_business_for_owner_invitation(
    cursor,
    *,
    business_name,
    owner_first_name,
    owner_last_name,
    owner_email,
    subscription_tier_code,
    organization_type_code,
    subscription_status,
    timezone_name="America/Chicago",
    owner_phone="",
    actor_user_id=None,
):
    """
    Provision a business that is waiting for its Owner to activate.

    The actual Owner receives a permanent employee identity and
    workspace Access Level 1, but no PSP user is created. The Owner's
    PSP account will be created only when the invitation is accepted.

    This function intentionally does not commit or roll back.
    """
    business_name = _required_text(
        business_name,
        "Business name",
    )
    owner_first_name = _required_text(
        owner_first_name,
        "Owner first name",
    )
    owner_last_name = _required_text(
        owner_last_name,
        "Owner last name",
    )
    owner_email = _required_text(
        owner_email,
        "Owner email",
    ).lower()
    subscription_tier_code = _required_text(
        subscription_tier_code,
        "Subscription tier",
    ).lower()
    organization_type_code = _required_text(
        organization_type_code,
        "Organization type",
    ).lower()
    subscription_status = _required_text(
        subscription_status,
        "Subscription status",
    )
    timezone_name = _required_text(
        timezone_name,
        "Business time zone",
    )
    owner_phone = str(owner_phone or "").strip()

    business_record = _provision_new_business_record(
        cursor,
        business_name=business_name,
        owner_first_name=owner_first_name,
        owner_last_name=owner_last_name,
        owner_email=owner_email,
        subscription_tier_code=subscription_tier_code,
        organization_type_code=organization_type_code,
        subscription_status=subscription_status,
        timezone_name=timezone_name,
        owner_phone=owner_phone,
    )

    spa_id = business_record["spa_id"]

    foundation = provision_new_business_workspace_without_user(
        cursor,
        spa_id=spa_id,
        business_name=business_name,
        actor_user_id=actor_user_id,
        contact_email=owner_email,
        contact_phone=owner_phone,
    )

    owner = provision_new_business_owner_employee(
        cursor,
        spa_id=spa_id,
        business_unit_id=foundation["business_unit_id"],
        owner_first_name=owner_first_name,
        owner_last_name=owner_last_name,
        owner_email=owner_email,
        owner_phone=owner_phone,
        actor_user_id=actor_user_id,
    )

    cursor.execute(
        """
        INSERT INTO business_onboarding (
            spa_id,
            account_opened_by_user_id,
            primary_onboarding_user_id,
            waiting_on_initial_activation
        )
        VALUES (%s, %s, NULL, TRUE)
        """,
        (
            spa_id,
            actor_user_id,
        ),
    )

    return {
        "spa_id": spa_id,
        "owner_employee_id": owner["owner_employee_id"],
        "registration_number": business_record[
            "registration_number"
        ],
        "subscription_tier_code": subscription_tier_code,
        "organization_type_code": organization_type_code,
        "waiting_on_initial_activation": True,
        **foundation,
    }


def provision_new_business(
    cursor,
    *,
    business_name,
    owner_first_name,
    owner_last_name,
    owner_email,
    administrator_password_hash,
    subscription_tier_code,
    organization_type_code,
    subscription_status,
    timezone_name="America/Chicago",
    owner_phone="",
    actor_user_id=None,
):
    """
    Create one complete Peach Suite Pro business using the
    caller's existing transaction.

    This is the shared provisioning engine for Master Admin
    creation and future Stripe-authoritative provisioning.

    This function intentionally does not commit or roll back.
    """
    business_name = _required_text(
        business_name,
        "Business name",
    )
    owner_first_name = _required_text(
        owner_first_name,
        "Administrator first name",
    )
    owner_last_name = _required_text(
        owner_last_name,
        "Administrator last name",
    )
    owner_email = _required_text(
        owner_email,
        "Administrator email",
    ).lower()
    administrator_password_hash = _required_text(
        administrator_password_hash,
        "Administrator password hash",
    )
    subscription_tier_code = _required_text(
        subscription_tier_code,
        "Subscription tier",
    ).lower()
    organization_type_code = _required_text(
        organization_type_code,
        "Organization type",
    ).lower()
    subscription_status = _required_text(
        subscription_status,
        "Subscription status",
    )
    timezone_name = _required_text(
        timezone_name,
        "Business time zone",
    )
    owner_phone = str(owner_phone or "").strip()

    business_record = _provision_new_business_record(
        cursor,
        business_name=business_name,
        owner_first_name=owner_first_name,
        owner_last_name=owner_last_name,
        owner_email=owner_email,
        subscription_tier_code=subscription_tier_code,
        organization_type_code=organization_type_code,
        subscription_status=subscription_status,
        timezone_name=timezone_name,
        owner_phone=owner_phone,
    )

    spa_id = business_record["spa_id"]
    registration_number = business_record[
        "registration_number"
    ]

    cursor.execute(
        """
        INSERT INTO users (
            spa_id,
            first_name,
            last_name,
            email,
            username,
            password_hash,
            role,
            active,
            preferred_language,
            must_change_password
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            'admin', TRUE, 'EN', TRUE
        )
        RETURNING user_id
        """,
        (
            spa_id,
            owner_first_name,
            owner_last_name,
            owner_email,
            owner_email,
            administrator_password_hash,
        ),
    )
    administrator_user_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO business_onboarding (
            spa_id,
            account_opened_by_user_id,
            primary_onboarding_user_id,
            waiting_on_initial_activation
        )
        VALUES (%s, %s, %s, FALSE)
        """,
        (
            spa_id,
            actor_user_id,
            administrator_user_id,
        ),
    )

    foundation = provision_new_business_workspace_foundation(
        cursor,
        spa_id=spa_id,
        administrator_user_id=administrator_user_id,
        business_name=business_name,
        actor_user_id=actor_user_id,
        contact_email=owner_email,
        contact_phone=owner_phone,
    )

    return {
        "spa_id": spa_id,
        "administrator_user_id": administrator_user_id,
        "registration_number": registration_number,
        "subscription_tier_code": subscription_tier_code,
        "organization_type_code": organization_type_code,
        **foundation,
    }
