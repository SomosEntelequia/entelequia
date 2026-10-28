from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    sap_price_list_id = fields.Many2one(
        "sap.price.list",
        string="Lista de precio SAP",
        domain="[('company_id', '=', company_id)]",
        # Una lista usada en órdenes no se puede eliminar (solo archivar),
        # para que la línea no pierda la referencia y siempre pueda revalidarse.
        ondelete="restrict",
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

    # -----------------------------
    # Validación de vigencia (guardar / confirmar)
    # -----------------------------
    def _sap_get_price_issue(self):
        """Revisa si la línea sigue siendo válida contra su Lista SAP.

        Regresa None si la línea es válida (o no usa Lista SAP),
        o un texto con el motivo por el que ya no es vigente.
        """
        self.ensure_one()
        pricelist = self.sap_price_list_id
        if not pricelist or self.display_type or not self.product_id:
            return None

        pricelist = pricelist.sudo()
        product = self.product_id.sudo()
        uom = self._sap_get_uom()

        if not pricelist.active:
            return _("la Lista SAP «%(list)s» está archivada", list=pricelist.display_name)
        if not product.active:
            return _("el producto está archivado")
        if not uom:
            return _("la línea no tiene unidad de medida")
        if not uom.sudo().active:
            return _("la unidad de medida «%(uom)s» está archivada", uom=uom.display_name)

        price = pricelist._get_price(product, uom)
        if price is None:
            return _(
                "no existe precio en la Lista SAP «%(list)s» para esta unidad de medida",
                list=pricelist.display_name,
            )

        digits = self.env["decimal.precision"].precision_get("Product Price")
        if float_compare(self.price_unit, price, precision_digits=digits) != 0:
            return _(
                "el precio unitario (%(current)s) no coincide con el de la Lista SAP «%(list)s» (%(expected)s)",
                current=round(self.price_unit, digits),
                list=pricelist.display_name,
                expected=round(price, digits),
            )
        return None

    def _sap_collect_price_issues(self):
        """Lista de textos '• Producto (UdM): motivo' de las líneas no vigentes."""
        issues = []
        for line in self:
            issue = line._sap_get_price_issue()
            if issue:
                uom = line._sap_get_uom()
                issues.append(
                    "• %s (%s): %s"
                    % (line.product_id.display_name, uom.display_name if uom else "-", issue)
                )
        return issues

    def _sap_validate_on_save(self):
        """Impide guardar líneas cuyo precio no corresponde a la Lista SAP seleccionada."""
        if self.env.context.get("skip_sap_price_check"):
            return
        lines = self.filtered(lambda l: l.sap_price_list_id and l.order_id.state != "cancel")
        if not lines:
            return
        issues = lines._sap_collect_price_issues()
        if issues:
            raise ValidationError(
                _(
                    "No se puede guardar: hay líneas cuyo precio no corresponde "
                    "a la Lista de precio SAP seleccionada.\n\n%(issues)s\n\n"
                    "Corrige la Lista SAP / UdM de la línea o crea la línea en "
                    "'Listas de precio SAP' (Producto + UdM + Precio).",
                    issues="\n".join(issues),
                )
            )

    # -----------------------------
    # Onchanges
    # -----------------------------
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
                            "No podrás guardar la orden mientras esta línea no tenga "
                            "un precio válido en la lista.\n\n"
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

    # -----------------------------
    # CRUD
    # -----------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get("skip_sap_price_apply"):
            return lines
        lines._sap_apply_price(write_mode=True)
        lines._sap_validate_on_save()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_sap_price_apply"):
            return res

        uom_field = self._sap_uom_field_name()
        if {"product_id", uom_field, "sap_price_list_id"} & set(vals.keys()):
            self._sap_apply_price(write_mode=True)

        # Solo se valida cuando cambia algo que afecta el precio SAP,
        # para no bloquear escrituras técnicas (entregas, facturación, etc.).
        if {"product_id", uom_field, "sap_price_list_id", "price_unit"} & set(vals.keys()):
            self._sap_validate_on_save()
        return res
