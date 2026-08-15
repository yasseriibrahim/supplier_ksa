# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
import math
import json

STOCK_MOVE_TYPES = ("out_invoice", "out_refund", "in_invoice", "in_refund")

def _int_to_arabic(n):
    """Convert a non-negative integer to Arabic words."""
    if n == 0:
        return 'صفر'

    ones = [
        '', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة',
        'عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر',
        'ستة عشر', 'سبعة عشر', 'ثمانية عشر', 'تسعة عشر',
    ]
    tens = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
    hundreds = [
        '', 'مئة', 'مئتان', 'ثلاثمئة', 'أربعمئة',
        'خمسمئة', 'ستمئة', 'سبعمئة', 'ثمانمئة', 'تسعمئة',
    ]

    def _below_hundred(num):
        if num == 0:
            return ''
        if num < 20:
            return ones[num]
        t, o = divmod(num, 10)
        if o == 0:
            return tens[t]
        return ones[o] + ' و' + tens[t]

    def _below_thousand(num):
        if num == 0:
            return ''
        if num < 100:
            return _below_hundred(num)
        h, rest = divmod(num, 100)
        h_word = hundreds[h]
        if rest == 0:
            return h_word
        return h_word + ' و' + _below_hundred(rest)

    parts = []
    if n >= 1_000_000_000:
        chunk, n = divmod(n, 1_000_000_000)
        parts.append(_below_thousand(chunk) + ' مليار')
    if n >= 1_000_000:
        chunk, n = divmod(n, 1_000_000)
        parts.append(_below_thousand(chunk) + ' مليون')
    if n >= 1_000:
        chunk, n = divmod(n, 1_000)
        if chunk == 1:
            parts.append('ألف')
        elif chunk == 2:
            parts.append('ألفان')
        else:
            parts.append(_below_thousand(chunk) + ' ألف')
    if n > 0:
        parts.append(_below_thousand(n))

    return ' و'.join(parts)


def amount_to_arabic_words(amount, currency_name='ريال', fils_name='هللة'):
    """Convert a float amount to Arabic words with currency."""
    amount = round(amount, 2)
    riyals = int(amount)
    fils = round((amount - riyals) * 100)
    result = _int_to_arabic(riyals) + ' ' + currency_name
    if fils:
        result += ' و' + _int_to_arabic(fils) + ' ' + fils_name
    return result + ' فقط لا غير'


