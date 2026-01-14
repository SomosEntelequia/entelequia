from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    sap_price_list_id = fields.Many2one(
        "sap.price.list",
        string="Lista de precio SAP",
        domain="[('company_id', '=', company_id)]",
    )

    product_image = fields.Image(
        string="Imagen",
        related="product_id.image_128",
        readonly=True,
    )

    # -----------------------------
    # Helpers (compat Odoo 18/19)
    # -----------------------------
    def _sap_get_uom(self):
        """Odoo 19 renombró product_uom -> product_uom_id.
        Regresa la UdM de la línea de venta de forma compatible.
        """
        self.ensure_one()
        if "product_uom_id" in self._fields:
            return self.product_uom_id
        return getattr(self, "product_uom", False)

    @api.model
    def _sap_uom_field_name(self):
        return "product_uom_id" if "product_uom_id" in self._fields else "product_uom"

    # -----------------------------
    # Core: aplicar precio
    # -----------------------------
    def _sap_apply_price(self, write_mode=False):
        for line in self:
            uom = line._sap_get_uom()
            if not line.sap_price_list_id or not line.product_id or not uom:
                continue

            price = line.sap_price_list_id._get_price(line.product_id, uom)
            if price is None:
                continue

            if write_mode:
                line.with_context(skip_sap_price_apply=True).write({"price_unit": price})
            else:
                line.price_unit = price

    @api.onchange("sap_price_list_id")
    def _onchange_sap_price_list_id(self):
        for line in self:
            uom = line._sap_get_uom()
            if not line.sap_price_list_id or not line.product_id or not uom:
                continue

            price = line.sap_price_list_id._get_price(line.product_id, uom)
            if price is None:
                return {
                    "warning": {
                        "title": "Precio SAP no encontrado",
                        "message": (
                            "No existe una línea de precio en la Lista SAP seleccionada "
                            "para este Producto y esta UdM.\n\n"
                            "Tip: crea la línea en 'Listas de precio SAP' (Producto + UdM + Precio)."
                        ),
                    }
                }

            line.price_unit = price

    # Cuando cambia producto / UdM, re-evaluamos precio SAP
    def _onchange_product_id(self):
        res = super()._onchange_product_id()
        self._sap_apply_price(write_mode=False)
        return res

    # Odoo 18
    def _onchange_product_uom(self):
        parent = super(SaleOrderLine, self)
        method = getattr(parent, "_onchange_product_uom", None)
        res = method() if method else {}
        self._sap_apply_price(write_mode=False)
        return res

    # Odoo 19
    def _onchange_product_uom_id(self):
        parent = super(SaleOrderLine, self)
        method = getattr(parent, "_onchange_product_uom_id", None)
        res = method() if method else {}
        self._sap_apply_price(write_mode=False)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get("skip_sap_price_apply"):
            return lines
        lines._sap_apply_price(write_mode=True)
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_sap_price_apply"):
            return res

        uom_field = self._sap_uom_field_name()
        if {"product_id", uom_field, "sap_price_list_id"} & set(vals.keys()):
            self._sap_apply_price(write_mode=True)
        return res
