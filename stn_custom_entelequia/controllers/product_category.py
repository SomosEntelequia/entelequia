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
    
    @http.route('/api/create_category', type='http', auth='public', methods=['POST'], csrf=False)
    def create_category(self, **kwargs):
        # 1. Autenticación
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
            cat_data = data.get('category_data', {})
        except Exception:
            return self._create_response({"status": "error", "message": "Invalid JSON"}, 400)

        id_sap = cat_data.get("id_secundario_sap")
        if not id_sap:
            return self._create_response({"status": "error", "message": "Missing id_secundario_sap"}, 400)

        # 3. Lógica de Categoría Padre (Parent ID)
        parent_id = False
        sap_parent_id = cat_data.get("parent_id_sap")
        if sap_parent_id:
            parent_cat = request.env['product.category'].sudo().search([
                ('id_secundario_sap', '=', str(sap_parent_id))
            ], limit=1)
            if parent_cat:
                parent_id = parent_cat.id
            else:
                # Opcional: Error si el padre no existe aún
                return self._create_response({
                    "status": "error", 
                    "message": f"Parent category SAP ID '{sap_parent_id}' not found. Sync parents first."
                }, 400)

        # 4. Preparar valores
        vals = {
            "name": cat_data.get("name"),
            "id_secundario_sap": id_sap,
            "parent_id": parent_id or cat_data.get("parent_id", False) # Prioriza SAP, si no usa ID de Odoo
        }

        # 5. Operación en BD (Upsert)
        try:
            category = request.env['product.category'].sudo().search([
                ('id_secundario_sap', '=', id_sap)
            ], limit=1)

            if category:
                category.write(vals)
                action = "updated"
                res_id = category.id
            else:
                new_cat = request.env['product.category'].sudo().create(vals)
                action = "created"
                res_id = new_cat.id

            return self._create_response({
                "status": "success", 
                "action": action, 
                "category_id": res_id
            }, 200)

        except Exception as e:
            _logger.exception("Error en API create_category")
            return self._create_response({"status": "error", "message": f"BD Error: {str(e)}"}, 500)