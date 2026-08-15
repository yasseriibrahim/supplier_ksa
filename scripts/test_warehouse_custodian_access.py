"""Rollback-only security and quantity test for the warehouse custodian role."""

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
admin_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id
jeddah = admin_env["stock.location"].search([
    ("name", "=", "مخزن جده"), ("company_id", "=", company.id),
], limit=1)
dammam = admin_env["stock.location"].search([
    ("name", "=", "مخزن الدمام"), ("company_id", "=", company.id),
], limit=1)
group = admin_env.ref("supplier_ksa.group_warehouse_custodian")

try:
    user = admin_env["res.users"].create({
        "name": "Warehouse custodian smoke user",
        "login": "warehouse-custodian-smoke@example.invalid",
        "company_id": company.id,
        "company_ids": [(6, 0, [company.id])],
        "custodian_location_id": jeddah.id,
    })
    group.user_ids = [(4, user.id)]
    product = admin_env["product.product"].create({
        "name": "Warehouse custodian smoke product",
        "is_storable": True,
        "company_id": company.id,
    })
    admin_env["stock.quant"]._update_available_quantity(product, jeddah, 2.0)
    admin_env["stock.quant"]._update_available_quantity(product, dammam, 7.0)

    user_env = env(user=user.id, context=dict(env.context, allowed_company_ids=[company.id]))
    visible_locations = user_env["stock.location"].search([])
    assert jeddah in visible_locations
    assert dammam not in visible_locations
    user_product = user_env["product.product"].browse(product.id)
    assert user_product.custodian_quantity == 2.0
    user_product.custodian_quantity = 5.0
    assert admin_env["stock.quant"]._get_available_quantity(
        product, jeddah, strict=True, allow_negative=True,
    ) == 5.0
    assert admin_env["stock.quant"]._get_available_quantity(
        product, dammam, strict=True, allow_negative=True,
    ) == 7.0
    created = user_env["product.product"].create({
        "name": "Created by warehouse custodian",
        "is_storable": True,
    })
    created.custodian_quantity = 4.0
    assert created.custodian_quantity == 4.0
    visible_quants = user_env["stock.quant"].search([])
    assert all(quant.location_id == jeddah for quant in visible_quants)
    assert not visible_quants.filtered(lambda quant: quant.location_id == dammam)
    print("TEST_OK", user.login, jeddah.complete_name,
          "JEDDAH", 5.0, "DAMMAM", 7.0, "CREATED_PRODUCT", created.display_name)
finally:
    env.cr.rollback()
