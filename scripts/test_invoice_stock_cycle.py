"""Transactional smoke test: nothing created here is committed."""

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id
location = test_env["stock.location"].search([
    ("name", "=", "مخزن جده"), ("company_id", "=", company.id),
], limit=1)
journal = test_env["account.journal"].search([
    ("type", "=", "sale"), ("company_id", "=", company.id),
], limit=1)
if not location or not journal:
    raise RuntimeError("Test prerequisites are missing")

try:
    product = test_env["product.product"].create({
        "name": "Supplier KSA stock-cycle smoke test",
        "is_storable": True,
        "sale_ok": True,
        "company_id": company.id,
    })
    partner = test_env["res.partner"].create({
        "name": "Supplier KSA stock-cycle smoke customer",
        "company_id": company.id,
    })
    test_env["stock.quant"]._update_available_quantity(product, location, 2.0)
    before = test_env["stock.quant"]._get_available_quantity(
        product, location, allow_negative=True,
    )
    invoice = test_env["account.move"].create({
        "move_type": "out_invoice",
        "partner_id": partner.id,
        "journal_id": journal.id,
        "company_id": company.id,
        "location_id": location.id,
        "invoice_line_ids": [(0, 0, {
            "product_id": product.id,
            "quantity": 5.0,
            "price_unit": 10.0,
        })],
    })
    invoice.action_post()
    after = test_env["stock.quant"]._get_available_quantity(
        product, location, allow_negative=True,
    )
    picking = invoice.picking_ids
    assert invoice.state == "posted", invoice.state
    assert len(picking) == 1, len(picking)
    assert picking.state == "done", picking.state
    assert picking.location_id == location, picking.location_id.display_name
    assert abs(after - (before - 5.0)) < 0.00001, (before, after)
    print("TEST_OK", invoice.state, picking.name, picking.state, "QTY", before, "->", after)
finally:
    env.cr.rollback()
