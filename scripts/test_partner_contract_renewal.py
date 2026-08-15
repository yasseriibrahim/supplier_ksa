"""Rollback-only smoke test for automatic yearly contract renewal."""

from odoo import fields

admin = env["res.users"].search([("login", "=", "admin")], limit=1)
test_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[admin.company_id.id]))
company = admin.company_id

try:
    partner = test_env["res.partner"].create({
        "name": "Yearly contract renewal smoke customer",
        "company_id": company.id,
    })
    original = test_env["partner.contract"].create({
        "partner_id": partner.id,
        "start_date": fields.Date.from_string("2023-09-15"),
        "end_date": fields.Date.from_string("2024-09-15"),
        "contract_amount": 12000.0,
        "currency_id": company.currency_id.id,
        "payment_periods": "25",
        "company_id": company.id,
        "notes": "Same notes every year",
        "auto_renew": True,
    })
    original._generate_installment_lines(preview=False)
    original.action_activate()
    test_env["partner.contract"]._cron_renew_yearly_contracts()

    chain = original
    while chain.renewed_contract_id:
        chain = chain.renewed_contract_id
    assert original.state == "renewed", original.state
    assert chain.state == "active", chain.state
    assert chain.end_date > fields.Date.today(), chain.end_date
    assert chain.contract_amount == original.contract_amount
    assert chain.payment_periods == original.payment_periods
    assert chain.notes == original.notes
    assert len(chain.installment_ids) == 4
    assert [(line.due_date.month, line.due_date.day) for line in chain.installment_ids] == [
        (9, 15), (12, 15), (3, 15), (6, 15),
    ]
    print("TEST_OK", original.start_date, "->", chain.start_date,
          "active_until", chain.end_date, "installments", len(chain.installment_ids))
finally:
    env.cr.rollback()
