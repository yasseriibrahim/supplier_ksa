from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    custodian_location_id = fields.Many2one(
        "stock.location",
        string="Custodian Stock Location",
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
        help="The only stock location whose quantity this warehouse custodian may maintain.",
    )


class ProductProduct(models.Model):
    _inherit = "product.product"

    custodian_quantity = fields.Float(
        string="Quantity in My Location",
        compute="_compute_custodian_quantity",
        inverse="_inverse_custodian_quantity",
        digits="Product Unit of Measure",
        groups="supplier_ksa.group_warehouse_custodian",
        help="On-hand quantity in the stock location assigned to the current user.",
    )

    def _get_custodian_location(self):
        location = self.env.user.custodian_location_id
        if not location:
            raise ValidationError(
                _("No stock location is assigned to your warehouse custodian user.")
            )
        if location.usage != "internal":
            raise ValidationError(_("The assigned location must be an internal location."))
        if location.company_id and location.company_id not in self.env.companies:
            raise AccessError(_("The assigned stock location is outside your allowed companies."))
        return location

    def _compute_custodian_quantity(self):
        location = self.env.user.custodian_location_id
        Quant = self.env["stock.quant"].sudo()
        for product in self:
            product.custodian_quantity = (
                Quant._get_available_quantity(
                    product, location, strict=True, allow_negative=True,
                )
                if location else 0.0
            )

    def _inverse_custodian_quantity(self):
        location = self._get_custodian_location()
        Quant = self.env["stock.quant"].sudo()
        for product in self:
            if not product.is_storable:
                raise ValidationError(
                    _("Quantities can only be set for stockable products.")
                )
            current = Quant._get_available_quantity(
                product, location, strict=True, allow_negative=True,
            )
            difference = product.custodian_quantity - current
            if not product.uom_id.is_zero(difference):
                Quant._update_available_quantity(
                    product, location, difference,
                )


class ProductTemplate(models.Model):
    _inherit = "product.template"

    custodian_quantity = fields.Float(
        string="Quantity in My Location",
        compute="_compute_custodian_quantity",
        inverse="_inverse_custodian_quantity",
        digits="Product Unit of Measure",
        groups="supplier_ksa.group_warehouse_custodian",
        help="On-hand quantity in the stock location assigned to the current user.",
    )

    def _compute_custodian_quantity(self):
        for template in self:
            template.custodian_quantity = sum(
                template.product_variant_ids.mapped("custodian_quantity")
            )

    def _inverse_custodian_quantity(self):
        for template in self:
            if len(template.product_variant_ids) != 1:
                raise ValidationError(
                    _("Set quantities separately on each product variant.")
                )
            template.product_variant_ids.custodian_quantity = template.custodian_quantity
