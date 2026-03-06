# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID
from odoo.http import request, Response
import json
import logging

_logger = logging.getLogger(__name__)

ALLOWED_ORIGIN = "*"

class ApiController(http.Controller):

    def _create_response(self, data, status_code):
        headers = [
            ('Access-Control-Allow-Origin', ALLOWED_ORIGIN),
            ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, PATCH'),
            ('Access-Control-Allow-Headers', 'Content-Type, apiKey, secretKey'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Content-Type', 'application/json')
        ]
        return Response(json.dumps(data), status=status_code, headers=headers)

    def _validate_auth(self):
        api_key = request.httprequest.headers.get('apiKey')
        secret_key = request.httprequest.headers.get('secretKey')
        if not api_key or not secret_key:
            return None, "Missing headers", 400
        api_record = request.env['stings.key'].sudo().search([
            ('key', '=', api_key),
            ('secret_key', '=', secret_key)
        ], limit=1)
        if not api_record:
            return None, "Invalid Keys", 401
        return api_record, None, 200

    def _get_contact_type_logic(self, contact_data, id_secondary):
        """
        Lógica unificada para determinar is_company, parent_id y el type de Odoo.
        
        REGLA CLAVE:
        - Si tiene parent_id → ES HIJO (el id_secondary es solo informativo/respaldo del padre)
        - Si NO tiene parent_id → ES PADRE (el id_secondary es su identificador único)
        """
        raw_type = contact_data.get('company_type')
        input_parent_id = contact_data.get('parent_id')
        job_position = contact_data.get('job_position')
        
        _logger.info("="*80)
        _logger.info("INICIANDO _get_contact_type_logic")
        _logger.info(f"  - raw_type (company_type): {raw_type}")
        _logger.info(f"  - input_parent_id: {input_parent_id}")
        _logger.info(f"  - id_secondary: {id_secondary} (en hijos es solo respaldo del padre)")
        _logger.info(f"  - job_position: {job_position}")
        
        valid_odoo_types = ['contact', 'delivery', 'invoice', 'other', 'private']
        
        final_parent_id = False
        is_company_val = True
        address_type = 'contact'

        # 1. Si tiene parent_id, ES HIJO (sin importar el valor de id_secondary)
        if input_parent_id:
            _logger.info(f"  >>> Tiene parent_id='{input_parent_id}' - ES HIJO")
            _logger.info(f"  >>> El id_secondary '{id_secondary}' es solo informativo (respaldo del padre)")
            _logger.info(f"  >>> Buscando padre con id_secondary='{input_parent_id}'")
            
            parent_partner = request.env['res.partner'].sudo().search([
                ('id_secondary', '=', input_parent_id),
                ('parent_id', '=', False)
            ], limit=1)
            
            if parent_partner:
                final_parent_id = parent_partner.id
                is_company_val = False
                
                _logger.info(f"  >>> PADRE ENCONTRADO: ID={parent_partner.id}, Name='{parent_partner.name}'")
                
                if raw_type in valid_odoo_types:
                    address_type = raw_type
                    _logger.info(f"  >>> Type asignado desde company_type: '{address_type}'")
                elif raw_type == 'person':
                    address_type = 'contact'
                    _logger.info(f"  >>> company_type='person' -> Type='contact'")
            else:
                _logger.warning(f"  >>> ⚠️ PADRE NO ENCONTRADO con id_secondary='{input_parent_id}'")
        else:
            _logger.info(f"  >>> NO tiene parent_id - ES PADRE")
            _logger.info(f"  >>> El id_secondary '{id_secondary}' es su identificador único")
        
        # 2. Si no tiene parent_id, es contacto padre
        if not final_parent_id:
            if raw_type == 'company':
                is_company_val = True
                address_type = 'contact'
                _logger.info(f"  >>> Es PADRE tipo 'company'")
            elif raw_type in ['person'] + valid_odoo_types or job_position:
                is_company_val = False
                address_type = raw_type if raw_type in valid_odoo_types else 'contact'
                _logger.info(f"  >>> Es PADRE tipo 'person' o con job_position")

        _logger.info(f"RESULTADO _get_contact_type_logic:")
        _logger.info(f"  - is_company: {is_company_val}")
        _logger.info(f"  - parent_id: {final_parent_id}")
        _logger.info(f"  - address_type: {address_type}")
        _logger.info("="*80)
        
        return is_company_val, final_parent_id, address_type
    #
    #
    @http.route('/api/create_contact', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def create_contact(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        try:
            data = json.loads(request.httprequest.data)
            contact_data = data.get('contact_data', {})
            id_secondary = contact_data.get('id_secondary')

            _logger.info("\n" + "#"*100)
            _logger.info("### API CREATE_CONTACT LLAMADA ###")
            _logger.info(f"### id_secondary: {id_secondary}")
            _logger.info(f"### name: {contact_data.get('name')}")
            _logger.info(f"### company_type: {contact_data.get('company_type')}")
            _logger.info(f"### parent_id: {contact_data.get('parent_id')}")
            _logger.info("#"*100 + "\n")

            if not id_secondary or not contact_data.get('name'):
                return self._create_response({'status': 'error', 'message': 'Missing name or id_secondary'}, 400)

            # Lógica de tipo y jerarquía
            is_company, parent_id, addr_type = self._get_contact_type_logic(contact_data, id_secondary)

            # Localidad
            locality_id = False
            loc_name = contact_data.get('locality_name')
            if loc_name:
                loc = request.env['l10n_mx_edi.res.locality'].sudo().search([('name', 'ilike', loc_name)], limit=1)
                if loc:
                    locality_id = loc.id

            # Término de pago por código SAP
            payment_term = False
            sap_payment_code = False
            if contact_data.get('l10n_mx_edi_payment_method_id'):
                sap_payment_code = str(contact_data.get('l10n_mx_edi_payment_method_id'))
                _logger.info("================================================================================")
                _logger.info("PROCESANDO l10n_mx_edi_payment_method_id (CREATE)")
                _logger.info("  - sap_payment_code recibido (convertido a str): %s", sap_payment_code)

                payment_term = request.env['account.payment.term'].sudo().search(
                    [('sap_payment_term_code', '=', sap_payment_code)],
                    limit=1
                )

                if payment_term:
                    _logger.info("  - payment_term ENCONTRADO: id=%s | name=%s | sap_code=%s",
                                 payment_term.id, payment_term.name, payment_term.sap_payment_term_code)
                else:
                    _logger.warning("  - NO se encontró account.payment.term con sap_payment_term_code='%s'", sap_payment_code)

                _logger.info("================================================================================")
            else:
                _logger.info("  - l10n_mx_edi_payment_method_id NO viene en el payload, se omite término de pago")

            # Construcción de valores para Odoo
            vals = {
                'name': contact_data.get('name'),
                'is_company': is_company,
                'parent_id': parent_id,
                'type': addr_type,
                'function': contact_data.get('job_position'),
                'email': contact_data.get('email'),
                'phone': contact_data.get('phone'),
                'street': contact_data.get('street'),
                'street2': contact_data.get('street2'),
                'zip': contact_data.get('zip'),
                'city': contact_data.get('city'),
                'l10n_mx_edi_usage': contact_data.get('l10n_mx_edi_usage'),
                'l10n_mx_edi_fiscal_regime': contact_data.get('l10n_mx_edi_fiscal_regime'),
                'l10n_mx_edi_payment_method_id': payment_term.id if payment_term else False,
                'vat': contact_data.get('vat'),
                'ref': contact_data.get('ref'),
                'l10n_mx_edi_locality_id': locality_id,
                'l10n_mx_edi_colony': contact_data.get('colony_name'),
                'u_entrega_lunes': contact_data.get('u_entrega_lunes', 'No'),
                'u_entrega_martes': contact_data.get('u_entrega_martes', 'No'),
                'u_entrega_miercoles': contact_data.get('u_entrega_miercoles', 'No'),
                'u_entrega_jueves': contact_data.get('u_entrega_jueves', 'No'),
                'u_entrega_viernes': contact_data.get('u_entrega_viernes', 'No'),
                'u_entrega_sabado': contact_data.get('u_entrega_sabado', 'No'),
                'u_entrega_domingo': contact_data.get('u_entrega_domingo', 'No'),
                'u_hora_entrega_inicio': contact_data.get('u_hora_entrega_inicio', 0),
                'u_hora_entrega_fin': contact_data.get('u_hora_entrega_fin', 0),
                'u_estatus_cliente': contact_data.get('u_estatus_cliente', '0'),
                'u_dias_revision': contact_data.get('u_dias_revision', ''),
                'u_sap_credit_limit': float(contact_data.get('credit_limit') or 0.0),
                'u_sap_credit_balance': float(contact_data.get('credit_balance') or 0.0),
                'u_sap_credit_available': float(contact_data.get('credit_available') or 0.0),
                'u_sap_use_credit_limit': bool(contact_data.get('use_partner_credit_limit', True)),
                'u_is_sap_client': True,
                'id_secondary': id_secondary,
                'lang': contact_data.get('lang', 'es_MX'),
            }

            # Agregar country_id si viene en el payload
            if 'country_id' in contact_data and contact_data.get('country_id'):
                vals['country_id'] = int(contact_data.get('country_id'))

            # Agregar state_id si viene en el payload
            if 'state_id' in contact_data and contact_data.get('state_id'):
                vals['state_id'] = int(contact_data.get('state_id'))

            # Buscar usuario por salesPersonCode y asignar user_id
            if 'salesPersonCode' in contact_data:
                sales_person_code = contact_data.get('salesPersonCode')
                if sales_person_code:
                    try:
                        user = request.env['res.users'].sudo().search([
                            ('sap_sales_person_code', '=', int(sales_person_code))
                        ], limit=1)

                        if user and len(user) == 1:
                            vals['user_id'] = user.id
                            _logger.info("  👤 Vendedor asignado: %s (código SAP: %s)", user.name, sales_person_code)
                        elif len(user) > 1:
                            _logger.warning("  ⚠️ Múltiples usuarios con sap_sales_person_code=%s, se omite", sales_person_code)
                        else:
                            _logger.warning("  ⚠️ No se encontró usuario con sap_sales_person_code=%s", sales_person_code)
                    except (ValueError, TypeError) as e:
                        _logger.warning("  ⚠️ salesPersonCode inválido '%s': %s", sales_person_code, str(e))

            partner_env = request.env['res.partner'].sudo().with_context(l10n_mx_edi_force_validate_vat=False)

            # --- LÓGICA DE BÚSQUEDA SEGÚN JERARQUÍA ---
            existing = False

            _logger.info("\n" + "+"*80)
            _logger.info("INICIANDO BÚSQUEDA DE CONTACTO EXISTENTE")

            if parent_id:
                _logger.info(f">>> RAMA: ES HIJO (parent_id={parent_id})")
                _logger.info(f"    - name = '{contact_data.get('name')}'")
                _logger.info(f"    - parent_id = {parent_id}")

                existing = partner_env.search([
                    ('name', '=', contact_data.get('name')),
                    ('parent_id', '=', parent_id)
                ], limit=1)

                if existing:
                    _logger.info(f">>> ✓ HIJO ENCONTRADO: ID={existing.id} | ACCIÓN: ACTUALIZAR")
                else:
                    _logger.info(f">>> ✗ HIJO NO ENCONTRADO | ACCIÓN: CREAR")

            else:
                _logger.info(f">>> RAMA: ES PADRE (parent_id=False)")
                _logger.info(f"    - id_secondary = '{id_secondary}'")

                existing = partner_env.search([
                    ('id_secondary', '=', id_secondary),
                    ('parent_id', '=', False)
                ], limit=1)

                if existing:
                    _logger.info(f">>> ✓ PADRE ENCONTRADO: ID={existing.id} | ACCIÓN: ACTUALIZAR")
                else:
                    _logger.info(f">>> ✗ PADRE NO ENCONTRADO | ACCIÓN: CREAR")

            _logger.info("+"*80 + "\n")

            # Crear o actualizar
            if existing:
                _logger.info(f">>> EJECUTANDO: existing.write(vals) | ID: {existing.id}")
                existing.write(vals)
                action = "updated"
                contact_id = existing.id
                partner_record = existing
            else:
                _logger.info(f">>> EJECUTANDO: partner_env.create(vals)")
                new_contact = partner_env.create(vals)
                action = "created"
                contact_id = new_contact.id
                partner_record = new_contact
                _logger.info(f">>> Nuevo contacto creado con ID: {contact_id}")

            # Escribir términos de pago con with_company
            if payment_term:
                company = partner_record.company_id or request.env['res.company'].sudo().search([], limit=1)
                _logger.info("================================================================================")
                _logger.info("ESCRIBIENDO TÉRMINOS DE PAGO CON with_company (CREATE)")
                _logger.info("  - partner_record.id: %s", partner_record.id)
                _logger.info("  - company: id=%s | name=%s", company.id, company.name)
                _logger.info("  - sap_payment_code: %s | payment_term.id: %s", sap_payment_code, payment_term.id)

                # 1. Guardar código SAP en campo auxiliar (Char)
                partner_record.with_company(company).write({
                    'x_studio_terminos_pago_sap_auxiliar': sap_payment_code,
                })
                _logger.info("  - PASO 1 OK: x_studio_terminos_pago_sap_auxiliar = '%s'", sap_payment_code)

                # 2. Escribir property_payment_term_id con with_company
                partner_record.with_company(company).write({
                    'property_payment_term_id': payment_term.id,
                })

                # Verificar
                partner_record.invalidate_recordset()
                valor_property = partner_record.with_company(company).property_payment_term_id
                _logger.info("  - VERIFICACION property_payment_term_id: id=%s | name=%s",
                             valor_property.id if valor_property else 'VACIO',
                             valor_property.name if valor_property else 'VACIO')

                if valor_property and valor_property.id == payment_term.id:
                    _logger.info("  - ✅ ÉXITO: property_payment_term_id escrito correctamente")
                else:
                    _logger.warning("  - ⚠️ FALLO: property_payment_term_id NO quedó con el valor esperado")

                _logger.info("================================================================================")

            _logger.info("\n" + "#"*100)
            _logger.info("### RESULTADO FINAL ###")
            _logger.info(f"### Acción: {action}")
            _logger.info(f"### Contact ID: {contact_id}")
            _logger.info(f"### Type: {addr_type}")
            _logger.info(f"### Is Company: {is_company}")
            _logger.info(f"### Parent ID: {parent_id}")
            _logger.info("#"*100 + "\n")

            return self._create_response({
                'status': 'success',
                'contact_id': contact_id,
                'action': action,
                'type_applied': addr_type,
                'is_company': is_company,
                'parent_id': parent_id,
                'is_child': bool(parent_id)
            }, 200)

        except Exception as e:
            _logger.error(f"❌ ERROR en create_contact: {str(e)}", exc_info=True)
            return self._create_response({"status": "error", "message": str(e)}, 500)
    ##
    ##
    @http.route('/api/update_contact', type='http', auth='none', methods=['PATCH', 'OPTIONS'], csrf=False)
    def update_contact(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        try:
            data = json.loads(request.httprequest.data)
            contact_data = data.get('contact_data', {})
            id_secondary = contact_data.get('id_secondary')

            if not id_secondary:
                return self._create_response({'status': 'error', 'message': 'Missing id_secondary'}, 400)

            # Lógica de tipo y jerarquía
            is_company, parent_id, addr_type = self._get_contact_type_logic(contact_data, id_secondary)

            # Buscar el contacto según la misma lógica que create
            partner_env = request.env['res.partner'].sudo()
            existing = False

            if parent_id:
                _logger.info(f"UPDATE: Buscando hijo con name='{contact_data.get('name')}' y parent_id={parent_id}")
                existing = partner_env.search([
                    ('name', '=', contact_data.get('name')),
                    ('parent_id', '=', parent_id)
                ], limit=1)
            else:
                _logger.info(f"UPDATE: Buscando padre con id_secondary='{id_secondary}'")
                existing = partner_env.search([
                    ('id_secondary', '=', id_secondary),
                    ('parent_id', '=', False)
                ], limit=1)

            if not existing:
                return self._create_response({'status': 'error', 'message': 'Contact not found'}, 404)

            # Para PATCH, solo actualizamos lo que viene en el JSON
            update_vals = {
                'is_company': is_company,
                'parent_id': parent_id,
                'type': addr_type,
                'u_is_sap_client': True,
                'id_secondary': id_secondary,
            }

            fields_to_map = {
                'name': 'name',
                'email': 'email',
                'phone': 'phone',
                'street': 'street',
                'street2': 'street2',
                'zip': 'zip',
                'city': 'city',
                'vat': 'vat',
                'ref': 'ref',
                'job_position': 'function',
                'colony_name': 'l10n_mx_edi_colony',
                'u_entrega_lunes': 'u_entrega_lunes',
                'u_entrega_martes': 'u_entrega_martes',
                'u_entrega_miercoles': 'u_entrega_miercoles',
                'u_entrega_jueves': 'u_entrega_jueves',
                'u_entrega_viernes': 'u_entrega_viernes',
                'u_entrega_sabado': 'u_entrega_sabado',
                'u_entrega_domingo': 'u_entrega_domingo',
                'u_hora_entrega_inicio': 'u_hora_entrega_inicio',
                'u_hora_entrega_fin': 'u_hora_entrega_fin',
                'u_estatus_cliente': 'u_estatus_cliente',
                'u_dias_revision': 'u_dias_revision',
                'credit_limit': 'u_sap_credit_limit',
                'credit_balance': 'u_sap_credit_balance',
                'credit_available': 'u_sap_credit_available',
                'use_partner_credit_limit': 'u_sap_use_credit_limit',
                'l10n_mx_edi_usage': 'l10n_mx_edi_usage',
                'l10n_mx_edi_fiscal_regime': 'l10n_mx_edi_fiscal_regime',
            }

            for json_key, odoo_key in fields_to_map.items():
                if json_key in contact_data:
                    value = contact_data[json_key]
                    if json_key in ['credit_limit', 'credit_balance', 'credit_available']:
                        value = float(value or 0.0)
                    elif json_key == 'use_partner_credit_limit':
                        value = bool(value)
                    update_vals[odoo_key] = value

            # Country, State IDs
            if 'country_id' in contact_data and contact_data.get('country_id'):
                update_vals['country_id'] = int(contact_data.get('country_id'))

            if 'state_id' in contact_data and contact_data.get('state_id'):
                update_vals['state_id'] = int(contact_data.get('state_id'))

            # Vendedor por salesPersonCode
            if 'salesPersonCode' in contact_data:
                sales_person_code = contact_data.get('salesPersonCode')
                if sales_person_code:
                    try:
                        user = request.env['res.users'].sudo().search([
                            ('sap_sales_person_code', '=', int(sales_person_code))
                        ], limit=1)

                        if user and len(user) == 1:
                            update_vals['user_id'] = user.id
                            _logger.info("  👤 Vendedor asignado: %s (código SAP: %s)", user.name, sales_person_code)
                        elif len(user) > 1:
                            _logger.warning("  ⚠️ Múltiples usuarios con sap_sales_person_code=%s, se omite", sales_person_code)
                        else:
                            _logger.warning("  ⚠️ No se encontró usuario con sap_sales_person_code=%s", sales_person_code)
                    except (ValueError, TypeError) as e:
                        _logger.warning("  ⚠️ salesPersonCode inválido '%s': %s", sales_person_code, str(e))

            # Localidad
            if 'locality_name' in contact_data:
                loc_name = contact_data.get('locality_name')
                if loc_name:
                    loc = request.env['l10n_mx_edi.res.locality'].sudo().search([('name', 'ilike', loc_name)], limit=1)
                    if loc:
                        update_vals['l10n_mx_edi_locality_id'] = loc.id

            # Término de pago por código SAP
            payment_term = False
            sap_code = False
            if contact_data.get('l10n_mx_edi_payment_method_id'):
                sap_code = str(contact_data.get('l10n_mx_edi_payment_method_id'))
                _logger.info("================================================================================")
                _logger.info("PROCESANDO l10n_mx_edi_payment_method_id (UPDATE)")
                _logger.info("  - sap_code recibido (convertido a str): %s", sap_code)

                payment_term = request.env['account.payment.term'].sudo().search(
                    [('sap_payment_term_code', '=', sap_code)],
                    limit=1
                )

                if payment_term:
                    _logger.info("  - payment_term ENCONTRADO: id=%s | name=%s | sap_code=%s",
                                 payment_term.id, payment_term.name, payment_term.sap_payment_term_code)
                else:
                    _logger.warning("  - NO se encontró account.payment.term con sap_payment_term_code='%s'", sap_code)

                _logger.info("================================================================================")
            else:
                _logger.info("  - l10n_mx_edi_payment_method_id NO viene en el payload, se omite término de pago")

            # Escribir campos normales (SIN property_payment_term_id aquí)
            _logger.info(">>> EJECUTANDO write(update_vals) campos normales")
            existing.with_context(l10n_mx_edi_force_validate_vat=False).write(update_vals)
            _logger.info(">>> write(update_vals) completado")

            # Escribir términos de pago con contexto de compañía
            # Escribir términos de pago con with_company (Odoo 17+)
            if payment_term:
                # Obtener compañía válida — desde el contacto, o la primera disponible
                company = existing.company_id or request.env['res.company'].sudo().search([], limit=1)
                _logger.info("================================================================================")
                _logger.info("ESCRIBIENDO TÉRMINOS DE PAGO CON with_company (UPDATE)")
                _logger.info("  - existing.id: %s", existing.id)
                _logger.info("  - company: id=%s | name=%s", company.id, company.name)
                _logger.info("  - sap_code: %s | payment_term.id: %s", sap_code, payment_term.id)
            
                # 1. Guardar código SAP en campo auxiliar (Char)
                existing.with_company(company).write({
                    'x_studio_terminos_pago_sap_auxiliar': sap_code,
                })
                _logger.info("  - PASO 1 OK: x_studio_terminos_pago_sap_auxiliar = '%s'", sap_code)
            
                # 2. Escribir property_payment_term_id con with_company
                existing.with_company(company).write({
                    'property_payment_term_id': payment_term.id,
                })
            
                # Verificar
                existing.invalidate_recordset()
                valor_property = existing.with_company(company).property_payment_term_id
                _logger.info("  - VERIFICACION property_payment_term_id: id=%s | name=%s",
                             valor_property.id if valor_property else 'VACIO',
                             valor_property.name if valor_property else 'VACIO')
            
                if valor_property and valor_property.id == payment_term.id:
                    _logger.info("  - ✅ ÉXITO: property_payment_term_id escrito correctamente")
                else:
                    _logger.warning("  - ⚠️ FALLO: property_payment_term_id NO quedó con el valor esperado")
            
                _logger.info("================================================================================")

            return self._create_response({
                'status': 'success',
                'contact_id': existing.id,
                'type_applied': addr_type,
                'is_company': is_company,
                'parent_id': parent_id,
                'is_child': bool(parent_id)
            }, 200)

        except Exception as e:
            _logger.error(f"Error en update_contact: {str(e)}", exc_info=True)
            return self._create_response({"status": "error", "message": str(e)}, 500)
