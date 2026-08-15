from datetime import timedelta

from odoo import api, fields, models


class SupplierDashboard(models.AbstractModel):
    _name = "supplier.dashboard"
    _description = "Supplier KSA Operational Dashboard"

    @api.model
    def get_dashboard_data(self):
        company = self.env.company
        today = fields.Date.today()
        soon_date = today + timedelta(days=30)
        currency = company.currency_id

        Installment = self.env["partner.payment.installment"].sudo()
        installment_domain = [
            ("contract_id", "!=", False),
            ("contract_id.company_id", "=", company.id),
            ("state", "not in", ("paid", "waived")),
        ]
        overdue_installments = Installment.search(
            installment_domain + [("due_date", "<", today)],
            order="due_date asc",
        )
        upcoming_installments = Installment.search(
            installment_domain + [("due_date", ">=", today), ("due_date", "<=", soon_date)],
            order="due_date asc",
        )
        all_overdue_installments = Installment.search(
            installment_domain + [("due_date", "<", today)]
        )

        Move = self.env["account.move"].sudo()
        invoice_base = [
            ("company_id", "=", company.id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "not in", ("paid", "reversed")),
            ("amount_residual", ">", 0),
        ]
        overdue_invoices = Move.search(
            invoice_base + [("invoice_date_due", "<", today)],
            order="invoice_date_due asc",
        )
        due_soon_invoices = Move.search(
            invoice_base + [("invoice_date_due", ">=", today),
                            ("invoice_date_due", "<=", soon_date)],
            order="invoice_date_due asc",
        )
        all_overdue_invoices = Move.search(invoice_base + [("invoice_date_due", "<", today)])
        all_unpaid_invoices = Move.search(invoice_base)

        Quant = self.env["stock.quant"].sudo()
        quant_groups = Quant._read_group(
            [
                ("company_id", "=", company.id),
                ("location_id.usage", "=", "internal"),
                ("product_id.is_storable", "=", True),
            ],
            groupby=["product_id", "location_id"],
            aggregates=["quantity:sum"],
        )
        stock_rows = []
        for product, location, quantity in quant_groups:
            if quantity <= 5:
                stock_rows.append({
                    "product_id": product.id,
                    "product": product.display_name,
                    "location_id": location.id,
                    "location": location.complete_name,
                    "quantity": round(quantity, 2),
                    "level": "out" if quantity <= 0 else "low",
                })
        stock_rows.sort(key=lambda row: (row["quantity"], row["product"]))
        out_stock_count = len([row for row in stock_rows if row["level"] == "out"])
        low_stock_count = len([row for row in stock_rows if row["level"] == "low"])
        active_contract_records = self.env["partner.contract"].sudo().search([
            ("company_id", "=", company.id), ("state", "=", "active")
        ])

        def installment_row(line):
            return {
                "id": line.id,
                "contract_id": line.contract_id.id,
                "contract": line.contract_id.name,
                "partner": line.partner_id.display_name,
                "due_date": fields.Date.to_string(line.due_date),
                "remaining": line.amount_remaining,
                "days": (today - line.due_date).days if line.due_date < today
                        else (line.due_date - today).days,
            }

        def invoice_row(invoice):
            due = invoice.invoice_date_due or invoice.invoice_date or today
            return {
                "id": invoice.id,
                "name": invoice.name,
                "partner": invoice.partner_id.display_name,
                "due_date": fields.Date.to_string(due),
                "residual": invoice.amount_residual,
                "days": (today - due).days if due < today else (due - today).days,
            }

        return {
            "company": company.display_name,
            "company_id": company.id,
            "today": fields.Date.to_string(today),
            "currency": currency.symbol or currency.name,
            "kpis": {
                "active_contracts": len(active_contract_records),
                "overdue_contract_count": len(all_overdue_installments),
                "overdue_contract_amount": sum(all_overdue_installments.mapped("amount_remaining")),
                "unpaid_invoice_count": len(all_unpaid_invoices),
                "unpaid_invoice_amount": sum(all_unpaid_invoices.mapped("amount_residual")),
                "overdue_invoice_count": len(all_overdue_invoices),
                "overdue_invoice_amount": sum(all_overdue_invoices.mapped("amount_residual")),
                "low_stock_count": low_stock_count,
                "out_stock_count": out_stock_count,
            },
            "overdue_installments": [installment_row(line) for line in overdue_installments],
            "upcoming_installments": [installment_row(line) for line in upcoming_installments],
            "overdue_invoices": [invoice_row(move) for move in overdue_invoices],
            "due_soon_invoices": [invoice_row(move) for move in due_soon_invoices],
            "stock_rows": stock_rows,
            "active_contract_ids": active_contract_records.ids,
            "unpaid_invoice_ids": all_unpaid_invoices.ids,
            "stock_product_ids": list({row["product_id"] for row in stock_rows}),
        }
