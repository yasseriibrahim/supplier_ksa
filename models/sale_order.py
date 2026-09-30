from odoo import api, fields, models

from .account_move import amount_to_arabic_words


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # These report-only aliases allow quotations to render through the exact
    # custom invoice template, keeping one shared visual design.
    invoice_line_ids = fields.One2many(
        "sale.order.line", "order_id", string="Quotation Lines", readonly=True,
    )
    invoice_date = fields.Datetime(related="date_order")
    invoice_date_due = fields.Date(related="validity_date")
    invoice_payment_term_id = fields.Many2one(related="payment_term_id")
    narration = fields.Html(related="note")
    ref = fields.Char(related="client_order_ref")
    qr = fields.Binary(compute="_compute_custom_quotation_report_fields")
    move_type = fields.Selection(
        [("sale", "Quotation")], compute="_compute_custom_quotation_report_fields",
    )
    payment_state = fields.Selection(
        [("not_paid", "Quotation")], compute="_compute_custom_quotation_report_fields",
    )
    driver_name = fields.Many2one(
        "res.partner", compute="_compute_custom_quotation_report_fields",
    )
    invoice_region = fields.Char(compute="_compute_custom_quotation_report_fields")
    collect_type = fields.Char(compute="_compute_custom_quotation_report_fields")
    branch_name = fields.Char(compute="_compute_custom_quotation_report_fields")
    amount_discount = fields.Monetary(
        compute="_compute_custom_quotation_amounts", currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        compute="_compute_custom_quotation_amounts", currency_field="currency_id",
    )
    amount_total_words = fields.Char(compute="_compute_custom_quotation_amounts")
    agent_id = fields.Many2one('res.partner', string='Agent Name')


    def _compute_custom_quotation_report_fields(self):
        for order in self:
            order.qr = False
            order.move_type = "sale"
            order.payment_state = "not_paid"


    @api.depends(
        "order_line.discount", "order_line.price_unit", "order_line.product_uom_qty",
        "amount_total", "currency_id",
    )
    def _compute_custom_quotation_amounts(self):
        for order in self:
            order.amount_discount = sum(
                line.price_unit * line.product_uom_qty * line.discount / 100.0
                for line in order.order_line.filtered(
                    lambda line: line.display_type == "product"
                )
            )
            order.amount_residual = order.amount_total
            order.amount_total_words = amount_to_arabic_words(order.amount_total)

    def action_print_custom_quotation(self):
        return self.env.ref(
            "supplier_ksa.action_custom_quotation_report"
        ).report_action(self)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    quantity = fields.Float(related="product_uom_qty", readonly=True)
