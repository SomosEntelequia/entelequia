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
        """
        Regresa el precio según Producto + UdM.
        1) Exacto: (product + uom)
        2) Fallback: si existe precio en UdM base, intenta convertir
           (solo si existe category_id y coincide)
        """
        self.ensure_one()

        _logger.info("========== INICIO _get_price ==========")
        _logger.info("Lista de precio ID: %s", self.id)
        _logger.info("Lista de precio Nombre: %s", self.name)
        _logger.info("Producto ID: %s", product.id if product else "N/A")
        _logger.info("Producto Nombre: %s", product.display_name if product else "N/A")
        _logger.info("UdM solicitada ID: %s", uom.id if uom else "N/A")
        _logger.info("UdM solicitada Nombre: %s", uom.display_name if uom else "N/A")

        Line = self.env["sap.price.list.line"].sudo()

        line = Line.search(
            [
                ("price_list_id", "=", self.id),
                ("product_id", "=", product.id),
                ("uom_id", "=", uom.id),
            ],
            limit=1,
        )

        _logger.info("Línea exacta encontrada: %s", line.id if line else "No")

        if line:
            _logger.info("Precio exacto encontrado: %s", line.price_unit)
            _logger.info("========== FIN _get_price (exacto) ==========")
            return line.price_unit

        base_uom = product.uom_id
        _logger.info("UdM base del producto ID: %s", base_uom.id if base_uom else "N/A")
        _logger.info("UdM base del producto Nombre: %s", base_uom.display_name if base_uom else "N/A")

        if not base_uom:
            _logger.warning("No hay UdM base en el producto.")
            _logger.info("========== FIN _get_price (sin UdM base) ==========")
            return None

        #if base_uom.id == uom.id:
        #    _logger.warning("La UdM solicitada es igual a la UdM base, pero no se encontró línea exacta.")
        #    _logger.info("========== FIN _get_price (misma UdM sin línea) ==========")
        #    return None

        # Algunos builds (Odoo 19) ya no traen category_id en uom.uom
        has_category_base = "category_id" in base_uom._fields
        has_category_uom = "category_id" in uom._fields

        _logger.info("¿base_uom tiene category_id?: %s", has_category_base)
        _logger.info("¿uom solicitada tiene category_id?: %s", has_category_uom)

        if has_category_base and has_category_uom:
            _logger.info(
                "Categoría UdM base: %s",
                base_uom.category_id.display_name if base_uom.category_id else "N/A",
            )
            _logger.info(
                "Categoría UdM solicitada: %s",
                uom.category_id.display_name if uom.category_id else "N/A",
            )

            if (
                base_uom.category_id
                and uom.category_id
                and base_uom.category_id == uom.category_id
            ):
                _logger.info("Las categorías de UdM coinciden. Buscando línea en UdM base...")

                base_line = Line.search(
                    [
                        ("price_list_id", "=", self.id),
                        ("product_id", "=", product.id),
                        ("uom_id", "=", base_uom.id),
                    ],
                    limit=1,
                )

                _logger.info("Línea base encontrada: %s", base_line.id if base_line else "No")

                if base_line:
                    converted_price = base_uom._compute_price(base_line.price_unit, uom)
                    _logger.info("Precio base encontrado: %s", base_line.price_unit)
                    _logger.info("Precio convertido a UdM solicitada: %s", converted_price)
                    _logger.info("========== FIN _get_price (convertido) ==========")
                    return converted_price
                else:
                    _logger.warning("No se encontró línea base para convertir.")
            else:
                _logger.warning("Las categorías de UdM no coinciden o alguna categoría está vacía.")
        else:
            _logger.warning("Alguna de las UdM no tiene campo category_id en este build.")

        _logger.warning("No se pudo determinar precio.")
        _logger.info("========== FIN _get_price (None) ==========")
        return None


class SapPriceListLine(models.Model):
    _name = "sap.price.list.line"
    _description = "Línea de Lista de Precio SAP"
    _order = "product_id, uom_id"

    id_secundario_sap_line = fields.Char(string="Nombre de la lista de precios", required=True)

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
        _logger.info("========== INICIO _check_uom_same_category_when_available ==========")

        for rec in self:
            _logger.info("----------------------------------------")
            _logger.info("Registro línea ID: %s", rec.id if rec.id else "Nuevo")
            _logger.info("Producto: %s", rec.product_id.display_name if rec.product_id else "N/A")
            _logger.info("UdM seleccionada: %s", rec.uom_id.display_name if rec.uom_id else "N/A")

            if not rec.product_id or not rec.uom_id:
                _logger.warning("Falta producto o UdM. Se omite validación.")
                continue

            puom = rec.product_id.uom_id
            _logger.info("UdM del producto: %s", puom.display_name if puom else "N/A")

            if not puom:
                _logger.warning("El producto no tiene UdM definida. Se omite validación.")
                continue

            has_category_rec = "category_id" in rec.uom_id._fields
            has_category_puom = "category_id" in puom._fields

            _logger.info("¿UdM seleccionada tiene category_id?: %s", has_category_rec)
            _logger.info("¿UdM del producto tiene category_id?: %s", has_category_puom)

            if has_category_rec and has_category_puom:
                _logger.info(
                    "Categoría UdM seleccionada: %s",
                    rec.uom_id.category_id.display_name if rec.uom_id.category_id else "N/A",
                )
                _logger.info(
                    "Categoría UdM producto: %s",
                    puom.category_id.display_name if puom.category_id else "N/A",
                )

                if (
                    rec.uom_id.category_id
                    and puom.category_id
                    and rec.uom_id.category_id != puom.category_id
                ):
                    _logger.error("ERROR: La categoría de la UdM no coincide con la del producto.")
                    _logger.info("========== FIN _check_uom_same_category_when_available (ValidationError) ==========")
                    raise ValidationError(
                        _("La Unidad de Medida debe pertenecer a la misma categoría que la UdM del producto.")
                    )
                else:
                    _logger.info("Validación correcta: categorías compatibles.")
            else:
                _logger.warning("Alguna de las UdM no tiene category_id en este build. No se valida categoría.")

        _logger.info("========== FIN _check_uom_same_category_when_available ==========")
