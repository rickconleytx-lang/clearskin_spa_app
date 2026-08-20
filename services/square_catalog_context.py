class SquareCatalogContextError(Exception):
    """Raised when Square catalog mapping context is invalid."""



def persist_square_catalog_mapping(
    cursor,
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
    square_catalog_object_id,
    square_item_id,
    square_name,
    square_sku=None,
    mapping_type,
    inventory_product_id=None,
    service_type_id=None,
    actor_user_id=None,
):
    """
    Persist one verified Square Catalog mapping using the
    caller's existing transaction.

    This helper intentionally does not commit or roll back.
    The caller owns the transaction boundary.
    """

    def row_value(row, key, index):
        if isinstance(row, dict):
            return row.get(key)

        return row[index]

    def returned_mapping(row):
        keys = (
            "square_catalog_mapping_id",
            "square_catalog_object_id",
            "square_item_id",
            "square_name",
            "square_sku",
            "mapping_type",
            "inventory_product_id",
            "service_type_id",
            "is_active",
        )

        if isinstance(row, dict):
            return {
                key: row.get(key)
                for key in keys
            }

        return {
            key: row[index]
            for index, key in enumerate(keys)
        }

    environment = str(
        environment or ""
    ).strip().lower()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquareCatalogContextError(
            "Square catalog environment is invalid."
        )

    if not square_connection_id:
        raise SquareCatalogContextError(
            "Square connection is required."
        )

    if not spa_id or not business_unit_id:
        raise SquareCatalogContextError(
            "Square catalog workspace is required."
        )

    square_catalog_object_id = str(
        square_catalog_object_id or ""
    ).strip()

    if not square_catalog_object_id:
        raise SquareCatalogContextError(
            "Square Catalog variation is required."
        )

    mapping_type = str(
        mapping_type or ""
    ).strip()

    if mapping_type not in {
        "inventory_product",
        "service_type",
    }:
        raise SquareCatalogContextError(
            "Square catalog mapping type is invalid."
        )

    cursor.execute("""
        SELECT square_connection_id
        FROM square_connections
        WHERE square_connection_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
          AND environment = %s
        LIMIT 1
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
    ))

    if not cursor.fetchone():
        raise SquareCatalogContextError(
            "Square connection does not belong to the "
            "selected workspace."
        )

    if mapping_type == "inventory_product":
        if (
            not inventory_product_id
            or service_type_id is not None
        ):
            raise SquareCatalogContextError(
                "Square inventory mapping target is invalid."
            )

        cursor.execute("""
            SELECT product_id
            FROM inventory_products
            WHERE product_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
            LIMIT 1
        """, (
            inventory_product_id,
            spa_id,
            business_unit_id,
        ))

        if not cursor.fetchone():
            raise SquareCatalogContextError(
                "PSP inventory product changed before the "
                "Square mapping could be saved."
            )

        target_id = inventory_product_id

    else:
        if (
            not service_type_id
            or inventory_product_id is not None
        ):
            raise SquareCatalogContextError(
                "Square service mapping target is invalid."
            )

        # Services remain spa-owned master records. The
        # Square mapping itself is still workspace-specific.
        cursor.execute("""
            SELECT service_type_id
            FROM service_name_types
            WHERE service_type_id = %s
              AND spa_id = %s
            LIMIT 1
        """, (
            service_type_id,
            spa_id,
        ))

        if not cursor.fetchone():
            raise SquareCatalogContextError(
                "PSP service changed before the Square "
                "mapping could be saved."
            )

        target_id = service_type_id

    if mapping_type == "inventory_product":
        cursor.execute("""
            SELECT
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                inventory_product_id,
                service_type_id,
                is_active
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND mapping_type = 'inventory_product'
              AND inventory_product_id = %s
              AND is_active = TRUE
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            target_id,
        ))
    else:
        cursor.execute("""
            SELECT
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                inventory_product_id,
                service_type_id,
                is_active
            FROM square_catalog_mappings
            WHERE square_connection_id = %s
              AND spa_id = %s
              AND business_unit_id = %s
              AND environment = %s
              AND mapping_type = 'service_type'
              AND service_type_id = %s
              AND is_active = TRUE
            LIMIT 1
            FOR UPDATE
        """, (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            target_id,
        ))

    existing_for_target = cursor.fetchone()

    if existing_for_target:
        if (
            row_value(
                existing_for_target,
                "square_catalog_object_id",
                1,
            )
            != square_catalog_object_id
        ):
            target_label = (
                "inventory product"
                if mapping_type == "inventory_product"
                else "service"
            )

            raise SquareCatalogContextError(
                f"PSP {target_label} already has a different "
                "active Square Catalog mapping."
            )

        if (
            row_value(
                existing_for_target,
                "square_item_id",
                2,
            )
            and row_value(
                existing_for_target,
                "square_item_id",
                2,
            )
            != square_item_id
        ):
            target_label = (
                "inventory"
                if mapping_type == "inventory_product"
                else "service"
            )

            raise SquareCatalogContextError(
                f"PSP {target_label} mapping points to a "
                "different Square parent item."
            )

        cursor.execute("""
            UPDATE square_catalog_mappings
            SET
                square_item_id = %s,
                square_name = %s,
                square_sku = %s,
                verified_by = %s,
                verified_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE square_catalog_mapping_id = %s
            RETURNING
                square_catalog_mapping_id,
                square_catalog_object_id,
                square_item_id,
                square_name,
                square_sku,
                mapping_type,
                inventory_product_id,
                service_type_id,
                is_active
        """, (
            square_item_id,
            square_name,
            (
                square_sku
                if mapping_type == "inventory_product"
                else None
            ),
            actor_user_id,
            row_value(
                existing_for_target,
                "square_catalog_mapping_id",
                0,
            ),
        ))

        row = cursor.fetchone()

        return returned_mapping(row)

    cursor.execute("""
        SELECT
            square_catalog_mapping_id,
            mapping_type,
            inventory_product_id,
            service_type_id,
            is_active
        FROM square_catalog_mappings
        WHERE square_connection_id = %s
          AND square_catalog_object_id = %s
        LIMIT 1
        FOR UPDATE
    """, (
        square_connection_id,
        square_catalog_object_id,
    ))

    if cursor.fetchone():
        raise SquareCatalogContextError(
            "Square Catalog variation is already mapped "
            "to another PSP record."
        )

    cursor.execute("""
        INSERT INTO square_catalog_mappings (
            square_connection_id,
            spa_id,
            business_unit_id,
            environment,
            square_catalog_object_id,
            square_item_id,
            square_name,
            square_sku,
            mapping_type,
            inventory_product_id,
            service_type_id,
            is_active,
            verified_by,
            verified_at
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, TRUE, %s,
            CURRENT_TIMESTAMP
        )
        RETURNING
            square_catalog_mapping_id,
            square_catalog_object_id,
            square_item_id,
            square_name,
            square_sku,
            mapping_type,
            inventory_product_id,
            service_type_id,
            is_active
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
        square_catalog_object_id,
        square_item_id,
        square_name,
        (
            square_sku
            if mapping_type == "inventory_product"
            else None
        ),
        mapping_type,
        (
            inventory_product_id
            if mapping_type == "inventory_product"
            else None
        ),
        (
            service_type_id
            if mapping_type == "service_type"
            else None
        ),
        actor_user_id,
    ))

    row = cursor.fetchone()

    return returned_mapping(row)

def load_square_catalog_mappings(
    cursor,
    *,
    square_connection_id,
    spa_id,
    business_unit_id,
    environment,
):
    """
    Load active Square catalog mappings for one exact PSP
    workspace + Square connection + environment.

    Returns both:
      - catalog_classifications used by build_income_preview()
      - catalog_mapping_details used for PSP inventory posting
    """

    environment = str(
        environment or ""
    ).strip().lower()

    if environment not in {
        "sandbox",
        "production",
    }:
        raise SquareCatalogContextError(
            "Square catalog environment is invalid."
        )

    if not square_connection_id:
        raise SquareCatalogContextError(
            "Square connection is required."
        )

    if not spa_id or not business_unit_id:
        raise SquareCatalogContextError(
            "Square catalog workspace is required."
        )

    cursor.execute("""
        SELECT
            square_catalog_mapping_id,
            square_catalog_object_id,
            square_item_id,
            square_sku,
            mapping_type,
            inventory_product_id,
            service_type_id
        FROM square_catalog_mappings
        WHERE square_connection_id = %s
          AND spa_id = %s
          AND business_unit_id = %s
          AND environment = %s
          AND is_active = TRUE
    """, (
        square_connection_id,
        spa_id,
        business_unit_id,
        environment,
    ))

    catalog_classifications = {}
    catalog_mapping_details = {}

    for (
        square_catalog_mapping_id,
        square_catalog_object_id,
        square_item_id,
        square_sku,
        mapping_type,
        inventory_product_id,
        service_type_id,
    ) in cursor.fetchall():

        if mapping_type == "service_type":
            catalog_classifications[
                square_catalog_object_id
            ] = "service"

        elif mapping_type == "inventory_product":
            catalog_classifications[
                square_catalog_object_id
            ] = "retail"

        catalog_mapping_details[
            square_catalog_object_id
        ] = {
            "square_catalog_mapping_id":
                square_catalog_mapping_id,
            "square_item_id": square_item_id,
            "square_sku": square_sku,
            "mapping_type": mapping_type,
            "inventory_product_id":
                inventory_product_id,
            "service_type_id": service_type_id,
        }

    return {
        "catalog_classifications":
            catalog_classifications,
        "catalog_mapping_details":
            catalog_mapping_details,
    }
