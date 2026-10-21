# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID
from odoo.http import request, Response
from markupsafe import Markup
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
        headers = make_cors_headers() + [('Content-Type', 'application/json')]
        return Response(json.dumps(data), status=status_code, headers=headers)

    # =========================================================================
    # CHATTER: snapshot de valores y publicación (mismo patrón que contactos)
    # =========================================================================
    def _snapshot(self, record, field_names):
        """Foto legible de los valores actuales de los campos indicados."""
        snap = {}
        for fname in field_names:
            field = record._fields.get(fname)
            if not field:
                continue
            val = record[fname]
            if field.type == 'many2one':
                snap[fname] = val.display_name or ''
            elif field.type == 'selection':
                snap[fname] = dict(field._description_selection(record.env)).get(val, val or '')
            elif field.type == 'boolean':
                snap[fname] = 'Sí' if val else 'No'
            else:
                snap[fname] = '' if val in (False, None) else str(val)
        return snap

    def _lines_summary_html(self, results):
        """Bloque HTML con el resumen de líneas procesadas en la petición."""
        body = Markup("<p><b>Líneas recibidas</b></p><ul>")
        body += Markup("<li>Creadas: %s</li>") % results["created"]
        body += Markup("<li>Actualizadas: %s</li>") % results["updated"]
        body += Markup("<li>Con error: %s</li>") % len(results["errors"])
        body += Markup("</ul>")
        if results["errors"]:
            body += Markup("<p><b>Errores</b></p><ul>")
            for err in results["errors"]:
                body += Markup("<li><small>%s</small></li>") % err
            body += Markup("</ul>")
        return body

    def _post_create_chatter(self, price_list, values, origen, results):
        """Publica en el chatter los valores con los que se creó la lista por API."""
        try:
            rows = []
            for fname, val in values.items():
                if val in ('', None):
                    continue
                label = price_list._fields[fname].string
                rows.append(Markup("<li><b>%s</b>: %s</li>") % (label, val))

            body = Markup("<p><b>Creación vía API SAP</b> (%s)</p>") % origen
            if rows:
                body += Markup("<ul>%s</ul>") % Markup('').join(rows)
            body += self._lines_summary_html(results)

            price_list.with_user(SUPERUSER_ID).sudo().message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except Exception as e:
            # El chatter nunca debe tumbar la sincronización
            _logger.warning(f"⚠️ No se pudo publicar en chatter de la lista {price_list.id}: {e}")

    def _post_update_chatter(self, price_list, before, after, origen, results):
        """Publica en el chatter los cambios recibidos por API."""
        try:
            rows = []
            for fname, old in before.items():
                new = after.get(fname, '')
                if old != new:
                    label = price_list._fields[fname].string
                    rows.append(
                        Markup("<li><b>%s</b>: %s → %s</li>") % (label, old or '—', new or '—')
                    )

            body = Markup("<p><b>Actualización vía API SAP</b> (%s)</p>") % origen
            if rows:
                body += Markup("<ul>%s</ul>") % Markup('').join(rows)
            else:
                body += Markup("<p>Sin cambios en la cabecera.</p>")
            body += self._lines_summary_html(results)

            price_list.with_user(SUPERUSER_ID).sudo().message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except Exception as e:
            _logger.warning(f"⚠️ No se pudo publicar en chatter de la lista {price_list.id}: {e}")

    # =========================================================================
    # ENDPOINT
    # =========================================================================
    @http.route('/api/price_list', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def sync_price_list(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        # 1. Autenticación por API Key
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key), ('secret_key', '=', secret_key)
        ], limit=1)
        if not api_record:
            return self._create_response({"status": "error", "message": "Unauthorized"}, 401)

        # auth='public' deja al usuario público como env.user: el tracking y el
        # message_post saldrían a su nombre y la compañía por defecto sería la suya.
        # Igual que en contactos, se trabaja como SUPERUSER.
        request.update_env(user=SUPERUSER_ID)

        # 2. Leer JSON
        try:
            data = json.loads(request.httprequest.data)
            list_data = data.get('price_list')
            if not list_data or not list_data.get('id_secundario_sap'):
                return self._create_response({"status": "error", "message": "Missing price_list or id_secundario_sap"}, 400)
        except Exception:
            return self._create_response({"status": "error", "message": "Invalid JSON format"}, 400)

        sap_list_id = str(list_data.get('id_secundario_sap'))
        _logger.info(f"[API price_list] Recibida lista SAP {sap_list_id} | name={list_data.get('name')}")

        # 3. Buscar o Crear la Cabecera
        PriceList = request.env['sap.price.list'].sudo().with_context(active_test=False)
        price_list = PriceList.search([('id_secundario_sap', '=', sap_list_id)], limit=1)

        list_vals = {
            'name': list_data.get('name'),
            'active': list_data.get('active', True),
            'id_secundario_sap': sap_list_id,
        }

        before = {}
        if price_list:
            before = self._snapshot(price_list, list_vals.keys())
            price_list.write(list_vals)
            action = "updated"
        else:
            price_list = PriceList.create(list_vals)
            action = "created"
        _logger.info(f"[API price_list] Cabecera {action}: id={price_list.id}")

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
                        ('unspsc_code_id.code', '=', str(uom_input))  # Común en localización MX
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
                    'uom_id': odoo_uom.id,  # Usamos el ID de Odoo encontrado
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

        # 5. Trazabilidad en el chatter de la lista (mismo patrón que contactos)
        origen = 'POST /api/price_list'
        if action == "updated":
            after = self._snapshot(price_list, list_vals.keys())
            self._post_update_chatter(price_list, before, after, f"{origen} (lista existente)", results)
        else:
            created_values = self._snapshot(price_list, list_vals.keys())
            self._post_create_chatter(price_list, created_values, origen, results)

        _logger.info(f"[API price_list] Resultado lista {price_list.id}: {action} | líneas {results}")

        return self._create_response({
            "status": "success",
            "action": action,
            "price_list_id": price_list.id,
            "summary": results
        }, 200)
