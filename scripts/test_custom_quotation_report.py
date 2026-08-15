"""Rollback-only smoke test for the custom quotation PDF."""

from datetime import timedelta
from odoo import fields

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id

try:
    partner = test_env["res.partner"].create({
        "name": "Custom quotation report smoke customer",
        "company_id": company.id,
    })
    product = test_env["product.product"].create({
        "name": "Quotation report smoke service",
        "type": "service",
        "sale_ok": True,
        "list_price": 125.0,
        "company_id": company.id,
    })
    order = test_env["sale.order"].create({
        "partner_id": partner.id,
        "company_id": company.id,
        "validity_date": fields.Date.today() + timedelta(days=30),
        "note": "Quotation terms and conditions",
        "order_line": [(0, 0, {
            "product_id": product.id,
            "product_uom_qty": 3.0,
            "price_unit": 125.0,
            "discount": 10.0,
        })],
    })
    report = test_env.ref("supplier_ksa.action_custom_quotation_report")
    pdf, output_type = report._render_qweb_pdf(report.report_name, [order.id])
    assert output_type == "pdf", output_type
    assert pdf.startswith(b"%PDF"), pdf[:10]
    assert len(pdf) > 1000, len(pdf)
    action = order.action_print_custom_quotation()
    assert action["type"] == "ir.actions.report", action
    print("TEST_OK", order.name, "PDF_BYTES", len(pdf), "TOTAL", order.amount_total)
finally:
    env.cr.rollback()
