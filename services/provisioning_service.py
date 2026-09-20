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
    Provision the default workspace, administrator membership,
    PeachBook foundation, and PeachWeb foundation.

    This helper intentionally does not commit or roll back.
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
            initial_administrator_user_id
        )
        VALUES (%s, %s)
        """,
        (
            spa_id,
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
