import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SapPriceList(models.Model):
    _name = "sap.price.list"
    _description = "Lista de Precio SAP"
    _rec_name = "name"

    name = fields.Char(string="Nombre de la lista de precios", required=True)
    active = fields.Boolean(default=True)

    id_secundario_sap = fields.Char(string="ID Secundario SAP")

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

        Estrategia:
        1) Exacto: busca línea con (product + uom) exactos.
        2) Fallback: busca línea con UdM base del producto y convierte
           mediante _compute_price.

        Nota Odoo 19: uom.uom ya no expone el campo category_id,
        por lo que se eliminó cualquier validación sobre ese campo.
        La compatibilidad entre unidades es responsabilidad de
        _compute_price; si son inconvertibles, Odoo lanzará su propio error.

        Args:
            product (product.product): Producto a buscar.
            uom (uom.uom): Unidad de medida deseada.

        Returns:
            float | None: Precio unitario en la moneda de la lista, o None
                          si no se encuentra ninguna coincidencia.
        """
        self.ensure_one()
        _logger.debug(
            "_get_price | price_list=%s (id=%s) | product=%s (id=%s) | uom=%s (id=%s)",
            self.name,
            self.id,
            product.display_name,
            product.id,
            uom.name,
            uom.id,
        )

        Line = self.env["sap.price.list.line"].sudo()

        # ── 1) Búsqueda exacta producto + UdM solicitada ──────────────────────
        line = Line.search(
            [
                ("price_list_id", "=", self.id),
                ("product_id", "=", product.id),
                ("uom_id", "=", uom.id),
            ],
            limit=1,
        )
        if line:
            _logger.debug(
                "_get_price | Línea exacta encontrada | price_unit=%s %s",
                line.price_unit,
                self.currency_id.name,
            )
            return line.price_unit

        _logger.debug(
            "_get_price | Sin línea exacta, intentando fallback con UdM base del producto."
        )

        # ── 2) Fallback: precio en UdM base + conversión ──────────────────────
        base_uom = product.uom_id
        if not base_uom or base_uom.id == uom.id:
            _logger.warning(
                "_get_price | Sin fallback posible | product=%s | "
                "uom_base=%s | uom_solicitada=%s",
                product.display_name,
                base_uom.name if base_uom else "N/A",
                uom.name,
            )
            return None

        base_line = Line.search(
            [
                ("price_list_id", "=", self.id),
                ("product_id", "=", product.id),
                ("uom_id", "=", base_uom.id),
            ],
            limit=1,
        )

        if not base_line:
            _logger.warning(
                "_get_price | Sin línea en UdM base | price_list=%s | "
                "product=%s | uom_base=%s",
                self.name,
                product.display_name,
                base_uom.name,
            )
            return None

        try:
            converted_price = base_uom._compute_price(base_line.price_unit, uom)
            _logger.debug(
                "_get_price | Precio convertido | %.4f %s (%s) → %.4f %s (%s)",
                base_line.price_unit,
                self.currency_id.name,
                base_uom.name,
                converted_price,
                self.currency_id.name,
                uom.name,
            )
            return converted_price
        except Exception as exc:
            _logger.error(
                "_get_price | Error al convertir precio | product=%s | "
                "%s → %s | error: %s",
                product.display_name,
                base_uom.name,
                uom.name,
                exc,
                exc_info=True,
            )
            return None


class SapPriceListLine(models.Model):
    _name = "sap.price.list.line"
    _description = "Línea de Lista de Precio SAP"
    _order = "product_id, uom_id"

    id_secundario_sap_line = fields.Char(
        string="ID Secundario SAP Línea",
        required=True,
    )

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

    # Sin domain de category_id: campo eliminado en Odoo 19
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
    def _check_uom_compatibility(self):
        """Valida compatibilidad entre la UdM de la línea y la del producto.

        En Odoo 19, uom.uom ya no expone category_id, por lo que no es
        posible verificar la categoría desde Python. Esta constraint emite
        únicamente un aviso informativo en el log cuando las unidades
        difieren; la validación de convertibilidad real ocurre en tiempo
        de cálculo a través de _compute_price.
        """
        for rec in self:
            if not rec.product_id or not rec.uom_id:
                continue

            puom = rec.product_id.uom_id
            if not puom:
                continue

            if puom.id != rec.uom_id.id:
                _logger.info(
                    "_check_uom_compatibility | UdM de línea distinta a UdM base "
                    "del producto | product=%s | uom_producto=%s (id=%s) | "
                    "uom_linea=%s (id=%s) | Verifique que sean convertibles entre sí.",
                    rec.product_id.display_name,
                    puom.name,
                    puom.id,
                    rec.uom_id.name,
                    rec.uom_id.id,
                )
