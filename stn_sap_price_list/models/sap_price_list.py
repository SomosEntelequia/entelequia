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
        """
        Regresa el precio según Producto + UdM.
        1) Exacto: (product + uom)
        2) Fallback: si existe precio en UdM base, intenta convertir
           (solo si existe category_id y coincide)
        """
        self.ensure_one()

        print("========== INICIO _get_price ==========")
        print(f"Lista de precio ID: {self.id}")
        print(f"Lista de precio Nombre: {self.name}")
        print(f"Producto ID: {product.id if product else 'N/A'}")
        print(f"Producto Nombre: {product.display_name if product else 'N/A'}")
        print(f"UdM solicitada ID: {uom.id if uom else 'N/A'}")
        print(f"UdM solicitada Nombre: {uom.display_name if uom else 'N/A'}")

        Line = self.env["sap.price.list.line"].sudo()

        line = Line.search(
            [
                ("price_list_id", "=", self.id),
                ("product_id", "=", product.id),
                ("uom_id", "=", uom.id),
            ],
            limit=1,
        )

        print(f"Línea exacta encontrada: {line.id if line else 'No'}")

        if line:
            print(f"Precio exacto encontrado: {line.price_unit}")
            print("========== FIN _get_price (exacto) ==========")
            return line.price_unit

        base_uom = product.uom_id
        print(f"UdM base del producto ID: {base_uom.id if base_uom else 'N/A'}")
        print(f"UdM base del producto Nombre: {base_uom.display_name if base_uom else 'N/A'}")

        if not base_uom:
            print("No hay UdM base en el producto.")
            print("========== FIN _get_price (sin UdM base) ==========")
            return None

        if base_uom.id == uom.id:
            print("La UdM solicitada es igual a la UdM base, pero no se encontró línea exacta.")
            print("========== FIN _get_price (misma UdM sin línea) ==========")
            return None

        # Algunos builds (Odoo 19) ya no traen category_id en uom.uom
        has_category_base = "category_id" in base_uom._fields
        has_category_uom = "category_id" in uom._fields

        print(f"¿base_uom tiene category_id?: {has_category_base}")
        print(f"¿uom solicitada tiene category_id?: {has_category_uom}")

        if has_category_base and has_category_uom:
            print(f"Categoría UdM base: {base_uom.category_id.display_name if base_uom.category_id else 'N/A'}")
            print(f"Categoría UdM solicitada: {uom.category_id.display_name if uom.category_id else 'N/A'}")

            if (
                base_uom.category_id
                and uom.category_id
                and base_uom.category_id == uom.category_id
            ):
                print("Las categorías de UdM coinciden. Buscando línea en UdM base...")

                base_line = Line.search(
                    [
                        ("price_list_id", "=", self.id),
                        ("product_id", "=", product.id),
                        ("uom_id", "=", base_uom.id),
                    ],
                    limit=1,
                )

                print(f"Línea base encontrada: {base_line.id if base_line else 'No'}")

                if base_line:
                    converted_price = base_uom._compute_price(base_line.price_unit, uom)
                    print(f"Precio base encontrado: {base_line.price_unit}")
                    print(f"Precio convertido a UdM solicitada: {converted_price}")
                    print("========== FIN _get_price (convertido) ==========")
                    return converted_price
                else:
                    print("No se encontró línea base para convertir.")
            else:
                print("Las categorías de UdM no coinciden o alguna categoría está vacía.")
        else:
            print("Alguna de las UdM no tiene campo category_id en este build.")

        print("No se pudo determinar precio.")
        print("========== FIN _get_price (None) ==========")
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
        print("========== INICIO _check_uom_same_category_when_available ==========")

        for rec in self:
            print("----------------------------------------")
            print(f"Registro línea ID: {rec.id if rec.id else 'Nuevo'}")
            print(f"Producto: {rec.product_id.display_name if rec.product_id else 'N/A'}")
            print(f"UdM seleccionada: {rec.uom_id.display_name if rec.uom_id else 'N/A'}")

            if not rec.product_id or not rec.uom_id:
                print("Falta producto o UdM. Se omite validación.")
                continue

            puom = rec.product_id.uom_id
            print(f"UdM del producto: {puom.display_name if puom else 'N/A'}")

            if not puom:
                print("El producto no tiene UdM definida. Se omite validación.")
                continue

            has_category_rec = "category_id" in rec.uom_id._fields
            has_category_puom = "category_id" in puom._fields

            print(f"¿UdM seleccionada tiene category_id?: {has_category_rec}")
            print(f"¿UdM del producto tiene category_id?: {has_category_puom}")

            if has_category_rec and has_category_puom:
                print(f"Categoría UdM seleccionada: {rec.uom_id.category_id.display_name if rec.uom_id.category_id else 'N/A'}")
                print(f"Categoría UdM producto: {puom.category_id.display_name if puom.category_id else 'N/A'}")

                if (
                    rec.uom_id.category_id
                    and puom.category_id
                    and rec.uom_id.category_id != puom.category_id
                ):
                    print("ERROR: La categoría de la UdM no coincide con la del producto.")
                    print("========== FIN _check_uom_same_category_when_available (ValidationError) ==========")
                    raise ValidationError(
                        _("La Unidad de Medida debe pertenecer a la misma categoría que la UdM del producto.")
                    )
                else:
                    print("Validación correcta: categorías compatibles.")
            else:
                print("Alguna de las UdM no tiene category_id en este build. No se valida categoría.")

        print("========== FIN _check_uom_same_category_when_available ==========")
