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
        # 1. Autenticación (ApiKey / SecretKey)
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')
        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key), ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            _logger.error("API API-KEY/SECRET-KEY INVALIDA")
            return self._create_response({"status": "error", "message": "Unauthorized"}, 401)

        # 2. Leer JSON
        try:
            data = json.loads(request.httprequest.data)
            product_data = data.get('product_data', {})
            _logger.info("JSON RECIBIDO DESDE SAP: %s", json.dumps(product_data, indent=2))
        except Exception as e:
            _logger.error("ERROR AL LEER JSON: %s", str(e))
            return self._create_response({"status": "error", "message": "Invalid JSON"}, 400)

        id_sap = product_data.get("id_secundario_sap")
        if not id_sap:
            _logger.error("FALTA id_secundario_sap EN EL JSON")
            return self._create_response({"status": "error", "message": "Missing id_secundario_sap"}, 400)

        # ---------------------------------------------------------
        # 3. CONVERSIÓN DE UOM (Búsqueda por alt_code Y grupo_sap)
        # ---------------------------------------------------------
        uom_id_real = False
        all_uom_ids_in_group = []
        sap_uom_code = product_data.get("uom") # Ej: "X4G"
        sap_uom_group = product_data.get("grupo_de_unidad_de_medida_sap") # Ej: "Caja 4 Paquetes 200pz"
        
        _logger.info("BUSCANDO UOM -> alt_code: %s | grupo_sap: %s", sap_uom_code, sap_uom_group)

        if sap_uom_code:
            uom_domain = [('alt_code', '=', str(sap_uom_code).strip())]
            if sap_uom_group:
                uom_domain.append(('grupo_de_unidad_de_medida_sap', '=', str(sap_uom_group).strip()))
            
            uom_record = request.env['uom.uom'].sudo().search(uom_domain, limit=1)
            
            if not uom_record:
                _logger.error("NO SE ENCONTRÓ UOM EN ODOO PARA: %s / %s", sap_uom_code, sap_uom_group)
                return self._create_response({
                    "status": "error", 
                    "message": f"No se encontró UoM con alt_code '{sap_uom_code}' y grupo '{sap_uom_group}'."
                }, 400)
            
            uom_id_real = uom_record.id
            _logger.info("UOM ENCONTRADA: %s (ID Odoo: %s)", uom_record.name, uom_id_real)

            # Buscar embalajes (uom_ids) que pertenezcan al mismo grupo SAP
            if sap_uom_group:
                related_uoms = request.env['uom.uom'].sudo().search([
                    ('grupo_de_unidad_de_medida_sap', '=', str(sap_uom_group).strip())
                ])
                all_uom_ids_in_group = related_uoms.ids
                _logger.info("EMBALAJES ENCONTRADOS PARA EL GRUPO: %s", all_uom_ids_in_group)

        # ---------------------------------------------------------
        # 4. CONVERSIÓN DE CATEGORÍA (Búsqueda por id_secundario_sap)
        # ---------------------------------------------------------
        categ_id_real = 1
        sap_categ_code = product_data.get("categ") 
        _logger.info("BUSCANDO CATEGORÍA SAP: %s", sap_categ_code)
        
        if sap_categ_code:
            category_record = request.env['product.category'].sudo().search([
                ('id_secundario_sap', '=', str(sap_categ_code).strip())
            ], limit=1)
            
            if category_record:
                categ_id_real = category_record.id
                _logger.info("CATEGORÍA ENCONTRADA: %s (ID Odoo: %s)", category_record.name, categ_id_real)
            else:
                _logger.warning("CATEGORÍA SAP '%s' NO EXISTE. USANDO 'All' (ID 1).", sap_categ_code)

        # 5. Lógica de SAT / UNSPSC
        unspsc_id = False
        sat_id = product_data.get("unspsc_code_sat_id")
        if sat_id:
            sat_code = str(sat_id).strip().zfill(8)
            unspsc = request.env['product.unspsc.code'].sudo().search([('code', '=', sat_code)], limit=1)
            if unspsc: 
                unspsc_id = unspsc.id
                _logger.info("SAT CODE ENCONTRADO: %s", sat_code)

        # ---------------------------------------------------------
        # 6. Preparar valores base
        # ---------------------------------------------------------
        vals = {
            "name": product_data.get("name"),
            "sale_ok": product_data.get("sale_ok", True),
            "purchase_ok": product_data.get("purchase_ok", True),
            "type": product_data.get("type", "consu"),
            "list_price": product_data.get("list_price", 0.0),
            "standard_price": product_data.get("standard_price", 0.0),
            "default_code": product_data.get("default_code"),
            "unspsc_code_id": unspsc_id,
            "id_secundario_sap": id_sap,
            "categ_id": categ_id_real,
            "is_storable": product_data.get("is_storable", True),
            "grupo_de_unidad_de_medida_sap": sap_uom_group, # Texto plano de SAP
        }

        if uom_id_real:
            vals["uom_id"] = uom_id_real
            if 'uom_po_id' in request.env['product.template']._fields:
                vals["uom_po_id"] = uom_id_real
            
            # Llenamos la tabla de embalajes con todas las unidades del grupo
            if 'uom_ids' in request.env['product.template']._fields and all_uom_ids_in_group:
                vals["uom_ids"] = [(6, 0, all_uom_ids_in_group)]

        # ---------------------------------------------------------
        # 7. Operación en Base de Datos (Upsert)
        # ---------------------------------------------------------
        try:
            company = request.env['res.company'].sudo().search([], limit=1)
            existing_product = request.env['product.template'].sudo().search([
                ('id_secundario_sap', '=', id_sap)
            ], limit=1)

            if existing_product:
                _logger.info("PRODUCTO EXISTENTE (ID %s). ACTUALIZANDO...", existing_product.id)
                if uom_id_real and existing_product.uom_id.id != uom_id_real:
                    try:
                        existing_product.with_company(company).write(vals)
                    except Exception as e:
                        _logger.warning("BLOQUEO UOM: %s. ACTUALIZANDO SIN UOM.", str(e))
                        vals.pop("uom_id", None)
                        vals.pop("uom_po_id", None)
                        existing_product.with_company(company).write(vals)
                else:
                    existing_product.with_company(company).write(vals)
                action = "updated"
                res_id = existing_product.id
            else:
                _logger.info("PRODUCTO NUEVO. CREANDO...")
                new_product = request.env['product.template'].sudo().with_company(company).create(vals)
                action = "created"
                res_id = new_product.id

            return self._create_response({
                "status": "success", 
                "action": action, 
                "product_template_id": res_id
            }, 200)

        except Exception as e:
            _logger.exception("ERROR CRÍTICO EN API create_product: %s", str(e))
            return self._create_response({"status": "error", "message": f"BD Error: {str(e)}"}, 500)

    @http.route('/api/update_product', type='http', auth='public', methods=['PATCH'], csrf=False)
    def update_product(self, **kwargs):
        # 1. Autenticación por API KEY
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key), ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            _logger.error("API UPDATE - Unauthorized Access")
            return self._create_response({"status": "error", "message": "Unauthorized"}, 401)

        # 2. Parseo del JSON
        try:
            data = json.loads(request.httprequest.data)
            product_data = data.get('product_data', {})
            _logger.info("API UPDATE - JSON RECIBIDO: %s", json.dumps(product_data, indent=2))
        except Exception as e:
            return self._create_response({"status": "error", "message": "Invalid JSON format"}, 400)

        # 3. Validar id_secundario_sap
        sap_id = product_data.get("id_secundario_sap")
        if not sap_id:
            return self._create_response({"status": "error", "message": "Missing id_secundario_sap"}, 400)

        # 4. Buscar Producto
        template = request.env["product.template"].sudo().search([
            ("id_secundario_sap", "=", sap_id)
        ], limit=1)

        if not template:
            _logger.error("API UPDATE - Producto no encontrado: %s", sap_id)
            return self._create_response({"status": "error", "message": "Product not found"}, 404)

        company = request.env['res.company'].sudo().search([], limit=1)
        update_fields = {}

        # ---------------------------------------------------------
        # 5. CONVERSIÓN DE UOM (Búsqueda por alt_code Y grupo_sap)
        # ---------------------------------------------------------
        sap_uom_code = product_data.get("uom")
        sap_uom_group = product_data.get("grupo_de_unidad_de_medida_sap")
        uom_id_real = False
        all_uom_ids_in_group = []

        if sap_uom_code:
            _logger.info("API UPDATE - Buscando UOM: %s en grupo %s", sap_uom_code, sap_uom_group)
            uom_domain = [('alt_code', '=', str(sap_uom_code).strip())]
            if sap_uom_group:
                uom_domain.append(('grupo_de_unidad_de_medida_sap', '=', str(sap_uom_group).strip()))
            
            uom_record = request.env['uom.uom'].sudo().search(uom_domain, limit=1)
            
            if uom_record:
                uom_id_real = uom_record.id
                update_fields['uom_id'] = uom_id_real
                if 'uom_po_id' in template._fields:
                    update_fields['uom_po_id'] = uom_id_real
                
                # Buscar embalajes del grupo
                if sap_uom_group:
                    related_uoms = request.env['uom.uom'].sudo().search([
                        ('grupo_de_unidad_de_medida_sap', '=', str(sap_uom_group).strip())
                    ])
                    all_uom_ids_in_group = related_uoms.ids
                    if 'uom_ids' in template._fields:
                        update_fields['uom_ids'] = [(6, 0, all_uom_ids_in_group)]
            else:
                _logger.error("API UPDATE - UoM no encontrada para alt_code %s", sap_uom_code)
                return self._create_response({"status": "error", "message": f"UoM {sap_uom_code} not found"}, 400)

        # ---------------------------------------------------------
        # 6. CONVERSIÓN DE CATEGORÍA (Búsqueda por id_secundario_sap)
        # ---------------------------------------------------------
        sap_categ_code = product_data.get("categ")
        if sap_categ_code:
            category_record = request.env['product.category'].sudo().search([
                ('id_secundario_sap', '=', str(sap_categ_code).strip())
            ], limit=1)
            if category_record:
                update_fields['categ_id'] = category_record.id
            else:
                _logger.warning("API UPDATE - Categoría SAP %s no encontrada", sap_categ_code)

        # ---------------------------------------------------------
        # 7. Lógica de SAT / UNSPSC
        # ---------------------------------------------------------
        sat_id = product_data.get("unspsc_code_sat_id")
        if sat_id:
            sat_code = str(sat_id).strip().zfill(8)
            unspsc = request.env['product.unspsc.code'].sudo().search([('code', '=', sat_code)], limit=1)
            if unspsc:
                update_fields['unspsc_code_id'] = unspsc.id

        # ---------------------------------------------------------
        # 8. Mapeo de campos maestros
        # ---------------------------------------------------------
        mapping = {
            "name": "name",
            "sale_ok": "sale_ok",
            "purchase_ok": "purchase_ok",
            "list_price": "list_price",
            "standard_price": "standard_price",
            "default_code": "default_code",
            "type": "type",
            "invoice_policy": "invoice_policy",
            "is_storable": "is_storable",
            "grupo_de_unidad_de_medida_sap": "grupo_de_unidad_de_medida_sap"
        }

        for json_key, odoo_field in mapping.items():
            if json_key in product_data:
                update_fields[odoo_field] = product_data[json_key]

        # Impuestos
        if "taxes_id" in product_data:
            update_fields["taxes_id"] = [(6, 0, product_data["taxes_id"])]
        if "supplier_taxes_id" in product_data:
            update_fields["supplier_taxes_id"] = [(6, 0, product_data["supplier_taxes_id"])]

        # ---------------------------------------------------------
        # 9. Escritura en DB (Con protección de UoM)
        # ---------------------------------------------------------
        try:
            if uom_id_real and template.uom_id.id != uom_id_real:
                try:
                    template.with_company(company).write(update_fields)
                except Exception as e:
                    _logger.warning("API UPDATE - Bloqueo UoM: %s. Reintentando sin UoM.", str(e))
                    update_fields.pop("uom_id", None)
                    update_fields.pop("uom_po_id", None)
                    template.with_company(company).write(update_fields)
            else:
                template.with_company(company).write(update_fields)
        except Exception as e:
            _logger.exception("API UPDATE - Error al escribir")
            return self._create_response({"status": "error", "message": f"DB Write Error: {str(e)}"}, 500)

        # ---------------------------------------------------------
        # 10. Ajuste de Inventario (Si viene qty)
        # ---------------------------------------------------------
        qty = product_data.get("qty")
        warehouse_code = product_data.get("warehouse_code")
        
        if qty is not None:
            if not warehouse_code:
                return self._create_response({"status": "error", "message": "warehouse_code required for qty update"}, 400)
            
            warehouse = request.env["stock.warehouse"].sudo().search([("name", "=", warehouse_code)], limit=1)
            if not warehouse:
                return self._create_response({"status": "error", "message": "Warehouse not found"}, 404)
            
            product_variant = template.product_variant_id
            stock_location = warehouse.lot_stock_id
            pronosticado_sap = product_data.get("pronosticado_sap", 0)

            try:
                quant = request.env["stock.quant"].sudo().search([
                    ('product_id', '=', product_variant.id),
                    ('location_id', '=', stock_location.id),
                    ('company_id', '=', company.id)
                ], limit=1)

                quant_vals = {
                    'product_id': product_variant.id,
                    'location_id': stock_location.id,
                    'inventory_quantity': float(qty),
                    'company_id': company.id,
                    'pronosticado_sap': float(pronosticado_sap),
                }

                if quant:
                    quant.with_context(inventory_mode=True).write({
                        'inventory_quantity': float(qty),
                        'pronosticado_sap': float(pronosticado_sap)
                    })
                else:
                    quant = request.env["stock.quant"].sudo().with_context(inventory_mode=True).create(quant_vals)
                
                quant.action_apply_inventory()
                _logger.info("API UPDATE - Inventario aplicado: %s", qty)
            except Exception as e:
                _logger.error("API UPDATE - Error en inventario: %s", str(e))

        return self._create_response({
            "status": "success",
            "product_id": template.id,
            "updated_fields": list(update_fields.keys())
        }, 200)