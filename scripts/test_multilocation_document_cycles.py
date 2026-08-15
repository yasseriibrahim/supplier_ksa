"""Rollback-only test for per-line domains and multi-location stock cycles."""

import json

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id
jeddah = test_env["stock.location"].search([
    ("name", "=", "مخزن جده"), ("company_id", "=", company.id),
], limit=1)
dammam = test_env["stock.location"].search([
    ("name", "=", "مخزن الدمام"), ("company_id", "=", company.id),
], limit=1)
journal = test_env["account.journal"].search([
    ("type", "=", "sale"), ("company_id", "=", company.id),
], limit=1)

try:
    empty_invoice_line = test_env["account.move.line"].new({})
    empty_invoice_line._compute_product_domain()
    assert json.loads(empty_invoice_line.product_domain) == []
    empty_order_line = test_env["non.invoiced.order.line"].new({})
    empty_order_line._compute_product_domain()
    assert json.loads(empty_order_line.product_domain) == []

    partner = test_env["res.partner"].create({
        "name": "Multi-location cycle smoke customer", "company_id": company.id,
    })
    products = test_env["product.product"].create([{
        "name": name, "is_storable": True, "sale_ok": True, "company_id": company.id,
    } for name in ("Jeddah multi-location product", "Dammam multi-location product")])
    product_jeddah, product_dammam = products
    test_env["stock.quant"]._update_available_quantity(product_jeddah, jeddah, 3.0)
    test_env["stock.quant"]._update_available_quantity(product_dammam, dammam, 4.0)

    invoice = test_env["account.move"].create({
        "move_type": "out_invoice", "partner_id": partner.id,
        "journal_id": journal.id, "company_id": company.id,
        "invoice_line_ids": [
            (0, 0, {"product_id": product_jeddah.id, "quantity": 5.0,
                    "price_unit": 10.0, "line_location_id": jeddah.id}),
            (0, 0, {"product_id": product_dammam.id, "quantity": 6.0,
                    "price_unit": 10.0, "line_location_id": dammam.id}),
        ],
    })
    domain_jeddah = json.loads(invoice.invoice_line_ids[0].product_domain)
    domain_dammam = json.loads(invoice.invoice_line_ids[1].product_domain)
    assert product_jeddah.id in domain_jeddah[-1][-1]
    assert product_dammam.id not in domain_jeddah[-1][-1]
    assert product_dammam.id in domain_dammam[-1][-1]
    invoice.action_post()
    assert len(invoice.picking_ids) == 2
    assert all(picking.state == "done" for picking in invoice.picking_ids)
    assert set(invoice.picking_ids.mapped("location_id").ids) == {jeddah.id, dammam.id}

    product_order_jeddah, product_order_dammam = test_env["product.product"].create([{
        "name": name, "is_storable": True, "sale_ok": True, "company_id": company.id,
    } for name in ("Jeddah non-invoiced product", "Dammam non-invoiced product")])
    test_env["stock.quant"]._update_available_quantity(product_order_jeddah, jeddah, 2.0)
    test_env["stock.quant"]._update_available_quantity(product_order_dammam, dammam, 2.0)
    order = test_env["non.invoiced.order"].create({
        "partner_id": partner.id, "company_id": company.id,
        "line_ids": [
            (0, 0, {"product_id": product_order_jeddah.id, "quantity": 4.0,
                    "price_unit": 10.0, "line_location_id": jeddah.id}),
            (0, 0, {"product_id": product_order_dammam.id, "quantity": 5.0,
                    "price_unit": 10.0, "line_location_id": dammam.id}),
        ],
    })
    order.action_done()
    assert order.state == "done"
    assert len(order.picking_ids) == 2
    assert all(picking.state == "done" for picking in order.picking_ids)
    assert set(order.picking_ids.mapped("location_id").ids) == {jeddah.id, dammam.id}

    assert test_env["stock.quant"]._get_available_quantity(
        product_jeddah, jeddah, strict=True, allow_negative=True) == -2.0
    assert test_env["stock.quant"]._get_available_quantity(
        product_dammam, dammam, strict=True, allow_negative=True) == -2.0
    assert test_env["stock.quant"]._get_available_quantity(
        product_order_jeddah, jeddah, strict=True, allow_negative=True) == -2.0
    assert test_env["stock.quant"]._get_available_quantity(
        product_order_dammam, dammam, strict=True, allow_negative=True) == -3.0
    print("TEST_OK", "INVOICE_PICKINGS", len(invoice.picking_ids),
          "ORDER_PICKINGS", len(order.picking_ids), "DOMAINS", "location-specific")
finally:
    env.cr.rollback()
