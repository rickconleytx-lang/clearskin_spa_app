class SquareCatalogContextError(Exception):
    """Raised when Square catalog mapping context is invalid."""


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