class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_discount = fields.Monetary(
        string='Discount',
        compute='_compute_amount_discount',
        currency_field='currency_id',
        store=True,
    )
    amount_total_words = fields.Char(
        string='Amount in Words',
        compute='_compute_amount_total_words',
        store=True,
    )
    agent_id = fields.Many2one('res.partner', string='Agent Name')
    driver_name = fields.Many2one('res.partner', string='Driver Name')
    branch_name = fields.Char(string='Branch Name')
    collect_type = fields.Selection([
        ('cash', 'Cash'),
        ('credit', 'Credit'),
    ], string='Payment Way')
    invoice_region = fields.Selection([
        ('الدمام', 'الدمام'),
        ('الرياض', 'الرياض'),
        ('جده', 'جده'),
    ], string='Invoice Region')

    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Warehouse Location",
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
        copy=False,
        help="Products available in this exact location (and its children) can be invoiced. "
             "On confirmation, the delivery is created and validated automatically.",
    )
    allowed_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Products In Stock",
        compute="_compute_allowed_product_ids",
        help="Technical field feeding the product domain on invoice lines.",
    )
    picking_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="invoice_move_id",
        string="Transfers",
        readonly=True,
    )
    picking_count = fields.Integer(compute="_compute_picking_count")





    @api.depends('amount_total', 'currency_id')
    def _compute_amount_total_words(self):
        for move in self:
            move.amount_total_words = amount_to_arabic_words(move.amount_total)

    @api.depends('invoice_line_ids.discount', 'invoice_line_ids.price_unit',
                 'invoice_line_ids.quantity', 'invoice_line_ids.display_type')
    def _compute_amount_discount(self):
        for move in self:
            total = 0.0
            for line in move.invoice_line_ids.filtered(
                    lambda l: l.display_type not in ('line_section', 'line_note')):
                total += line.price_unit * line.quantity * (line.discount / 100.0)
            move.amount_discount = total

    def action_post(self):
        res = super().action_post()
        for move in self:
            if not move.qr:
                try:
                    move.generate_qr_button()
                except Exception:
                    pass
        return res

    def action_print_custom_invoice(self):
        return self.env.ref('supplier_ksa.action_custom_invoice_report').report_action(self)

    @api.onchange("location_id")
    def _onchange_location_id_set_lines(self):
        for move in self:
            if move.location_id:
                move.invoice_line_ids.line_location_id = move.location_id
                move.invoice_line_ids._compute_product_domain()




    @api.depends("location_id")
    def _compute_allowed_product_ids(self):
        Quant = self.env["stock.quant"]
        for move in self:
            if not move.location_id:
                move.allowed_product_ids = [(5, 0, 0)]
                continue
            groups = Quant._read_group(
                domain=[
                    ("location_id", "child_of", move.location_id.id),
                    ("location_id.usage", "=", "internal"),
                ],
                groupby=["product_id"],
                aggregates=["quantity:sum"],
            )
            move.allowed_product_ids = [
                product.id for product, quantity in groups if quantity > 0
            ]

    @api.depends("picking_ids")
    def _compute_picking_count(self):
        for move in self:
            move.picking_count = len(move.picking_ids)

    # ------------------------------------------------------------------
    # Stock cycle
    # ------------------------------------------------------------------

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted._create_invoice_picking()
        return posted

    def _create_invoice_picking(self):
        for move in self:
            if move.move_type not in STOCK_MOVE_TYPES:
                continue
            if move.picking_ids:
                continue
            lines = move.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
                and line.product_id.is_storable
                and line.quantity > 0
            )
            if not lines:
                continue
            missing = lines.filtered(
                lambda line: not (move.location_id or line.line_location_id)
            )
            if missing:
                raise UserError(
                    _("Select a warehouse location on the invoice or on every stockable line.")
                )
            locations = (move.location_id or lines.mapped("line_location_id"))
            for location in locations:
                location_lines = lines.filtered(
                    lambda line: (move.location_id or line.line_location_id) == location
                )
                picking_type = move._get_picking_type(location)
                picking = self.env["stock.picking"].create(
                    move._prepare_picking_vals(picking_type, location)
                )
                self.env["stock.move"].create(
                    [move._prepare_stock_move_vals(line, picking) for line in location_lines]
                )
                move._complete_invoice_picking(picking)

    def _complete_invoice_picking(self, picking):
        picking.action_confirm()
        picking.action_assign()
        for stock_move in picking.move_ids:
            move_lines = stock_move.move_line_ids
            if move_lines:
                move_lines[0].write({
                    "quantity": stock_move.product_uom_qty,
                    "picked": True,
                })
                (move_lines - move_lines[0]).unlink()
            else:
                self.env["stock.move.line"].create({
                    "move_id": stock_move.id,
                    "picking_id": picking.id,
                    "product_id": stock_move.product_id.id,
                    "product_uom_id": stock_move.product_uom.id,
                    "location_id": stock_move.location_id.id,
                    "location_dest_id": stock_move.location_dest_id.id,
                    "quantity": stock_move.product_uom_qty,
                    "picked": True,
                })
            stock_move.quantity = stock_move.product_uom_qty
            stock_move.picked = True
        picking.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()

    def _get_picking_type(self, location):
        self.ensure_one()
        warehouse = location.warehouse_id
        if self.move_type in ("out_invoice", "in_refund"):
            picking_type = warehouse.out_type_id
        else:
            picking_type = warehouse.in_type_id
        if not picking_type:
            raise UserError(
                _("Location %s is not attached to a warehouse operation type.",
                  location.display_name)
            )
        return picking_type

    def _prepare_picking_vals(self, picking_type, selected_location):
        self.ensure_one()
        customer_location = self.partner_id.property_stock_customer
        if self.move_type in ("out_invoice", "in_refund"):
            location = selected_location
            location_dest = customer_location or picking_type.default_location_dest_id
        else:
            location = customer_location or picking_type.default_location_src_id
            location_dest = selected_location
        return {
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            # The invoice action context contains default_move_type=out_invoice.
            # Never let that accounting value leak into stock.picking.move_type.
            "move_type": "direct",
            "location_id": location.id,
            "location_dest_id": location_dest.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "invoice_move_id": self.id,
            "scheduled_date": fields.Datetime.now(),
        }

    def _prepare_stock_move_vals(self, line, picking):
        self.ensure_one()
        return {
            "product_id": line.product_id.id,
            "product_uom_qty": line.quantity,
            "product_uom": (line.product_uom_id or line.product_id.uom_id).id,
            "picking_id": picking.id,
            "picking_type_id": picking.picking_type_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "partner_id": picking.partner_id.id,
            "company_id": picking.company_id.id,
            "origin": self.name,
        }

    # ------------------------------------------------------------------
    # Guards & actions
    # ------------------------------------------------------------------

    def button_draft(self):
        blocked = self.picking_ids.filtered(lambda p: p.state == "done")
        if blocked:
            raise UserError(
                _("Reverse the transfer %s before resetting this invoice to draft.",
                  ", ".join(blocked.mapped("name")))
            )
        self.picking_ids.action_cancel()
        return super().button_draft()

    def action_view_pickings(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", self.picking_ids.ids)]
        action["context"] = {"create": False}
        if len(self.picking_ids) == 1:
            action["views"] = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["res_id"] = self.picking_ids.id
        return action


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    allowed_product_ids = fields.Many2many(
        related="move_id.allowed_product_ids",
        string="Products In Stock",
    )
    line_location_id = fields.Many2one(
        "stock.location",
        string="Line Location",
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
    )
    product_domain = fields.Char(compute="_compute_product_domain")

    @api.depends("line_location_id", "move_id.location_id")
    def _compute_product_domain(self):
        Quant = self.env["stock.quant"].sudo()
        for line in self:
            location = line.move_id.location_id or line.line_location_id
            if not location:
                line.product_domain = json.dumps([])
                continue
            groups = Quant._read_group(
                [("location_id", "child_of", location.id),
                 ("location_id.usage", "=", "internal")],
                groupby=["product_id"], aggregates=["quantity:sum"],
            )
            product_ids = [product.id for product, quantity in groups if quantity > 0]
            line.product_domain = json.dumps([["id", "in", product_ids]])

    @api.onchange("line_location_id")
    def _onchange_line_location_product_domain(self):
        for line in self:
            line._compute_product_domain()
            domain = json.loads(line.product_domain)
            allowed_ids = domain[0][2] if domain else None
            if allowed_ids is not None and line.product_id and line.product_id.id not in allowed_ids:
                line.product_id = False

    @api.onchange("product_id")
    def _onchange_product_line_location(self):
        for line in self:
            if line.move_id.location_id and not line.line_location_id:
                line.line_location_id = line.move_id.location_id
