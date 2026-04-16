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

    def _resolve_product_variant(self, product):
        """Garantiza que siempre trabajemos con product.product.

        Si se recibe un product.template, resuelve a su variante principal.
        Si ya es product.product, lo devuelve sin cambios.

        Args:
            product: recordset de product.template o product.product.

        Returns:
            product.product | None: variante resuelta, o None si no existe.
        """
        if product._name == "product.template":
            _logger.debug(
                "_resolve_product_variant | Se recibió product.template (id=%s), "
                "resolviendo a product.product.",
                product.id,
            )
            variant = product.product_variant_id
            if not variant:
                _logger.warning(
                    "_resolve_product_variant | product.template sin variante "
                    "definida | template_id=%s | display_name=%s",
                    product.id,
                    product.display_name,
                )
                return None
            _logger.debug(
                "_resolve_product_variant | Variante resuelta | "
                "product.product id=%s | display_name=%s",
                variant.id,
                variant.display_name,
            )
            return variant

        # Ya es product.product, no se toca nada
        return product

    def _get_price(self, product, uom):
        """Regresa el precio según Producto + UdM.

        Estrategia:
        1) Resolución: asegura que 'product' sea product.product (no template).
        2) Exacto: busca línea con (product.product + uom) exactos.
        3) Fallback: busca línea con UdM base del producto y convierte
           mediante _compute_price. Solo aplica si la UdM base existe
           y es distinta a la UdM solicitada.

        Nota Odoo 19: uom.uom ya no expone el campo category_id,
        por lo que se eliminó cualquier validación sobre ese campo.
        La compatibilidad entre unidades es responsabilidad de
        _compute_price; si son inconvertibles, Odoo lanzará su propio error.

        Si el producto no tiene UdM base definida (base_uom vacío),
        se permite continuar sin bloquear.

        Args:
            product: product.product o product.template a buscar.
            uom (uom.uom): Unidad de medida deseada.

        Returns:
            float | None: Precio unitario en la moneda de la lista, o None
                          si no se encuentra ninguna coincidencia.
        """
        self.ensure_one()

        # ── 1) Resolución product.template → product.product ─────────────────
        product = self._resolve_product_variant(product)
        if not product:
            return None

        _logger.debug(
            "_get_price | price_list=%s (id=%s) | "
            "product=%s (id=%s) [%s] | uom=%s (id=%s)",
            self.name,
            self.id,
            product.display_name,
            product.id,
            product._name,   # confirma que ya es product.product
            uom.name,
            uom.id,
        )

        Line = self.env["sap.price.list.line"].sudo()

        # ── Diagnóstico: líneas existentes para el producto en esta lista ─────
        existing_lines = Line.search([
            ("price_list_id", "=", self.id),
            ("product_id", "=", product.id),
        ])
        _logger.debug(
            "_get_price | Líneas existentes para el producto en la lista | %s",
            [(l.uom_id.id, l.uom_id.name, l.price_unit) for l in existing_lines],
        )

        # ── 2) Búsqueda exacta producto + UdM solicitada ──────────────────────
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
            "_get_price | Sin línea exacta, evaluando fallback con UdM base del producto."
        )

        # ── 3) Fallback: precio en UdM base + conversión ──────────────────────
        base_uom = product.uom_id

        # Sin UdM base: no hay conversión posible, paso 1 ya cubrió este caso
        if not base_uom:
            _logger.warning(
                "_get_price | Producto sin UdM base definida, no hay fallback | "
                "price_list=%s | product=%s | uom=%s",
                self.name,
                product.display_name,
                uom.name,
            )
            return None

        # UdM solicitada == UdM base: paso 2 ya lo intentó sin éxito
        if base_uom.id == uom.id:
            _logger.warning(
                "_get_price | Sin precio exacto y UdM solicitada == UdM base, "
                "no hay conversión aplicable | "
                "price_list=%s | product=%s | uom=%s (id=%s)",
                self.name,
                product.display_name,
                uom.name,
                uom.id,
            )
            return None

        # UdM base distinta a la solicitada: buscar en UdM base y convertir
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
                "product=%s | uom_base=%s (id=%s)",
                self.name,
                product.display_name,
                base_uom.name,
                base_uom.id,
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

        Si el producto no tiene UdM base definida (base_uom vacío),
        se permite guardar la línea sin restricción.
        """
        for rec in self:
            if not rec.product_id or not rec.uom_id:
                continue

            puom = rec.product_id.uom_id

            # Sin UdM base en el producto: se permite sin restricción
            if not puom:
                _logger.info(
                    "_check_uom_compatibility | Producto sin UdM base definida, "
                    "se omite validación | product=%s | uom_linea=%s (id=%s)",
                    rec.product_id.display_name,
                    rec.uom_id.name,
                    rec.uom_id.id,
                )
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
