from markupsafe import Markup, escape

from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # -----------------------------
    # Revalidación al confirmar
    # -----------------------------
    def _sap_check_prices_before_confirm(self):
        """Revalúa línea por línea que Lista SAP, producto, UdM y precio sigan vigentes."""
        errors = []
        for order in self:
            if order.state not in ("draft", "sent"):
                continue
            issues = order.order_line._sap_collect_price_issues()
            if issues:
                errors.append("%s:\n%s" % (order.name, "\n".join(issues)))

        if errors:
            raise UserError(
                _(
                    "No se puede confirmar la orden: hubo cambios en las Listas de precio SAP "
                    "desde que se capturó y las siguientes líneas ya no son vigentes.\n\n"
                    "%(errors)s\n\n"
                    "Si solo cambió el precio, usa el botón «Actualizar precios SAP». "
                    "Si la lista, el producto o la UdM se archivaron, cambia la línea por una vigente.",
                    errors="\n\n".join(errors),
                )
            )

    def action_confirm(self):
        if not self.env.context.get("skip_sap_price_check"):
            self._sap_check_prices_before_confirm()
        return super().action_confirm()

    # -----------------------------
    # Botón: actualizar precios SAP
    # -----------------------------
    def action_sap_refresh_prices(self):
        """Vuelve a traer el precio vigente de la Lista SAP en cada línea y deja nota en el chatter."""
        for order in self:
            if order.state not in ("draft", "sent"):
                raise UserError(_("Solo se pueden actualizar precios SAP en cotizaciones."))

            lines = order.order_line.filtered(
                lambda l: l.sap_price_list_id and l.product_id and not l.display_type
            )
            before = {line.id: line.price_unit for line in lines}
            lines._sap_apply_price(write_mode=True)

            changes = [
                Markup("<li>%s: %s → %s</li>")
                % (line.product_id.display_name, before[line.id], line.price_unit)
                for line in lines
                if line.price_unit != before[line.id]
            ]
            if changes:
                order.message_post(
                    body=Markup("<p>%s</p><ul>%s</ul>")
                    % (escape(_("Precios actualizados desde Listas de precio SAP:")), Markup("").join(changes)),
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
        return True
