# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json
import logging

_logger = logging.getLogger(__name__)

class ApiUomController(http.Controller):

    def _create_response(self, data, status_code):
        """Genera la respuesta JSON estandarizada."""
        return Response(
            json.dumps(data),
            status=status_code,
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/api/create_uom', type='http', auth='public', methods=['POST'], csrf=False)
    def sync_uom(self, **kwargs):
        # 1. Autenticación por Headers
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')
        
        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key), ('secret_key', '=', secret_key)
        ], limit=1)
        
        if not api_record:
            return self._create_response({"status": "error", "message": "Unauthorized"}, 401)

        try:
            
            # 2. Carga de datos del Payload
            body = request.httprequest.data.decode('utf-8')
            data = json.loads(body)
            lineas = data.get('unidades_medida', [])
            grupo_uom = data.get('grupo_uom')
            
            if not grupo_uom or not lineas:
                return self._create_response({"status": "error", "message": "Faltan datos (grupo_uom o unidades_medida)"}, 400)

            # Variable para capturar el ID del primer registro creado/encontrado
            primer_id_odoo = False

            # 3. Procesamiento de la lista de unidades
            for index, linea in enumerate(lineas):
                alt_code = linea.get('alt_code')
                alt_qty = float(linea.get('alt_qty', 1.0))
                base_qty = float(linea.get('base_qty', 1.0))

                # Buscar el ID del código UNSPSC (SAT) por el campo 'code'
                unspsc_rec = request.env['product.unspsc.code'].sudo().search([
                    ('code', '=', alt_code)
                ], limit=1)

                if not unspsc_rec:
                    _logger.warning(f"API UOM: Código UNSPSC '{alt_code}' no encontrado en Odoo.")
                    continue

                # Cálculo solicitado: cantidad_base_sap / cantidad_de_equivalencia
                factor_calculado =  base_qty / alt_qty if alt_qty != 0 else 0.0
                # Así obtenemos el nombre traducido correctamente
                nombre_en_espanol = unspsc_rec.with_context(lang='es_MX').name or unspsc_rec.name
                # Construcción del diccionario de valores (Mapeo estricto)
                vals = {
                    'name': nombre_en_espanol,  # Sacamos el nombre del modelo UNSPSC
                    'unspsc_code_id': unspsc_rec.id,
                    'grupo_de_unidad_de_medida_sap': grupo_uom,
                    'cantidad_base_sap': base_qty,
                    'cantidad_de_equivalencia': alt_qty,
                    'relative_factor': float(factor_calculado),
                    'alt_code':alt_code,
                }

                # Asignación del relative_uom_id
                # Si no es el primero, le ponemos el ID del primero
                if index > 0 and primer_id_odoo:
                    vals['relative_uom_id'] = primer_id_odoo

                # 4. Búsqueda para Actualizar o Crear
                uom_existente = request.env['uom.uom'].sudo().search([
                    ('unspsc_code_id', '=', unspsc_rec.id),
                    ('grupo_de_unidad_de_medida_sap', '=', grupo_uom)
                ], limit=1)

                if uom_existente:
                    # Evitamos recursión: No actualizamos relative_uom_id si es el mismo registro
                    if index == 0:
                        vals.pop('relative_uom_id', None)
                    
                    uom_existente.sudo().write(vals)
                    id_actual = uom_existente.id
                    _logger.info(f"API UOM: Actualizada ID {id_actual}")
                else:
                    # Creación del nuevo registro
                    nueva_uom = request.env['uom.uom'].sudo().create(vals)
                    id_actual = nueva_uom.id
                    _logger.info(f"API UOM: Creada ID {id_actual}")

                # El primer ID de la lista se guarda para referenciarlo en los siguientes
                if index == 0:
                    primer_id_odoo = id_actual

            return self._create_response({"status": "success", "message": "Sincronización exitosa"}, 200)

        except Exception as e:
            _logger.error(f"Error Crítico API UOM: {str(e)}", exc_info=True)
            return self._create_response({"status": "error", "message": str(e)}, 500)