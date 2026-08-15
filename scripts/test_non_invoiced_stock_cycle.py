"""Transactional smoke test for the non-invoiced order Done action."""

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id
location = test_env["stock.location"].search([
    ("name", "=", "مخزن الدمام"), ("company_id", "=", company.id),
], limit=1)
if not location:
    raise RuntimeError("Dammam stock location is missing")

try:
    product = test_env["product.product"].create({
        "name": "Non-invoiced stock-cycle smoke test",
        "is_storable": True,
        "sale_ok": True,
        "company_id": company.id,
    })
    partner = test_env["res.partner"].create({
        "name": "Non-invoiced smoke customer",
        "company_id": company.id,
    })
    test_env["stock.quant"]._update_available_quantity(product, location, 2.0)
    before = test_env["stock.quant"]._get_available_quantity(
        product, location, allow_negative=True,
    )
    order = test_env["non.invoiced.order"].create({
        "partner_id": partner.id,
        "company_id": company.id,
        "location_id": location.id,
        "line_ids": [(0, 0, {
            "product_id": product.id,
            "quantity": 5.0,
            "price_unit": 10.0,
        })],
    })
    order.action_done()
    after = test_env["stock.quant"]._get_available_quantity(
        product, location, allow_negative=True,
    )
    assert order.state == "done", order.state
    assert len(order.picking_ids) == 1, len(order.picking_ids)
    assert order.picking_ids.state == "done", order.picking_ids.state
    assert order.picking_ids.location_id == location
    assert abs(after - (before - 5.0)) < 0.00001, (before, after)
    print("TEST_OK", order.state, order.picking_ids.name,
          order.picking_ids.state, "QTY", before, "->", after)
finally:
    env.cr.rollback()
