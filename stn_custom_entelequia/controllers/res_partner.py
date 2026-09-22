# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID
from odoo.http import request, Response
from markupsafe import Markup
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

    # =========================================================================
    # CONVERSIÓN: código SAP → account.payment.term
    # =========================================================================
    def _resolve_payment_term(self, contact_data):
        """
        El payload manda en 'property_payment_term_id' el CÓDIGO SAP del término
        de pago (ej. 22), NO el ID de Odoo. Se busca en account.payment.term por
        el campo sap_payment_term_code.

        Devuelve (term | None, nota_para_chatter | None):
          - No viene la llave        → (None, None)          no se toca el campo
          - Viene vacía / null       → (None, nota)          no se toca el campo
          - Código sin coincidencia  → (None, nota)          no se toca el campo
          - Código encontrado        → (term, nota)          se asigna term.id
        """
        if 'property_payment_term_id' not in contact_data:
            return None, None

        raw = contact_data.get('property_payment_term_id')
        if raw in (None, '', False):
            _logger.warning(f"   ⚠️ Código SAP de término de pago vacío: {raw!r}")
            return None, f"Código SAP de término de pago vacío ({raw!r}); no se modificó."

        # Se busca como texto: funciona si sap_payment_term_code es Char o Integer
        code = str(raw).strip()
        term = request.env['account.payment.term'].sudo().search([
            ('sap_payment_term_code', '=', code)
        ], limit=1)

        if not term:
            _logger.warning(f"   ⚠️ No existe término de pago con sap_payment_term_code={code}")
            return None, f"Código SAP {code} sin término de pago asociado en Odoo; no se modificó."

        _logger.info(f"   💳 Término de pago: código SAP {code} → {term.display_name} (id={term.id})")
        return term, f"Código SAP de término de pago {code} → {term.display_name}"

    # =========================================================================
    # CHATTER: snapshot de valores y publicación de cambios
    # =========================================================================
    def _snapshot(self, partner, field_names):
        """Foto legible de los valores actuales de los campos indicados."""
        snap = {}
        for fname in field_names:
            field = partner._fields.get(fname)
            if not field:
                continue
            val = partner[fname]
            if field.type == 'many2one':
                snap[fname] = val.display_name or ''
            elif field.type == 'selection':
                snap[fname] = dict(field._description_selection(partner.env)).get(val, val or '')
            elif field.type == 'boolean':
                snap[fname] = 'Sí' if val else 'No'
            else:
                snap[fname] = '' if val in (False, None) else str(val)
        return snap

    def _post_update_chatter(self, partner, before, after, origen, notas=None):
        """Publica en el chatter los cambios recibidos por API."""
        try:
            rows = []
            for fname, old in before.items():
                new = after.get(fname, '')
                if old != new:
                    label = partner._fields[fname].string
                    rows.append(
                        Markup("<li><b>%s</b>: %s → %s</li>") % (label, old or '—', new or '—')
                    )

            body = Markup("<p><b>Actualización vía API SAP</b> (%s)</p>") % origen
            if rows:
                body += Markup("<ul>%s</ul>") % Markup('').join(rows)
            else:
                body += Markup("<p>Sin cambios en los valores.</p>")

            # Notas de conversión (ej. código SAP → término de pago)
            for nota in (notas or []):
                if nota:
                    body += Markup("<p><small>%s</small></p>") % nota

            partner.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except Exception as e:
            # El chatter nunca debe tumbar la sincronización
            _logger.warning(f"⚠️ No se pudo publicar en chatter del partner {partner.id}: {e}")

    # =========================================================================
    # LÓGICA DE TIPO Y JERARQUÍA
    # =========================================================================
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

        _logger.info("=" * 80)
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
        _logger.info("=" * 80)

        return is_company_val, final_parent_id, address_type

    # =========================================================================
    # POST /api/create_contact
    # =========================================================================
    @http.route('/api/create_contact', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def create_contact(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        try:
            data = json.loads(request.httprequest.data)
            contact_data = data.get('contact_data', {})
            id_secondary = contact_data.get('id_secondary')

            _logger.info("\n" + "#" * 100)
            _logger.info("### API CREATE_CONTACT LLAMADA ###")
            _logger.info(f"### id_secondary: {id_secondary}")
            _logger.info(f"### name: {contact_data.get('name')}")
            _logger.info(f"### company_type: {contact_data.get('company_type')}")
            _logger.info(f"### parent_id: {contact_data.get('parent_id')}")
            _logger.info(f"### property_payment_term_id: {contact_data.get('property_payment_term_id')!r}")
            _logger.info("#" * 100 + "\n")

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
                # Siempre guardamos id_secondary como respaldo (tanto en padres como en hijos)
                'id_secondary': id_secondary,
                'lang': contact_data.get('lang', 'es_MX'),
            }

            # Agregar country_id si viene en el payload
            if 'country_id' in contact_data and contact_data.get('country_id'):
                vals['country_id'] = int(contact_data.get('country_id'))

            # Agregar state_id si viene en el payload
            if 'state_id' in contact_data and contact_data.get('state_id'):
                vals['state_id'] = int(contact_data.get('state_id'))

            # ✅ VALIDACIÓN PARA IDs (EVITA ERRORES)
            if 'l10n_mx_edi_payment_method_id' in contact_data and contact_data.get('l10n_mx_edi_payment_method_id'):
                vals['l10n_mx_edi_payment_method_id'] = int(contact_data.get('l10n_mx_edi_payment_method_id'))

            # Término de pago: llega el CÓDIGO SAP, se convierte al término de Odoo
            payment_term, payment_term_note = self._resolve_payment_term(contact_data)
            if payment_term:
                vals['property_payment_term_id'] = payment_term.id

            # Buscar usuario por salesPersonCode y asignar user_id
            if 'salesPersonCode' in contact_data:
                sales_person_code = contact_data.get('salesPersonCode')
                if sales_person_code:
                    user = request.env['res.users'].sudo().search([
                        ('sap_sales_person_code', '=', int(sales_person_code))
                    ], limit=1)

                    if user:
                        vals['user_id'] = user.id
                        _logger.info(f"   👤 Vendedor asignado: {user.name} (código SAP: {sales_person_code})")
                    else:
                        _logger.warning(f"   ⚠️ No se encontró usuario con sap_sales_person_code={sales_person_code}")

            partner_env = request.env['res.partner'].sudo().with_context(l10n_mx_edi_force_validate_vat=False)

            # --- LÓGICA DE BÚSQUEDA SEGÚN JERARQUÍA ---
            existing = False

            _logger.info("\n" + "+" * 80)
            _logger.info("INICIANDO BÚSQUEDA DE CONTACTO EXISTENTE")

            if parent_id:
                # ===== ES HIJO =====
                _logger.info(f">>> RAMA: ES HIJO (parent_id={parent_id})")
                _logger.info(f">>> Buscando hijo con:")
                _logger.info(f"    - name = '{contact_data.get('name')}'")
                _logger.info(f"    - parent_id = {parent_id}")
                _logger.info(f">>> NOTA: El id_secondary '{id_secondary}' se guarda como respaldo pero NO se usa para búsqueda")

                existing = partner_env.search([
                    ('name', '=', contact_data.get('name')),
                    ('parent_id', '=', parent_id)
                ], limit=1)

                if existing:
                    _logger.info(f">>> ✓ HIJO ENCONTRADO:")
                    _logger.info(f"    - ID: {existing.id}")
                    _logger.info(f"    - Name: '{existing.name}'")
                    _logger.info(f"    - Parent: {existing.parent_id.name if existing.parent_id else 'None'}")
                    _logger.info(f"    - Type: {existing.type}")
                    _logger.info(f"    - id_secondary (respaldo): {existing.id_secondary}")
                    _logger.info(f"    >>> ACCIÓN: ACTUALIZAR HIJO")
                else:
                    _logger.info(f">>> ✗ HIJO NO ENCONTRADO")
                    _logger.info(f"    >>> ACCIÓN: CREAR NUEVO HIJO")

            else:
                # ===== ES PADRE =====
                _logger.info(f">>> RAMA: ES PADRE (parent_id=False)")
                _logger.info(f">>> Buscando padre con:")
                _logger.info(f"    - id_secondary = '{id_secondary}'")
                _logger.info(f"    - parent_id = False")

                existing = partner_env.search([
                    ('id_secondary', '=', id_secondary),
                    ('parent_id', '=', False)
                ], limit=1)

                if existing:
                    _logger.info(f">>> ✓ PADRE ENCONTRADO:")
                    _logger.info(f"    - ID: {existing.id}")
                    _logger.info(f"    - Name: '{existing.name}'")
                    _logger.info(f"    - id_secondary: {existing.id_secondary}")
                    _logger.info(f"    >>> ACCIÓN: ACTUALIZAR PADRE")
                else:
                    _logger.info(f">>> ✗ PADRE NO ENCONTRADO")
                    _logger.info(f"    >>> ACCIÓN: CREAR NUEVO PADRE")

            _logger.info("+" * 80 + "\n")

            # Crear o actualizar
            if existing:
                _logger.info(f">>> EJECUTANDO: existing.write(vals)")
                _logger.info(f">>> Contacto ID a actualizar: {existing.id}")
                before = self._snapshot(existing, vals.keys())
                existing.write(vals)
                after = self._snapshot(existing, vals.keys())
                self._post_update_chatter(
                    existing, before, after,
                    'POST /api/create_contact (contacto existente)',
                    notas=[payment_term_note],
                )
                action = "updated"
                contact_id = existing.id
            else:
                _logger.info(f">>> EJECUTANDO: partner_env.create(vals)")
                new_contact = partner_env.create(vals)
                action = "created"
                contact_id = new_contact.id
                _logger.info(f">>> Nuevo contacto creado con ID: {contact_id}")
                # Si hubo problema con el código SAP, dejarlo visible en el chatter
                if payment_term_note and not payment_term:
                    new_contact.message_post(
                        body=Markup("<p><small>%s</small></p>") % payment_term_note,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )

            _logger.info("\n" + "#" * 100)
            _logger.info("### RESULTADO FINAL ###")
            _logger.info(f"### Acción: {action}")
            _logger.info(f"### Contact ID: {contact_id}")
            _logger.info(f"### Type: {addr_type}")
            _logger.info(f"### Is Company: {is_company}")
            _logger.info(f"### Parent ID: {parent_id}")
            _logger.info("#" * 100 + "\n")

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

    # =========================================================================
    # PATCH /api/update_contact
    # =========================================================================
    @http.route('/api/update_contact', type='http', auth='none', methods=['PATCH', 'OPTIONS'], csrf=False)
    def update_contact(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._create_response({}, 200)

        try:
            data = json.loads(request.httprequest.data)
            contact_data = data.get('contact_data', {})
            id_secondary = contact_data.get('id_secondary')

            _logger.info(f"UPDATE RAW BODY: {request.httprequest.data}")
            _logger.info(
                f"UPDATE property_payment_term_id -> "
                f"{contact_data.get('property_payment_term_id', '<<NO VIENE>>')!r}"
            )

            if not id_secondary:
                return self._create_response({'status': 'error', 'message': 'Missing id_secondary'}, 400)

            # Lógica de tipo y jerarquía
            is_company, parent_id, addr_type = self._get_contact_type_logic(contact_data, id_secondary)

            # Buscar el contacto según la misma lógica que create
            partner_env = request.env['res.partner'].sudo()
            existing = False

            if parent_id:
                # ===== ES HIJO =====
                _logger.info(f"UPDATE: Buscando hijo con name='{contact_data.get('name')}' y parent_id={parent_id}")
                existing = partner_env.search([
                    ('name', '=', contact_data.get('name')),
                    ('parent_id', '=', parent_id)
                ], limit=1)
            else:
                # ===== ES PADRE =====
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
                'id_secondary': id_secondary,  # Actualizar id_secondary como respaldo
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
                'l10n_mx_edi_usage': 'l10n_mx_edi_usage',                    # Uso CFDI
                'l10n_mx_edi_fiscal_regime': 'l10n_mx_edi_fiscal_regime',    # Régimen Fiscal
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

            # Campos fiscales que son IDs
            if 'l10n_mx_edi_payment_method_id' in contact_data and contact_data.get('l10n_mx_edi_payment_method_id'):
                update_vals['l10n_mx_edi_payment_method_id'] = int(contact_data.get('l10n_mx_edi_payment_method_id'))

            # Término de pago: llega el CÓDIGO SAP, se convierte al término de Odoo
            payment_term, payment_term_note = self._resolve_payment_term(contact_data)
            if payment_term:
                update_vals['property_payment_term_id'] = payment_term.id

            if 'locality_name' in contact_data:
                loc_name = contact_data.get('locality_name')
                if loc_name:
                    loc = request.env['l10n_mx_edi.res.locality'].sudo().search([('name', 'ilike', loc_name)], limit=1)
                    if loc:
                        update_vals['l10n_mx_edi_locality_id'] = loc.id

            # Escribir y registrar en chatter
            partner_ctx = existing.with_context(l10n_mx_edi_force_validate_vat=False)
            before = self._snapshot(partner_ctx, update_vals.keys())
            partner_ctx.write(update_vals)
            after = self._snapshot(partner_ctx, update_vals.keys())
            self._post_update_chatter(
                partner_ctx, before, after,
                'PATCH /api/update_contact',
                notas=[payment_term_note],
            )

            _logger.info(
                f"UPDATE post-write: company_env={request.env.company.name} | "
                f"property_payment_term_id guardado={existing.property_payment_term_id.display_name or '—'}"
            )

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
