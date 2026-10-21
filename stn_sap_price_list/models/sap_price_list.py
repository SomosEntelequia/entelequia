from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SapPriceList(models.Model):
    _name = "sap.price.list"
    _description = "Lista de Precio SAP"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "name"

    name = fields.Char(string="Nombre de la lista de precios", required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    id_secundario_sap = fields.Char(string="Nombre de la lista de precios", tracking=True)

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    line_ids = fields.One2many(
        "sap.price.list.line",
        "price_list_id",
        string="Líneas",
        copy=True,
    )

    def _get_price(self, product, uom):
        """Regresa el precio según Producto + UdM.
        1) Exacto: (product + uom)
        2) Fallback: si existe precio en UdM base, intenta convertir (solo si existe category_id y coincide)
        """
        self.ensure_one()
        Line = self.env["sap.price.list.line"].sudo()

        line = Line.search(
            [
                ("price_list_id", "=", self.id),
                ("product_id", "=", product.id),
                ("uom_id", "=", uom.id),
            ],
            limit=1,
        )
        if line:
            return line.price_unit

        base_uom = product.uom_id
        if not base_uom or base_uom.id == uom.id:
            return None

        # Algunos builds (Odoo 19) ya no traen category_id en uom.uom
        if "category_id" in base_uom._fields and "category_id" in uom._fields:
            if base_uom.category_id and uom.category_id and base_uom.category_id == uom.category_id:
                base_line = Line.search(
                    [
                        ("price_list_id", "=", self.id),
                        ("product_id", "=", product.id),
                        ("uom_id", "=", base_uom.id),
                    ],
                    limit=1,
                )
                if base_line:
                    return base_uom._compute_price(base_line.price_unit, uom)

        return None


class SapPriceListLine(models.Model):
    _name = "sap.price.list.line"
    _description = "Línea de Lista de Precio SAP"
    _inherit = ["mail.thread"]
    _order = "product_id, uom_id"

    id_secundario_sap_line = fields.Char(string="Nombre de la lista de precios", required=True, tracking=True)

    price_list_id = fields.Many2one(
        "sap.price.list",
        string="Lista de precio SAP",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="price_list_id.company_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="price_list_id.currency_id",
        store=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        index=True,
        tracking=True,
    )

    # Sin domain para evitar fallos de validación en builds con cambios en uom.uom
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad de medida",
        required=True,
        tracking=True,
    )

    price_unit = fields.Monetary(
        string="Precio unitario",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )

    _sql_constraints = [
        (
            "uniq_list_product_uom",
            "unique(price_list_id, product_id, uom_id)",
            "Ya existe una línea para ese Producto y esa UdM dentro de la misma Lista SAP.",
        )
    ]

    @api.constrains("product_id", "uom_id")
    def _check_uom_same_category_when_available(self):
        """Validación suave: si existe category_id, fuerza misma categoría."""
        for rec in self:
            if not rec.product_id or not rec.uom_id:
                continue
            puom = rec.product_id.uom_id
            if not puom:
                continue

            if "category_id" in rec.uom_id._fields and "category_id" in puom._fields:
                if rec.uom_id.category_id and puom.category_id and rec.uom_id.category_id != puom.category_id:
                    raise ValidationError(
                        _("La Unidad de Medida debe pertenecer a la misma categoría que la UdM del producto.")
                    )

    # -----------------------------
    # Registro de cambios en el chatter de la lista padre
    # -----------------------------
    def _sap_line_label(self):
        self.ensure_one()
        return "%s / %s" % (self.product_id.display_name, self.uom_id.display_name)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line.price_list_id.message_post(
                body=_("Línea agregada: %(line)s = %(price)s",
                       line=line._sap_line_label(), price=line.price_unit),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        return lines

    def write(self, vals):
        tracked = {"product_id", "uom_id", "price_unit", "id_secundario_sap_line"}
        before = {}
        if tracked & set(vals):
            before = {line.id: (line._sap_line_label(), line.price_unit) for line in self}
        res = super().write(vals)
        for line in self:
            if line.id not in before:
                continue
            old_label, old_price = before[line.id]
            new_label, new_price = line._sap_line_label(), line.price_unit
            if (old_label, old_price) == (new_label, new_price):
                continue
            line.price_list_id.message_post(
                body=_("Línea modificada: %(old)s = %(old_price)s → %(new)s = %(new_price)s",
                       old=old_label, old_price=old_price, new=new_label, new_price=new_price),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        return res

    def unlink(self):
        for line in self:
            line.price_list_id.message_post(
                body=_("Línea eliminada: %(line)s = %(price)s",
                       line=line._sap_line_label(), price=line.price_unit),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        return super().unlink()
