# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID
from odoo.http import request, Response
import json

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
        """Valida las llaves de API y devuelve el registro si es exitoso."""
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        if not api_key or not secret_key:
            return None, "Missing required headers (apiKey and/or secretKey)", 400

        # Usamos sudo() y SUPERUSER_ID para evitar problemas de sesión en auth='none'
        api_record = request.env['stings.key'].sudo().with_user(SUPERUSER_ID).search([
            ('key', '=', api_key),
            ('secret_key', '=', secret_key)
        ], limit=1)

        if not api_record:
            return None, "Invalid API Key or Secret Key", 401

        return api_record, None, 200

    @http.route('/api/create_contact', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def create_contact(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        # 1. Autenticación
        api_record, error_msg, status = self._validate_auth()
        if error_msg:
            return self._create_response({"status": "error", "message": error_msg}, status)

        # 2. Parsing de Datos
        try:
            data = json.loads(request.httprequest.data)
            contact_data = data.get('contact_data', {})
        except Exception:
            return self._create_response({"status": "error", "message": "Invalid JSON format"}, 400)

        # 3. Validación de campos mínimos
        required_fields = ['name', 'id_secondary']
        missing = [f for f in required_fields if not contact_data.get(f)]
        if missing:
            return self._create_response({'status': 'error', 'message': f'Missing: {", ".join(missing)}'}, 400)

        # 4. Lógica de Dirección de Entrega (Shipping Partner)
        # Si recibimos 'ref' en el JSON, buscamos al padre
        parent_id = None
        contact_type = 'contact'  # Por defecto es un contacto normal

        external_ref = contact_data.get('ref')
        if external_ref:
            # Buscamos al partner que tenga esa referencia única
            parent_partner = request.env['res.partner'].sudo().with_user(SUPERUSER_ID).search([
                ('ref', '=', external_ref)
            ], limit=1)

            if parent_partner:
                parent_id = parent_partner.id
                contact_type = 'delivery'  # Lo marcamos como dirección de entrega
            else:
                # Opcional: Si quieres que falle si no encuentra la referencia, descomenta:
                # return self._create_response({'status': 'error', 'message': f'Parent with ref {external_ref} not found'}, 404)
                pass

        # 5. Creación
        try:
            new_contact = request.env['res.partner'].sudo().with_user(SUPERUSER_ID).with_context(
                l10n_mx_edi_force_validate_vat=False
            ).create({
                'id_secondary': contact_data.get('id_secondary'),
                'type': contact_type,  # 'delivery' si encontramos el padre por ref
                'parent_id': parent_id,  # El ID interno de Odoo encontrado
                'active': contact_data.get('active', True),
                'company_type': 'person',  # Las direcciones suelen ser personas/localizaciones
                'name': contact_data.get('name'),
                'email': contact_data.get('email'),
                'phone': contact_data.get('phone'),
                'street': contact_data.get('street'),
                'street2': contact_data.get('street2'),

                'l10n_mx_edi_locality_id': contact_data.get('locality_id'),
                'l10n_mx_edi_locality': contact_data.get('locality_name'),
                'l10n_mx_edi_colony': contact_data.get('colony_name'),
                'l10n_mx_edi_colony_code': contact_data.get('colony_code'),

                'country_id': contact_data.get('country_id'),
                'state_id': contact_data.get('state_id'),
                'city_id': contact_data.get('city_id'),
                'zip': contact_data.get('zip'),
                'city': contact_data.get('city'),

                'vat': contact_data.get('vat'),
                'l10n_mx_edi_usage': contact_data.get('l10n_mx_edi_usage'),
                'l10n_mx_edi_fiscal_regime': contact_data.get('l10n_mx_edi_fiscal_regime'),
                'l10n_mx_edi_payment_method_id': contact_data.get('l10n_mx_edi_payment_method_id'),
                'property_payment_term_id': contact_data.get('property_payment_term_id'),
                'lang': contact_data.get('lang', 'es_MX'),
                'ref': contact_data.get('ref'),
            })

            print(
                contact_data.get('id_secondary'),
                contact_data.get('type'),
                contact_data.get('parent_id'),
                contact_data.get('active'),
                contact_data.get('company_type'),
                contact_data.get('name'),
                contact_data.get('email'),
                contact_data.get('phone'),
                contact_data.get('street'),
                contact_data.get('street2'),
                contact_data.get('l10n_mx_edi_locality_id'),
                contact_data.get('l10n_mx_edi_locality'),
                contact_data.get('l10n_mx_edi_colony'),
                contact_data.get('l10n_mx_edi_colony_code'),
                contact_data.get('country_id'),
                contact_data.get('state_id'),
                contact_data.get('city_id'),
                contact_data.get('zip'),
                contact_data.get('vat'),
                contact_data.get('l10n_mx_edi_usage'),
                contact_data.get('l10n_mx_edi_fiscal_regime'),
                contact_data.get('l10n_mx_edi_fiscal_regime'),
                contact_data.get('l10n_mx_edi_payment_method_id'),
                contact_data.get('property_payment_term_id'),
                contact_data.get('lang'),
                contact_data.get('property_prefayment_term_id'), 
            )

            return self._create_response({
                'status': 'success',
                'contact_id': new_contact.id,
                'parent_linked': parent_id is not None
            }, 201)

        except Exception as e:
            return self._create_response({"status": "error", "message": str(e)}, 500)

    # Endpoint para actualizar un contacto utilizando el 'id_secondary'
    @http.route('/api/update_contact',
                type='http',
                auth='none',
                methods=['PATCH'],
                csrf=False)
    def update_contact(self, **kwargs):
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')

        # 1. Validar la clave de API
        if not api_key or not secret_key:
            return self._create_response(
                {"status": "error",
                    "message": "Missing required headers (apiKey and/or secretKey)"},
                400
            )

        try:
            api_record = request.env['stings.key'].sudo().search(
                [('key', '=', api_key), ('secret_key', '=', secret_key)], limit=1)
            if not api_record:
                return self._create_response(
                    {"status": "error", "message": "Invalid API Key or Secret Key"},
                    401
                )
        except Exception as e:
            return self._create_response(
                {"status": "error", "message": f"Authentication check failed: {e}"},
                500
            )

        # 2. Obtener y decodificar los datos del cuerpo (Necesario para type='http')
        try:
            # Leemos y decodificamos el JSON del cuerpo de la solicitud
            data = json.loads(request.httprequest.data)
        except json.JSONDecodeError:
            return self._create_response(
                {"status": "error", "message": "Invalid JSON payload format."},
                400
            )

        contact_data = data.get('contact_data', {})

        # 3. Validar los datos del contacto
        if not contact_data or not isinstance(contact_data, dict):
            return self._create_response(
                {'status': 'error', 'message': 'No valid contact data provided in payload.'},
                400
            )

        name = contact_data.get('name')
        # Usamos el ID secundario para identificar el contacto
        id_secondary = contact_data.get('id_secondary')

        # Validación de campos esenciales
        if not id_secondary or not name:
            missing_fields = []
            if not id_secondary:
                missing_fields.append('id_secondary')
            if not name:
                missing_fields.append('name')

            return self._create_response(
                {'status': 'error',
                    'message': f'Missing required contact fields: {", ".join(missing_fields)}'},
                400
            )

        # Verificar si el contacto existe por 'id_secondary'
        try:
            existing_contact = request.env['res.partner'].sudo().search([
                ('id_secondary', '=', id_secondary),
            ], limit=1)

            if not existing_contact:
                return self._create_response(
                    {'status': 'error',
                        'message': f"Contact with id_secondary {id_secondary} not found"},
                    404  # 404 Not Found
                )

            # No permitir la actualización del 'id_secondary' (lo dejamos igual)
            # Eliminar el campo de 'id_secondary' si está presente en la solicitud
            contact_data.pop('id_secondary', None)

            # Actualizar el contacto con los nuevos datos
            existing_contact.write({
                'active': contact_data.get('active', True),
                'company_type': contact_data.get('company_type'),
                'name': contact_data.get('name'),
                'email': contact_data.get('email'),
                'phone': contact_data.get('phone'),
                'parent_id': contact_data.get('parent_id'),
                'street': contact_data.get('street'),
                'street2': contact_data.get('street2'),

                'l10n_mx_edi_locality_id': contact_data.get('locality_id'),
                'l10n_mx_edi_locality': contact_data.get('locality_name'),
                'l10n_mx_edi_colony_name': contact_data.get('colony_name'),
                'l10n_mx_edi_colony_code': contact_data.get('colony_code'),

                'city_id': contact_data.get('city_id'),
                'city': contact_data.get('city'),
                'state_id': contact_data.get('state_id'),
                'zip': contact_data.get('zip'),
                'country_id': contact_data.get('country_id'),

                'vat': contact_data.get('vat'),
                'l10n_mx_edi_usage': contact_data.get('l10n_mx_edi_usage'),
                'l10n_mx_edi_fiscal_regime': contact_data.get('l10n_mx_edi_fiscal_regime'),
                'l10n_mx_edi_payment_method_id': contact_data.get('l10n_mx_edi_payment_method_id'),
                'property_payment_term_id': contact_data.get('property_payment_term_id'),
                'property_product_pricelist': contact_data.get('property_product_pricelist'),
                'user_id': contact_data.get('user_id'),
                'lang': contact_data.get('lang', 'es_MX'),
                'ref': contact_data.get('ref'),
            })

            return self._create_response(
                {'status': 'success', 'contact_id': existing_contact.id},
                200  # 200 OK
            )

        except Exception as e:
            return self._create_response(
                {"status": "error", "message": f"Update failed: {e}"},
                500
            )

