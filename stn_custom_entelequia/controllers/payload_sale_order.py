# -*- coding: utf-8 -*-
from odoo import models, fields, api
from markupsafe import Markup, escape
import json
import logging
import requests
import pytz
from datetime import datetime

_logger = logging.getLogger(__name__)

MEXICO_TZ = pytz.timezone('America/Mexico_City')

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Nuevos campos para direcciones SAP
    partner_shipping_id_sap = fields.Many2one(
        'res.partner',
        string='Dirección de Envío',
        domain="[('parent_id', '=', partner_id), ('type', '=', 'delivery'), ('id_secondary', '!=', False)]",
        help="Dirección de envío que se enviará a SAP (ShipToCode). Solo muestra direcciones que ya tienen id_secondary."
    )
    partner_invoice_id_sap = fields.Many2one(
        'res.partner',
        string='Dirección de Facturación',
        domain="[('parent_id', '=', partner_id), ('type', '=', 'invoice'), ('id_secondary', '!=', False)]",
        help="Dirección de facturación que se enviará a SAP (PayToCode). Solo muestra direcciones que ya tienen id_secondary."
    )

    def _convert_to_mexico_date(self, dt_utc, field_name="fecha"):
        """
        Convierte un datetime UTC a fecha en zona horaria México City.
        Loguea ambas versiones para trazabilidad.
        """
        if not dt_utc:
            return None

        # Si no tiene tzinfo, asumimos que es UTC (así lo guarda Odoo)
        if dt_utc.tzinfo is None:
            dt_utc_aware = pytz.utc.localize(dt_utc)
        else:
            dt_utc_aware = dt_utc

        dt_mexico = dt_utc_aware.astimezone(MEXICO_TZ)

        _logger.info(f"🕐 Conversión de zona horaria para [{field_name}]:")
        _logger.info(f"   UTC         : {dt_utc_aware.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        _logger.info(f"   México (CDT): {dt_mexico.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        _logger.info(f"   Fecha final : {dt_mexico.strftime('%Y-%m-%d')} ✅")

        return dt_mexico

    def action_confirm(self):
        """ Envía la orden a SAP al confirmar. No toca contactos. """
        _logger.info("=" * 80)
        _logger.info(f"🚀 INICIANDO CONFIRMACIÓN DE ORDEN: {self.name}")
        _logger.info("=" * 80)
        
        self.write({'u_estado': '0'})
        res = super(SaleOrder, self).action_confirm()

        url_order = "http://b1.ativy.mx:22258/Sap/orders"

        for order in self:
            _logger.info(f"📦 Procesando orden: {order.name}")
            _logger.info(f"   - Cliente: {order.partner_id.name}")
            _logger.info(f"   - u_is_sap_client: {order.partner_id.u_is_sap_client}")
            _logger.info(f"   - id_secondary: {order.partner_id.id_secondary}")
            _logger.info(f"   - u_sap_id: {order.u_sap_id}")
            
            if not order.partner_id.u_is_sap_client:
                _logger.warning(f"⚠️ Orden {order.name}: El cliente no ha sido sincronizado con el botón SAP.")
                _logger.warning(f"   Necesitas sincronizar primero al cliente {order.partner_id.name}")
                order._post_sap_order_chatter(
                    "error",
                    f"El cliente {order.partner_id.display_name} no está sincronizado con SAP.",
                )
                continue

            if not order.u_sap_id:
                _logger.info(f"✅ Orden {order.name} NO tiene u_sap_id, procediendo a enviar a SAP...")
                
                try:
                    payload_order = order._build_sap_order_payload()
                    _logger.info(f"📤 PAYLOAD GENERADO PARA ORDEN {order.name}:")
                    _logger.info(json.dumps(payload_order, indent=2, ensure_ascii=False))
                    
                    sap_response = order._send_to_sap(payload_order, url_order, "ORDEN")
                    
                    if sap_response and isinstance(sap_response, dict):
                        _logger.info(f"✅ RESPUESTA SAP EXITOSA: {sap_response}")
                        order.write({
                            'x_payload_printed': True,
                            'u_sap_id': sap_response.get('docEntry'),
                            'u_sap_doc_num': str(sap_response.get('docNum')),
                            'u_estado': '0'
                        })
                        order._post_sap_order_chatter(
                            "success",
                            "Orden enviada a SAP correctamente.",
                            payload_order,
                            sap_response,
                        )
                    else:
                        _logger.error(f"❌ Error en respuesta SAP para orden {order.name}")
                        order._post_sap_order_chatter(
                            "error",
                            "SAP no confirmó la creación de la orden.",
                            payload_order,
                            sap_response,
                        )
                        
                except Exception as e:
                    _logger.error(f"❌ EXCEPCIÓN al procesar orden {order.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())
                    order._post_sap_order_chatter(
                        "error",
                        f"Excepción al enviar la orden a SAP: {str(e)}",
                    )
            else:
                _logger.info(f"⏭️ Orden {order.name} ya tiene u_sap_id: {order.u_sap_id}, omitiendo envío")
                order._post_sap_order_chatter(
                    "success",
                    f"La orden ya estaba sincronizada con SAP. DocEntry: {order.u_sap_id}.",
                )
        
        _logger.info("=" * 80)
        _logger.info(f"✅ CONFIRMACIÓN COMPLETADA")
        _logger.info("=" * 80)
        return res

    def action_cancel(self):
        """ Informa cancelación a SAP via PATCH """
        _logger.info(f"🚫 CANCELANDO ORDEN: {self.name}")
        
        res = super(SaleOrder, self).action_cancel()
        for order in self:
            if order.u_sap_doc_num:
                _logger.info(f"📤 Enviando cancelación a SAP para orden {order.name}")
                order.write({'u_estado': '3'})
                url_patch = f"http://b1.ativy.mx:22258/Sap/orders/{order.u_sap_doc_num}"
                payload_update = {
                    "order": {
                        "estado": "3",
                        "cancelacion": order.u_cancelacion or "0",
                        "docnum_odoo": order.name,
                        "Comments": (order.u_sap_notes or "Cancelado desde Odoo")[:250]
                    }
                }
                _logger.info(f"PAYLOAD CANCELACIÓN: {json.dumps(payload_update, indent=2, ensure_ascii=False)}")
                sap_response = order._send_to_sap(payload_update, url_patch, "CANCELACIÓN", method='PATCH')
                if sap_response:
                    order._post_sap_order_chatter(
                        "success",
                        "Cancelación enviada a SAP correctamente.",
                        payload_update,
                        sap_response,
                    )
                else:
                    order._post_sap_order_chatter(
                        "error",
                        "SAP no confirmó la cancelación de la orden.",
                        payload_update,
                        sap_response,
                    )
            else:
                _logger.warning(f"⚠️ Orden {order.name} no tiene u_sap_doc_num, no se puede cancelar en SAP")
                order._post_sap_order_chatter(
                    "error",
                    "No se puede cancelar en SAP porque la orden no tiene número de folio SAP.",
                )
        return res

    def _send_to_sap(self, payload, url, tipo_doc, method='POST'):
        headers = {"X-API-KEY": "2d33fa57-0f91", "Content-Type": "application/json"}
        try:
            _logger.info(f"🌐 Enviando {tipo_doc} a SAP: {url}")
            _logger.info(f"   Método: {method}")
            
            if method == 'PATCH':
                response = requests.patch(url, json=payload, headers=headers, timeout=60)
            else:
                response = requests.post(url, json=payload, headers=headers, timeout=60)
            
            _logger.info(f"📥 RESPONSE SAP [{response.status_code}]: {response.text}")
            
            if response.status_code in [200, 201, 204]:
                return response.json() if response.text else True
            else:
                _logger.error(f"❌ Error SAP {tipo_doc}: Status {response.status_code}")
                self._post_sap_order_chatter(
                    "error",
                    f"Error SAP {tipo_doc}. HTTP {response.status_code}.",
                    payload,
                    response.text,
                )
                return False
        except Exception as e:
            _logger.error(f"❌ ERROR SAP {tipo_doc}: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            self._post_sap_order_chatter(
                "error",
                f"Error de conexión SAP {tipo_doc}: {str(e)}",
                payload,
            )
            return False

    def _post_sap_order_chatter(self, status, message, payload=None, response=None):
        """Publica la trazabilidad SAP en el chatter de la orden."""
        for order in self:
            title = "✅ SAP Orden de Venta" if status == "success" else "❌ SAP Orden de Venta"
            body_parts = [
                Markup("<b>%s</b><p>%s</p>") % (escape(title), escape(message))
            ]
            if payload is not None:
                body_parts.append(
                    Markup("<b>Payload enviado:</b><pre>%s</pre>") %
                    escape(json.dumps(payload, indent=2, ensure_ascii=False))
                )
            if response is not None:
                response_text = (
                    json.dumps(response, indent=2, ensure_ascii=False)
                    if isinstance(response, (dict, list))
                    else str(response)
                )
                body_parts.append(
                    Markup("<b>Respuesta SAP:</b><pre>%s</pre>") %
                    escape(response_text)
                )
            order.message_post(body=Markup("").join(body_parts))

    def _build_sap_order_payload(self):
        self.ensure_one()
        _logger.info(f"🔨 Construyendo payload para orden {self.name}")

        # =============================
        # 🕐 CONVERSIÓN DE FECHAS A HORA MÉXICO
        # =============================
        _logger.info(f"📅 --- INICIO CONVERSIÓN DE FECHAS ---")
        _logger.info(f"   date_order raw (UTC desde Odoo) : {self.date_order}")
        _logger.info(f"   commitment_date raw (UTC desde Odoo): {self.commitment_date}")

        dt_order_mexico = self._convert_to_mexico_date(self.date_order, "OrderDate / date_order")
        order_date_str = dt_order_mexico.strftime('%Y-%m-%d') if dt_order_mexico else ""

        if self.commitment_date:
            dt_promised_mexico = self._convert_to_mexico_date(self.commitment_date, "PromisedDate / commitment_date")
        else:
            dt_promised_mexico = dt_order_mexico
            _logger.info(f"   PromisedDate: sin commitment_date, usando date_order en hora México")

        promised_date_str = dt_promised_mexico.strftime('%Y-%m-%d') if dt_promised_mexico else order_date_str

        _logger.info(f"📅 --- RESULTADO FINAL FECHAS ---")
        _logger.info(f"   OrderDate   → {order_date_str}")
        _logger.info(f"   PromisedDate → {promised_date_str}")
        _logger.info(f"📅 --- FIN CONVERSIÓN DE FECHAS ---")

        # =============================
        # Obtener el uso SAT del cliente
        # =============================
        main_usage = ""
        if (
            self.partner_id
            and hasattr(self.partner_id, 'l10n_mx_edi_usage')
            and self.partner_id.l10n_mx_edi_usage
        ):
            main_usage = self.partner_id.l10n_mx_edi_usage
            _logger.info(f"📋 Uso SAT del cliente (main_usage): {main_usage}")

        # =============================
        # Construcción de líneas
        # =============================
        lines = []
        for line in self.order_line:
            if not line.product_id or line.display_type:
                _logger.info(f"   ⏭️ Omitiendo línea: {line.name}")
                continue

            sap_pl_id = (
                line.sap_price_list_id.id_secundario_sap
                if hasattr(line, 'sap_price_list_id') and line.sap_price_list_id
                else ""
            )

            sat_code = (
                line.product_uom_id.unspsc_code_id.code
                if line.product_uom_id.unspsc_code_id
                else ""
            )

            if line.line_warehouse_id:
                warehouse_code = line.line_warehouse_id.name
            elif self.warehouse_id:
                warehouse_code = self.warehouse_id.name
            else:
                warehouse_code = "ALM-GRAL"

            line_data = {
                "ItemCode": line.product_id.id_secundario_sap or "",
                "Quantity": float(line.product_uom_qty),
                "UomEntry": sat_code,
                "Price": round(line.price_unit, 2),
                "discountPercent": round(line.discount, 2) if line.discount else 0.0,
                "TaxCode": self._get_sap_tax_code(
                    line.tax_ids[0] if line.tax_ids else False
                ),
                "Warehouse": warehouse_code,
                "CustomFields": {
                    "sap_price_list_id": sap_pl_id
                }
            }

            _logger.info(f"   ✅ Línea agregada: {line.product_id.name} x {line.product_uom_qty}")
            lines.append(line_data)

        # =============================
        # Direcciones SAP
        # =============================
        ship_to_code = ""
        pay_to_code = ""

        if self.partner_shipping_id_sap and self.partner_shipping_id_sap.id_secondary:
            ship_to_code = self.partner_shipping_id_sap.name
            _logger.info(f"📦 ShipTo (Address2): {ship_to_code}")

        if self.partner_invoice_id_sap and self.partner_invoice_id_sap.id_secondary:
            pay_to_code = self.partner_invoice_id_sap.name
            _logger.info(f"💰 PayTo (Address): {pay_to_code}")

        # =============================
        # Vendedor
        # =============================
        sales_person_code = self._get_sales_person_code()

        # =============================
        # Payload final
        # =============================
        order_data = {
            "OdooId": self.name,
            "CustomerCode": self.partner_id.id_secondary or "",
            "OrderDate": order_date_str,
            "PromisedDate": promised_date_str,
            "PaymentTermCode": self.payment_term_id.sap_payment_term_code or '',
            "Currency": self.currency_id.name,
            "Comments": (self.u_sap_notes or self.note or "")[:250],
            "salesPersonCode": sales_person_code,
            "lines": lines,
            "numRef": self.u_numRef or "",
            "estado": self.u_estado,
            "cond_entrega": self.u_cond_entrega,
            "form_envio": self.u_form_envio,
            "tipo_pedido": self.u_tipo_pedido,
            "tipo_envio": self.u_tipo_envio,
            "tipo_devolucion": self.u_tipo_devolucion,
            "devolucion": self.u_devolucion,
            "cancelacion": self.u_cancelacion,
            "zona": self.u_zona or "",
            "referencia_pago": self.u_referencia_pago or "",
            "docnum_odoo": self.name,
            "Address2": ship_to_code,
            "Address": pay_to_code,
        }

        if main_usage:
            order_data["main_usage"] = main_usage

        # Filtro Dinámico — elimina False y None
        final_order = {k: v for k, v in order_data.items() if v is not False and v is not None}

        _logger.info(f"✅ Payload construido con {len(lines)} líneas")
        return {"order": final_order}

    def _get_sales_person_code(self):
        self.ensure_one()
        
        if self.user_id and hasattr(self.user_id, 'sap_sales_person_code') and self.user_id.sap_sales_person_code:
            return self.user_id.sap_sales_person_code
        
        if self.team_id and hasattr(self.team_id, 'sap_sales_person_code') and self.team_id.sap_sales_person_code:
            return self.team_id.sap_sales_person_code
        
        _logger.warning(f"⚠️ No se encontró código de vendedor para orden {self.name}, usando código por defecto: 2")
        return 2

    def _get_sap_tax_code(self, odoo_tax):
        if not odoo_tax: return "IVAP16"
        name = odoo_tax.name.upper()
        if "EXENTO" in name: return "IVAPE"
        return {16.0: "IVAP16", 8.0: "IVAP08", 0.0: "IVAP00"}.get(odoo_tax.amount, "IVAP16")


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén',
        help='Almacén específico para esta línea de orden. Si no se especifica, se usa el almacén de la orden.'
    )
