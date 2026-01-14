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

    @http.route('/api/create_product', type='http', auth='public', methods=['POST'], csrf=False)
    def create_product(self, **kwargs):
        # -----------------------------
        # 1. Autenticación por API Key
        # -----------------------------
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        if not api_key or not secret_key:
            return self._create_response(
                {"status": "error", "message": "Missing required headers (apiKey, secretKey)"}, 400)

        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key),
            ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            return self._create_response(
                {"status": "error", "message": "Invalid API Key or Secret Key"}, 401)

        # -----------------------------
        # 2. Leer y parsear JSON
        # -----------------------------
        try:
            data = json.loads(request.httprequest.data)
        except Exception:
            return self._create_response(
                {"status": "error", "message": "Invalid JSON payload format"}, 400)

        product_data = data.get('product_data')
        if not product_data:
            return self._create_response(
                {"status": "error", "message": "Missing product_data"}, 400)

        # -----------------------------
        # 3. Validaciones de campos obligatorios
        # -----------------------------
        id_sap = product_data.get("id_secundario_sap")
        if not id_sap:
            return self._create_response(
                {"status": "error", "message": "Missing required field: id_secundario_sap"}, 400)

        # -----------------------------
        # 4. Lógica de Código UNSPSC (SAT México)
        # -----------------------------
        unspsc_id = False
        sat_id = product_data.get("unspsc_code_sat_id")

        if sat_id:
            sat_code = str(sat_id).strip().zfill(8)
            unspsc = request.env['product.unspsc.code'].sudo().search([
                ('code', '=', sat_code)
            ], limit=1)
            if unspsc:
                unspsc_id = unspsc.id

        # -----------------------------
        # 5. Lógica de Grupo de UoM SAP
        # -----------------------------
        uom_list_ids = []
        grupo_sap = product_data.get("grupo_de_unidad_de_medida_sap")
        
        if grupo_sap:
            # Buscamos todas las unidades que pertenecen a este grupo
            uoms = request.env['uom.uom'].sudo().search([
                ('grupo_de_unidad_de_medida_sap', '=', grupo_sap)
            ])
            if uoms:
                # Preparamos la lista de IDs para el campo many2many (uoms_ids)
                uom_list_ids = [(6, 0, uoms.ids)]

        # -----------------------------
        # 6. Crear o Actualizar Producto
        # -----------------------------
        try:
            company = request.env['res.company'].sudo().search([], limit=1)            
            product_type = product_data.get("type", "product")
            
            # Buscamos si el producto ya existe por su ID SAP
            existing_product = request.env['product.template'].sudo().search([
                ('id_secundario_sap', '=', id_sap)
            ], limit=1)

            vals = {
                "name": product_data.get("name"),
                "sale_ok": product_data.get("sale_ok", True),
                "purchase_ok": product_data.get("purchase_ok", True),
                "type": product_type,
                "invoice_policy": product_data.get("invoice_policy", "order"),
                "list_price": product_data.get("list_price", 0.0),
                "standard_price": product_data.get("standard_price", 0.0),
                "uom_id": product_data.get("uom_id"),
                "categ_id": product_data.get("categ_id"),
                "taxes_id": [(6, 0, product_data.get("taxes_id", []))],
                "default_code": product_data.get("default_code"),
                "unspsc_code_id": unspsc_id,
                "id_secundario_sap": id_sap,               
                "is_storable": product_data.get("is_storable", True),
                "grupo_de_unidad_de_medida_sap": grupo_sap,
                "uom_ids": uom_list_ids, # Vinculamos las unidades encontradas
            }

            if existing_product:
                # UPDATE
                existing_product.with_company(company).write(vals)
                template = existing_product
                action = "updated"
            else:
                # CREATE
                template = request.env['product.template'].sudo().with_company(company).create(vals)
                action = "created"

        except Exception as e:
            _logger.exception("API PRODUCT - Error en operación de BD")
            return self._create_response(
                {"status": "error", "message": f"Operation failed: {str(e)}"}, 500)

        # -----------------------------
        # 7. Respuesta Final
        # -----------------------------
        return self._create_response({
            "status": "success",
            "action": action,
            "product_template_id": template.id            
        }, 200 if action == "updated" else 201)
        

    @http.route('/api/update_product', type='http', auth='public', methods=['PATCH'], csrf=False)
    def update_product(self, **kwargs):

        # -----------------------------
        # 1. Autenticación por API KEY
        # -----------------------------
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        if not api_key or not secret_key:
            return self._create_response(
                {"status": "error", "message": "Missing required headers (apiKey, secretKey)"}, 400)

        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key),
            ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            return self._create_response(
                {"status": "error", "message": "Invalid API Key or Secret Key"}, 401)

        # -----------------------------
        # 2. Parseo del JSON
        # -----------------------------
        try:
            data = json.loads(request.httprequest.data)
        except:
            return self._create_response(
                {"status": "error", "message": "Invalid JSON payload format"}, 400)

        product_data = data.get('product_data')
        if not product_data:
            return self._create_response(
                {"status": "error", "message": "Missing product_data"}, 400)

        # -----------------------------
        # 3. Validar y normalizar id_secundario_sap
        # -----------------------------
        sap_id = product_data.get("id_secundario_sap")

        if sap_id in (None, "", False):
            return self._create_response(
                {"status": "error", "message": "Missing required field: id_secundario_sap"}, 400)

        #sap_id = str(sap_id_raw).strip()

        # 4. Buscar Producto por ID SAP
        # 4. Buscar Producto por ID SAP
        template = request.env["product.template"].sudo().search([
            ("id_secundario_sap", "=", sap_id)
        ], limit=1)

        if not template:
            return self._create_response({"status": "error", "message": "Product not found"}, 404)

        product_variant = template.product_variant_id
        company = request.env['res.company'].sudo().search([], limit=1)

        # ---------------------------------------------------------
        # 5. Lógica de Código UNSPSC (SAT México) para Actualización
        # ---------------------------------------------------------
        sat_id = product_data.get("unspsc_code_sat_id")
        if sat_id:
            sat_code = str(sat_id).strip().zfill(8)
            unspsc_record = request.env['product.unspsc.code'].sudo().search([
                ('code', '=', sat_code)
            ], limit=1)

            if unspsc_record:
                # Si lo encuentra, lo agregamos a los datos a actualizar
                product_data['unspsc_code_id'] = unspsc_record.id
                _logger.info("API UPDATE - UNSPSC Found: %s", sat_code)
            else:
                _logger.warning("API UPDATE - UNSPSC Code %s not found in Odoo", sat_code)

        # -----------------------------
        # 6. Validación de Inventario (Reglas de qty, uom, warehouse)
        # -----------------------------
        qty = product_data.get("qty")
        uom_id_incoming = product_data.get("uom_id")
        warehouse_code = product_data.get("warehouse_code")

        if qty is not None:
            if not warehouse_code or not uom_id_incoming:
                return self._create_response({
                    "status": "error", 
                    "message": "To update inventory, 'warehouse_code' and 'uom_id' are required."
                }, 400)
            
            if template.uom_id.id != int(uom_id_incoming):
                return self._create_response({
                    "status": "error", 
                    "message": f"UoM mismatch. Expected {template.uom_id.id}, received {uom_id_incoming}."
                }, 400)

        # -----------------------------
        # 7. Actualizar campos maestros
        # -----------------------------
        update_fields = {}
        # Nota: 'unspsc_code_id' es el campo real en Odoo, 'unspsc_code_sat_id' es el que recibimos por JSON
        allowed_updates = [
            "name", "sale_ok", "purchase_ok", "list_price", "standard_price", 
            "categ_id", "default_code", "type", "invoice_policy", "uom_id", 
            "taxes_id", "supplier_taxes_id", "unspsc_code_id"
        ]
        
        for field in allowed_updates:
            if field in product_data:
                if field in ["taxes_id", "supplier_taxes_id"] and isinstance(product_data[field], list):
                    update_fields[field] = [(6, 0, product_data[field])]
                else:
                    update_fields[field] = product_data[field]

        if update_fields:
            template.sudo().write(update_fields)

        # -----------------------------
        # 8. Ajuste de Inventario (Sobrescribir Stock)
        # -----------------------------
        if qty is not None:
            warehouse = request.env["stock.warehouse"].sudo().search([("code", "=", warehouse_code)], limit=1)
            if not warehouse:
                return self._create_response({"status": "error", "message": f"Warehouse {warehouse_code} not found"}, 404)
            stock_location = warehouse.lot_stock_id
            # Extraemos el valor del pronóstico del payload (asumiendo que viene en 'forecast_sap')
            pronosticado_sap = product_data.get("pronosticado_sap")
            try:
                # Lógica de sobreescritura con stock.quant
                quant = request.env["stock.quant"].sudo().search([
                    ('product_id', '=', product_variant.id),
                    ('location_id', '=', stock_location.id),
                    ('company_id', '=', company.id)
                ], limit=1)

                if quant:                 
                    quant.with_context(inventory_mode=True).write({
                        'inventory_quantity': float(qty),
                        'pronosticado_sap': float(pronosticado_sap)
                    })
                else:
                    quant = request.env["stock.quant"].sudo().with_context(inventory_mode=True).create({
                        'product_id': product_variant.id,
                        'location_id': stock_location.id,
                        'inventory_quantity': float(qty),
                        'company_id': company.id,
                        'pronosticado_sap': float(pronosticado_sap),
                    })                  
                quant.action_apply_inventory()
                _logger.info("API UPDATE - Inventory adjusted to %s", qty)
                
            except Exception as e:
                _logger.exception("API UPDATE - Inventory Error")
                
                return self._create_response({"status": "error", "message": f"Fields updated, but inventory failed: {str(e)}"}, 500)

        return self._create_response({
            "status": "success",            
            "updated_fields": list(update_fields.keys()),
            "inventory_updated": qty is not None
        }, 200)