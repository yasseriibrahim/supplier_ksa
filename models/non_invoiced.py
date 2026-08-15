from odoo import _, api, fields, models
from odoo.exceptions import UserError
import json


class NonInvoicedOrder(models.Model):
    _name = "non.invoiced.order"
    _description = "Non Invoiced Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_order desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env._("New"),
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        required=True,
        tracking=True,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Warehouse Location",
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
        tracking=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
    )
    picking_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="non_invoiced_order_id",
        string="Transfers",
        readonly=True,
    )
    picking_count = fields.Integer(compute="_compute_picking_count")
    date_order = fields.Date(
        string="Order Date",
        required=True,
        default=fields.Date.context_today,
    )
    line_ids = fields.One2many(
        comodel_name="non.invoiced.order.line",
        inverse_name="order_id",
        string="Order Lines",
        copy=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Currency",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
    )
    allowed_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Products In Stock",
        compute="_compute_allowed_product_ids",
        help="Technical field feeding the product domain on the order lines.",
    )
    note = fields.Html(string="Notes")

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped("price_subtotal"))

    @api.depends("picking_ids")
    def _compute_picking_count(self):
        for order in self:
            order.picking_count = len(order.picking_ids)

    @api.onchange("location_id")
    def _onchange_location_id_set_lines(self):
        for order in self:
            if order.location_id:
                order.line_ids.line_location_id = order.location_id
                order.line_ids._compute_product_domain()

    @api.depends("location_id")
    def _compute_allowed_product_ids(self):
        Quant = self.env["stock.quant"]
        for order in self:
            if not order.location_id:
                order.allowed_product_ids = [(5, 0, 0)]
                continue
            groups = Quant._read_group(
                domain=[
                    ("location_id", "child_of", order.location_id.id),
                    ("location_id.usage", "=", "internal"),
                ],
                groupby=["product_id"],
                aggregates=["quantity:sum"],
            )
            order.allowed_product_ids = [
                product.id for product, quantity in groups if quantity > 0
            ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", self.env._("New")) == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "non.invoiced.order"
                ) or self.env._("New")
        return super().create(vals_list)

    def action_done(self):
        for order in self:
            if order.state == "done":
                continue
            lines = order.line_ids.filtered(
                lambda line: line.product_id.is_storable and line.quantity > 0
            )
            if not lines:
                raise UserError(_("Add at least one stockable product with a positive quantity."))
            missing = lines.filtered(
                lambda line: not (order.location_id or line.line_location_id)
            )
            if missing:
                raise UserError(
                    _("Select a warehouse location on the order or on every stockable line.")
                )
            locations = order.location_id or lines.mapped("line_location_id")
            for location in locations:
                location_lines = lines.filtered(
                    lambda line: (order.location_id or line.line_location_id) == location
                )
                warehouse = location.warehouse_id
                picking_type = warehouse.out_type_id
                if not picking_type:
                    raise UserError(
                        _("Location %s is not attached to an outgoing warehouse operation.",
                          location.display_name)
                    )
                destination = (
                    order.partner_id.property_stock_customer
                    or picking_type.default_location_dest_id
                )
                picking = self.env["stock.picking"].create({
                    "partner_id": order.partner_id.id,
                    "picking_type_id": picking_type.id,
                    "location_id": location.id,
                    "location_dest_id": destination.id,
                    "origin": order.name,
                    "company_id": order.company_id.id,
                    "non_invoiced_order_id": order.id,
                    "scheduled_date": fields.Datetime.now(),
                })
                self.env["stock.move"].create([{
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.quantity,
                    "product_uom": line.product_id.uom_id.id,
                    "picking_id": picking.id,
                    "picking_type_id": picking_type.id,
                    "location_id": location.id,
                    "location_dest_id": destination.id,
                    "partner_id": order.partner_id.id,
                    "company_id": order.company_id.id,
                    "origin": order.name,
                } for line in location_lines])
                order._complete_picking(picking)
            order.state = "done"
        return True

    def _complete_picking(self, picking):
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move_lines = move.move_line_ids
            if move_lines:
                move_lines[0].write({
                    "quantity": move.product_uom_qty,
                    "picked": True,
                })
                (move_lines - move_lines[0]).unlink()
            else:
                self.env["stock.move.line"].create({
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "quantity": move.product_uom_qty,
                    "picked": True,
                })
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()
        if picking.state != "done":
            raise UserError(_("The stock transfer could not be completed."))

    def action_view_picking(self):
        self.ensure_one()
        if not self.picking_ids:
            return False
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", self.picking_ids.ids)]
        action["context"] = {"create": False}
        if len(self.picking_ids) == 1:
            action["views"] = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["res_id"] = self.picking_ids.id
        return action


class NonInvoicedOrderLine(models.Model):
    _name = "non.invoiced.order.line"
    _description = "Non Invoiced Order Line"
    _order = "order_id, sequence, id"

    order_id = fields.Many2one(
        comodel_name="non.invoiced.order",
        string="Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit of Measure",
        default=1.0,
        required=True,
    )
    price_unit = fields.Float(
        string="Unit Price",
        digits="Product Price",
        required=True,
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
        string="Currency",
    )
    company_id = fields.Many2one(
        related="order_id.company_id",
        store=True,
    )
    allowed_product_ids = fields.Many2many(
        related="order_id.allowed_product_ids",
        string="Products In Stock",
    )
    line_location_id = fields.Many2one(
        "stock.location",
        string="Line Location",
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
    )
    product_domain = fields.Char(compute="_compute_product_domain")

    @api.depends("line_location_id", "order_id.location_id")
    def _compute_product_domain(self):
        Quant = self.env["stock.quant"].sudo()
        for line in self:
            location = line.order_id.location_id or line.line_location_id
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

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.order_id.location_id and not line.line_location_id:
                line.line_location_id = line.order_id.location_id
            if line.product_id:
                line.price_unit = line.product_id.lst_price
