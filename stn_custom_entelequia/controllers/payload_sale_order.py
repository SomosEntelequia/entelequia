# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_payload_printed = fields.Boolean(string="Sincronizado SAP", copy=False)

    def action_confirm(self):
        """ Extensión del botón confirmar para disparar la sincronización """
        res = super(SaleOrder, self).action_confirm()

        for order in self:
            # 1. Sincronización de Contacto (Solo si es la primera vez)
            partner = order.partner_id
            confirmed_orders_count = self.env['sale.order'].search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', ['sale', 'done']),
                ('id', '!=', order.id)
            ])

            if confirmed_orders_count == 0:
                _logger.info(">>> SAP: Primer contacto detectado: %s", partner.name)
                if hasattr(partner, '_build_sap_payload'):
                    payload_partner = partner._build_sap_payload()
                    self._send_to_sap(payload_partner, "http://b1.ativy.mx:22258/Sap/sync_bp", "CONTACTO")
            
            # 2. Envío de la Orden de Venta
            payload_order = order._build_sap_order_payload()
            success = self._send_to_sap(payload_order, "http://b1.ativy.mx:22258/Sap/orders", "ORDEN")
            
            if success:
                order.x_payload_printed = True

        return res

    def _get_sap_tax_code(self, odoo_tax):
        """ Mapeo de impuestos a códigos PascalCase de SAP """
        if not odoo_tax:
            return "IVAP16"
        name = odoo_tax.name.upper()
        amount = odoo_tax.amount
        if "EXENTO" in name: return "IVAPE"
        if amount == 16.0: return "IVAP16"
        if amount == 8.0: return "IVAP08"
        if amount == 0.0: return "IVAP00"
        return "IVAP16"

    def _get_sap_payment_term_code(self):
        """ Mapeo de plazos de pago por nombre exacto """
        self.ensure_one()
        if not self.payment_term_id:
            return -1
        name = self.payment_term_id.name
        mapping = {
            "Pago inmediato": -1,
            "15 días": 8,
            "21 días": 15,
            "30 días": 13,
            "45 días": 7,
            "Fin del siguiente mes": 13,
            "10 días después del fin del siguiente mes": 13,
            "30% ahora, el resto en 60 días": 18,
            "2/7 neto 30": 13,
            "90 días, en el día 10": 21
        }
        return mapping.get(name, 22)

    def _build_sap_order_payload(self):
        """ Construcción del JSON usando IDs secundarios de SAP """
        self.ensure_one()
        
        lines = []
        counter = 1
        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue
            
            tax_record = line.tax_ids[0] if line.tax_ids else False
            
            # Buscamos el ID secundario de la lista de precios (informativo)
            sap_pl_id = ""
            if hasattr(self, 'sap_price_list_id') and self.sap_price_list_id:
                sap_pl_id = self.sap_price_list_id.id_secundario_sap or ""
                
            lines.append({
                "LineId": str(counter),
                "ItemCode": line.product_id.id_secundario_sap or "", # ID SAP del producto
                "Quantity": int(line.product_uom_qty),
                "UomEntry": 2, 
                "Price": round(line.price_unit, 2),
                "TaxCode": self._get_sap_tax_code(tax_record),
                "Warehouse": self.warehouse_id.name or "ALM-GRAL",
                "CustomFields": {
                    "sap_price_list_id": sap_pl_id, # Lista de precios informativa
                    "width": 50,
                    "height": 100,
                    "unit_conversion": "cm_to_mm"
                } 
            })
            counter += 1

        payload = {
            "order": {
                "OdooId": self.name, 
                "CustomerCode": self.partner_id.id_secondary or "C00000549",
                "OrderDate": "2025-12-05", # Fecha estática por temas de tipo de cambio
                "PromisedDate": (self.commitment_date or self.date_order).strftime('%Y-%m-%d'),
                "PaymentTermCode": self._get_sap_payment_term_code(),
                "Currency": self.currency_id.name or "MXN",
                "Comments": (self.note or "Sincronizado desde Odoo")[:250],
                "Lines": lines
            }
        }
        return payload

    def _send_to_sap(self, payload, url, tipo_doc):
        """ Método genérico de envío con logging decorado """
        headers = {
            "X-API-KEY": "2d33fa57-0f91",
            "Content-Type": "application/json"
        }
        
        _logger.info("\n" + "="*50 + "\nENVIANDO %s A SAP\nURL: %s\nPAYLOAD:\n%s\n" + "="*50, tipo_doc, url, json.dumps(payload, indent=2))

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            if response.status_code in [200, 201]:
                _logger.info(">>> ÉXITO SAP [%s]: Código %s", tipo_doc, response.status_code)
                return True
            else:
                _logger.error(">>> ERROR SAP [%s]: %s - %s", tipo_doc, response.status_code, response.text)
                return False
        except Exception as e:
            _logger.error(">>> ERROR CRÍTICO SAP [%s]: %s", tipo_doc, str(e))
            return False