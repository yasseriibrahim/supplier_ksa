from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    invoice_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Source Invoice",
        copy=False,
        index=True,
        ondelete="set null",
    )
    non_invoiced_order_id = fields.Many2one(
        comodel_name="non.invoiced.order",
        string="Non Invoiced Order",
        copy=False,
        index=True,
        ondelete="set null",
    )
