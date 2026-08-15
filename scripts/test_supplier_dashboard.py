"""Read-only smoke test for the Supplier KSA dashboard payload."""

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
data = test_env["supplier.dashboard"].get_dashboard_data()
required = {
    "company", "today", "currency", "kpis", "overdue_installments",
    "upcoming_installments", "overdue_invoices", "due_soon_invoices", "stock_rows",
}
assert required <= set(data), set(data)
assert {
    "active_contracts", "overdue_contract_count", "overdue_contract_amount",
    "unpaid_invoice_count", "unpaid_invoice_amount", "overdue_invoice_count",
    "overdue_invoice_amount", "low_stock_count", "out_stock_count",
} <= set(data["kpis"])
assert all(row["quantity"] <= 5 for row in data["stock_rows"])
print("TEST_OK", data["company"], data["today"], data["kpis"],
      "STOCK_ROWS", len(data["stock_rows"]))
