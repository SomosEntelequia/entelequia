from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SapPriceList(models.Model):
    _name = "sap.price.list"
    _description = "Lista de Precio SAP"
    _rec_name = "name"

    name = fields.Char(string="Nombre de la lista de precios", required=True)
    active = fields.Boolean(default=True)
    
    id_secundario_sap = fields.Char(string="Nombre de la lista de precios")
    
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
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
    _order = "product_id, uom_id"
    id_secundario_sap_line =  fields.Char(string="Nombre de la lista de precios", required=True)
    
    price_list_id = fields.Many2one(
        "sap.price.list",
        string="Lista de precio SAP",
        required=True,
        ondelete="cascade",
        index=True,
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
    )

    # Sin domain para evitar fallos de validación en builds con cambios en uom.uom
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad de medida",
        required=True,
    )

    price_unit = fields.Monetary(
        string="Precio unitario",
        required=True,
        currency_field="currency_id",
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
