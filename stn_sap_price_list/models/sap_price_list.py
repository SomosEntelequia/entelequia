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

    id_secundario_sap = fields.Char(
        string="ID Secundario SAP",
        required=True,  # FIX: ahora requerido, igual que en la línea
    )

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

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @staticmethod
    def _uom_are_compatible(uom_a, uom_b):
        """
        Verifica si dos UoM son compatibles para conversión.

        Estrategia multi-versión:
          - Odoo 16/17/18 → compara category_id
          - Odoo 19+       → intenta _compute_price(1.0) y atrapa excepción
          - Sin ninguno    → devuelve True (permisivo) + log de advertencia
        """
        if "category_id" in uom_a._fields and "category_id" in uom_b._fields:
            # Odoo < 19
            compatible = (
                uom_a.category_id
                and uom_b.category_id
                and uom_a.category_id == uom_b.category_id
            )
            _logger.debug(
                "UoM compat check (category_id): '%s'.category=%s | '%s'.category=%s → %s",
                uom_a.name,
                uom_a.category_id.name if uom_a.category_id else "None",
                uom_b.name,
                uom_b.category_id.name if uom_b.category_id else "None",
                compatible,
            )
            return compatible

        if "relative_uom_id" in uom_a._fields:
            # Odoo 19+: usamos _compute_price como árbitro
            try:
                uom_a._compute_price(1.0, uom_b)
                _logger.debug(
                    "UoM compat check (relative_uom_id/Odoo19): '%s' → '%s' → compatible",
                    uom_a.name,
                    uom_b.name,
                )
                return True
            except Exception as exc:
                _logger.debug(
                    "UoM compat check (relative_uom_id/Odoo19): '%s' → '%s' → incompatible (%s)",
                    uom_a.name,
                    uom_b.name,
                    exc,
                )
                return False

        # Sin ningún campo conocido → permisivo con advertencia
        _logger.warning(
            "UoM compat check: campos 'category_id' y 'relative_uom_id' ausentes "
            "en uom.uom. No se puede verificar compatibilidad entre '%s' y '%s'. "
            "Se asume compatible (permisivo).",
            uom_a.name,
            uom_b.name,
        )
        return True

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def _get_price(self, product, uom):
        """
        Retorna el precio según Producto + UdM.

        Flujo:
          1) Búsqueda exacta: (product, uom)
          2) Fallback: busca precio en UdM base del producto
             y convierte con _compute_price si son compatibles.
          3) Retorna None si no encuentra nada; registra WARNING en cada caso.

        Compatible con Odoo 16 / 17 / 18 / 19.
        """
        self.ensure_one()

        _logger.debug(
            "SAP PriceList [%s | id=%s]: _get_price llamado → "
            "product='%s' (id=%s) | uom='%s' (id=%s)",
            self.name, self.id,
            product.display_name, product.id,
            uom.name, uom.id,
        )

        Line = self.env["sap.price.list.line"].sudo()

        # ── 1) Búsqueda exacta ──────────────────────────────────────────
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
                "SAP PriceList [%s]: HIT exacto → línea id=%s | precio=%.4f %s",
                self.name, line.id, line.price_unit, self.currency_id.name,
            )
            return line.price_unit

        _logger.debug(
            "SAP PriceList [%s]: MISS exacto para product id=%s + uom id=%s. "
            "Intentando fallback a UdM base del producto.",
            self.name, product.id, uom.id,
        )

        # ── 2) Fallback a UdM base ──────────────────────────────────────
        base_uom = product.uom_id

        if not base_uom:
            _logger.warning(
                "SAP PriceList [%s]: producto '%s' (id=%s) no tiene UdM base definida. "
                "No es posible hacer fallback. Retorna None.",
                self.name, product.display_name, product.id,
            )
            return None

        if base_uom.id == uom.id:
            # La UdM pedida ES la base y ya no se encontró en exacta → no hay precio
            _logger.warning(
                "SAP PriceList [%s]: no hay precio para product='%s' (id=%s) "
                "en uom base '%s' (id=%s). Retorna None.",
                self.name, product.display_name, product.id,
                uom.name, uom.id,
            )
            return None

        _logger.debug(
            "SAP PriceList [%s]: UdM base del producto = '%s' (id=%s). "
            "Verificando compatibilidad con uom pedida '%s' (id=%s).",
            self.name, base_uom.name, base_uom.id, uom.name, uom.id,
        )

        # ── 2a) Verificar compatibilidad entre UdMs ─────────────────────
        if not self._uom_are_compatible(base_uom, uom):
            _logger.warning(
                "SAP PriceList [%s]: UdM '%s' (id=%s) y UdM base '%s' (id=%s) "
                "del producto '%s' NO son compatibles. No se puede convertir. Retorna None.",
                self.name,
                uom.name, uom.id,
                base_uom.name, base_uom.id,
                product.display_name,
            )
            return None

        # ── 2b) Buscar precio en UdM base ───────────────────────────────
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
                "SAP PriceList [%s]: no hay precio para product='%s' (id=%s) "
                "ni en uom '%s' (id=%s) ni en uom base '%s' (id=%s). Retorna None.",
                self.name,
                product.display_name, product.id,
                uom.name, uom.id,
                base_uom.name, base_uom.id,
            )
            return None

        # ── 2c) Convertir precio ────────────────────────────────────────
        try:
            converted = base_uom._compute_price(base_line.price_unit, uom)
            _logger.info(
                "SAP PriceList [%s]: FALLBACK OK → product='%s' (id=%s) | "
                "precio base %.4f %s [uom='%s' id=%s] → convertido %.4f %s [uom='%s' id=%s]",
                self.name,
                product.display_name, product.id,
                base_line.price_unit, self.currency_id.name,
                base_uom.name, base_uom.id,
                converted, self.currency_id.name,
                uom.name, uom.id,
            )
            return converted

        except Exception as exc:
            _logger.error(
                "SAP PriceList [%s]: ERROR al convertir precio para product='%s' (id=%s) "
                "de uom '%s' (id=%s) a '%s' (id=%s). Excepción: %s. Retorna None.",
                self.name,
                product.display_name, product.id,
                base_uom.name, base_uom.id,
                uom.name, uom.id,
                exc,
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

    # ------------------------------------------------------------------
    # Constrains
    # ------------------------------------------------------------------

    @api.constrains("price_unit")
    def _check_price_unit_positive(self):
        """El precio unitario debe ser mayor que cero."""
        for rec in self:
            if rec.price_unit <= 0:
                _logger.warning(
                    "SAP PriceListLine [id=%s]: precio_unit=%s inválido "
                    "(debe ser > 0) para product='%s' uom='%s' en lista='%s'.",
                    rec.id, rec.price_unit,
                    rec.product_id.display_name if rec.product_id else "N/A",
                    rec.uom_id.name if rec.uom_id else "N/A",
                    rec.price_list_id.name if rec.price_list_id else "N/A",
                )
                raise ValidationError(
                    _("El Precio Unitario debe ser mayor que cero.")
                )

    @api.constrains("product_id", "uom_id")
    def _check_uom_compatibility(self):
        """
        Valida que la UdM de la línea sea compatible con la UdM base del producto.

        Multi-versión:
          - Odoo 16/17/18 → compara category_id
          - Odoo 19+       → intenta _compute_price como árbitro
          - Sin campos     → log de advertencia, no bloquea
        """
        for rec in self:
            if not rec.product_id or not rec.uom_id:
                _logger.debug(
                    "SAP PriceListLine [id=%s]: _check_uom_compatibility omitido "
                    "(product_id o uom_id vacíos).",
                    rec.id,
                )
                continue

            puom = rec.product_id.uom_id
            if not puom:
                _logger.warning(
                    "SAP PriceListLine [id=%s]: producto '%s' (id=%s) no tiene "
                    "UdM base definida. No se puede validar compatibilidad.",
                    rec.id, rec.product_id.display_name, rec.product_id.id,
                )
                continue

            _logger.debug(
                "SAP PriceListLine [id=%s]: validando compatibilidad UdM → "
                "uom_línea='%s' (id=%s) vs uom_base_producto='%s' (id=%s)",
                rec.id,
                rec.uom_id.name, rec.uom_id.id,
                puom.name, puom.id,
            )

            # ── Odoo 16/17/18: category_id ─────────────────────────────
            if "category_id" in rec.uom_id._fields and "category_id" in puom._fields:
                if (
                    rec.uom_id.category_id
                    and puom.category_id
                    and rec.uom_id.category_id != puom.category_id
                ):
                    _logger.warning(
                        "SAP PriceListLine [id=%s]: UdM '%s' (cat='%s') incompatible "
                        "con UdM base '%s' (cat='%s') del producto '%s'.",
                        rec.id,
                        rec.uom_id.name, rec.uom_id.category_id.name,
                        puom.name, puom.category_id.name,
                        rec.product_id.display_name,
                    )
                    raise ValidationError(
                        _(
                            "La Unidad de Medida '%(uom)s' debe pertenecer a la misma "
                            "categoría que la UdM del producto ('%(puom)s').",
                            uom=rec.uom_id.name,
                            puom=puom.name,
                        )
                    )
                _logger.debug(
                    "SAP PriceListLine [id=%s]: UdM OK por category_id.",
                    rec.id,
                )
                continue

            # ── Odoo 19+: relative_uom_id ──────────────────────────────
            if "relative_uom_id" in rec.uom_id._fields:
                try:
                    puom._compute_price(1.0, rec.uom_id)
                    _logger.debug(
                        "SAP PriceListLine [id=%s]: UdM OK por relative_uom_id (Odoo 19).",
                        rec.id,
                    )
                except Exception as exc:
                    _logger.warning(
                        "SAP PriceListLine [id=%s]: UdM '%s' incompatible con "
                        "UdM base '%s' del producto '%s' (Odoo 19). Error: %s",
                        rec.id,
                        rec.uom_id.name, puom.name,
                        rec.product_id.display_name, exc,
                    )
                    raise ValidationError(
                        _(
                            "La Unidad de Medida '%(uom)s' no es compatible con "
                            "la UdM base '%(puom)s' del producto.",
                            uom=rec.uom_id.name,
                            puom=puom.name,
                        )
                    )
                continue

            # ── Sin campos conocidos ────────────────────────────────────
            _logger.warning(
                "SAP PriceListLine [id=%s]: no se encontraron campos 'category_id' ni "
                "'relative_uom_id' en uom.uom. No se puede validar compatibilidad de UdM "
                "para producto '%s'. Se omite validación.",
                rec.id, rec.product_id.display_name,
            )
