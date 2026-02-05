# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json
from odoo.exceptions import AccessDenied
import logging
_logger = logging.getLogger(__name__)

# ============================================
#   CONFIGURACIÓN CORS
# ============================================
ALLOWED_ORIGIN = "*"

def make_cors_headers():
    return [
        ('Access-Control-Allow-Origin', ALLOWED_ORIGIN),
        ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS'),
        ('Access-Control-Allow-Headers', 'Content-Type, apiKey, secretKey'),
        ('Access-Control-Allow-Credentials', 'true'),
        ('Access-Control-Max-Age', '3600'),
    ]

# ============================================
#   CONTROLADOR PRINCIPAL
# ============================================
class ApiController(http.Controller):
    
    def _create_response(self, data, status_code):
        # Asegúrate de tener definida la función make_cors_headers o cámbialo por headers fijos
        headers = [('Content-Type', 'application/json')]
        return Response(json.dumps(data), status=status_code, headers=headers)

    @http.route('/api/price_list', type='http', auth='public', methods=['POST'], csrf=False)
    def sync_price_list(self, **kwargs):
        # 1. Autenticación por API Key
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')
        
        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key), ('secret_key', '=', secret_key)
        ], limit=1)
        if not api_record:
            return self._create_response({"status": "error", "message": "Unauthorized"}, 401)

        # 2. Leer JSON
        try:
            data = json.loads(request.httprequest.data)
            list_data = data.get('price_list')
            if not list_data or not list_data.get('id_secundario_sap'):
                return self._create_response({"status": "error", "message": "Missing price_list or id_secundario_sap"}, 400)
        except Exception:
            return self._create_response({"status": "error", "message": "Invalid JSON format"}, 400)

        sap_list_id = str(list_data.get('id_secundario_sap'))
        
        # 3. Buscar o Crear la Cabecera
        price_list = request.env['sap.price.list'].sudo().search([
            ('id_secundario_sap', '=', sap_list_id)
        ], limit=1)

        list_vals = {
            'name': list_data.get('name'),
            'active': list_data.get('active', True),
            'id_secundario_sap': sap_list_id,
        }

        if price_list:
            price_list.write(list_vals)
        else:
            price_list = request.env['sap.price.list'].sudo().create(list_vals)

        # 4. Procesar Líneas
        lines_data = list_data.get('lines', [])
        results = {"created": 0, "updated": 0, "errors": []}

        for l_data in lines_data:
            try:
                line_sap_id = l_data.get('id_secundario_sap_line')
                product_sap_id = l_data.get('product_id_sap')
                # Recibimos el código o nombre, ej: "X4G"
                uom_input = l_data.get('uom_id') 
                price = float(l_data.get('price_unit', 0))

                if not line_sap_id:
                    results["errors"].append("Missing id_secundario_sap_line")
                    continue

                # --- LÓGICA DE BÚSQUEDA DE UOM ---
                odoo_uom = False
                if uom_input:
                    # Buscamos por nombre o por el código UNSPSC si lo usas
                    odoo_uom = request.env['uom.uom'].sudo().search([
                        '|', 
                        ('name', '=', str(uom_input)),
                        ('unspsc_code_id.code', '=', str(uom_input)) # Común en localización MX
                    ], limit=1)
                
                if not odoo_uom:
                    results["errors"].append(f"UoM '{uom_input}' not found for line {line_sap_id}")
                    continue
                # --------------------------------

                # Buscar el producto
                product = request.env['product.product'].sudo().search([
                    ('id_secundario_sap', '=', product_sap_id)
                ], limit=1)

                if not product:
                    results["errors"].append(f"Product SAP ID {product_sap_id} not found")
                    continue

                # Buscar línea existente
                line = request.env['sap.price.list.line'].sudo().search([
                    ('id_secundario_sap_line', '=', line_sap_id)
                ], limit=1)

                line_vals = {
                    'price_list_id': price_list.id,
                    'product_id': product.id,
                    'uom_id': odoo_uom.id, # Usamos el ID de Odoo encontrado
                    'price_unit': price,
                    'id_secundario_sap_line': line_sap_id
                }

                if line:
                    line.write(line_vals)
                    results["updated"] += 1
                else:
                    request.env['sap.price.list.line'].sudo().create(line_vals)
                    results["created"] += 1

            except Exception as e:
                results["errors"].append(str(e))

        return self._create_response({
            "status": "success",
            "price_list_id": price_list.id,
            "summary": results
        }, 200)