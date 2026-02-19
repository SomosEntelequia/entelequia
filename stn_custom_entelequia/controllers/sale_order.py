# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID
from odoo.http import request, Response
import json
import logging

_logger = logging.getLogger(__name__)

# ============================================
#   CONFIGURACIÓN CORS
# ============================================
ALLOWED_ORIGIN = "*"

def make_cors_headers():
    return [
        ('Access-Control-Allow-Origin', ALLOWED_ORIGIN),
        ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, PATCH'),
        ('Access-Control-Allow-Headers', 'Content-Type, apiKey, secretKey'),
        ('Access-Control-Allow-Credentials', 'true'),
        ('Access-Control-Max-Age', '3600'),
    ]

# ============================================
#   CONTROLADOR PRINCIPAL
# ============================================
class ApiController(http.Controller):

    def _create_response(self, data, status_code):
        headers = make_cors_headers()
        headers.append(('Content-Type', 'application/json'))
        return Response(json.dumps(data), status=status_code, headers=headers)

    def _validate_auth(self):
        """Valida las llaves de API."""
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        if not api_key or not secret_key:
            return None, "Missing required headers (apiKey and/or secretKey)", 400

        api_record = request.env['stings.key'].sudo().with_user(SUPERUSER_ID).search([
            ('key', '=', api_key),
            ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            return None, "Invalid API Key or Secret Key", 401

        return api_record, None, 200
    
    @http.route('/api/update_sale_order', type='http', auth='none', methods=['PATCH', 'OPTIONS'], csrf=False)
    def update_sale_order_status(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        api_record, error_msg, status = self._validate_auth()
        if error_msg:
            return self._create_response({"status": "error", "message": error_msg}, status)

        try:
            data = json.loads(request.httprequest.data)
            order_data = data.get('order_data', {})
        except Exception:
            return self._create_response({"status": "error", "message": "Invalid JSON format"}, 400)

        sap_doc_num = order_data.get('u_sap_doc_num')
        if not sap_doc_num:
            return self._create_response({'status': 'error', 'message': 'Missing: u_sap_doc_num'}, 400)

        try:
            sale_order = request.env['sale.order'].sudo().with_user(SUPERUSER_ID).search([
                ('u_sap_doc_num', '=', str(sap_doc_num))
            ], limit=1)

            if not sale_order:
                return self._create_response({'status': 'error', 'message': f'Order {sap_doc_num} not found'}, 404)

            update_vals = {}
            
            # --- 1. LÓGICA DE ACUMULACIÓN PARA MÚLTIPLES FOLIOS ---
            # Si SAP manda un folio, lo agregamos a la lista existente sin borrar los anteriores
            folios_mapping = {
                'invoice_num': 'u_sap_invoice_num',
                'delivery_num': 'u_sap_delivery_num',
                'credit_note_num': 'u_sap_credit_note_num',
                'return_num':'u_sap_folio_devolucion'
            }
            # --- LÓGICA DE ACUMULACIÓN CON FORMATO BULLETS ---
            for json_key, odoo_key in folios_mapping.items():
                if json_key in order_data and order_data[json_key]:
                    nuevos_folios = [n.strip() for n in str(order_data[json_key]).split(',') if n.strip()]
                    
                    # Extraer folios existentes quitando las etiquetas HTML para comparar
                    import re
                    content_actual = getattr(sale_order, odoo_key) or ""
                    actuales = re.findall(r'<li>(.*?)</li>', content_actual)
                    
                    for folio in nuevos_folios:
                        if folio not in actuales:
                            actuales.append(folio)
                    
                    # Construir el HTML final
                    if actuales:
                        html_list = '<ul style="margin: 0; padding-left: 15px;">'
                        for a in actuales:
                            html_list += f'<li>{a}</li>'
                        html_list += '</ul>'
                        update_vals[odoo_key] = html_list

            # --- 2. MAPEADO DE CAMPOS ESTÁNDAR ---
            standard_mapping = {
                'estado': 'u_estado',
                'cond_entrega': 'u_cond_entrega',
                'form_envio': 'u_form_envio',
                'tipo_pedido': 'u_tipo_pedido',
                'tipo_envio': 'u_tipo_envio',
                'tipo_devolucion': 'u_tipo_devolucion',
                'devolucion': 'u_devolucion',
                'cancelacion': 'u_cancelacion',
                'zona': 'u_zona',
                'referencia_pago': 'u_referencia_pago',
                'numRef': 'u_numRef',                
            }

            for json_key, odoo_key in standard_mapping.items():
                if json_key in order_data:
                    update_vals[odoo_key] = str(order_data[json_key])

            # Aplicar cambios en base de datos
            if update_vals:
                sale_order.write(update_vals)

            # --- 3. LÓGICA DE FLUJO NATIVO DE ODOO ---
            sap_status = str(order_data.get('estado', ''))

            if sap_status == '0' and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
                _logger.info(">>> SAP Sync: Orden %s CONFIRMADA", sap_doc_num)

            elif sap_status == '3' and sale_order.state != 'cancel':
                sale_order.action_cancel()
                _logger.info(">>> SAP Sync: Orden %s CANCELADA", sap_doc_num)

            return self._create_response({
                'status': 'success',
                'order_id': sale_order.id,
                'odoo_state': sale_order.state,
                'updated_fields': list(update_vals.keys())
            }, 200)

        except Exception as e:
            _logger.error(">>> SAP Sales Sync Error: %s", str(e))
            return self._create_response({"status": "error", "message": str(e)}, 500)