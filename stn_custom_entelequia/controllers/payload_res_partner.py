# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    u_is_sap_client = fields.Boolean(string="Sincronizado con SAP", default=False)
    u_has_pending_changes = fields.Boolean(
        string="Tiene cambios pendientes para SAP",
        default=False
    )
    
    # Campos que se monitorean para cambios
    SAP_SYNC_FIELDS = [
        'name', 'email', 'phone', 'vat', 'ref', 'active',
        'street', 'street2', 'city', 'state_id', 'zip', 'function',
        'u_entrega_lunes', 'u_entrega_martes', 'u_entrega_miercoles',
        'u_entrega_jueves', 'u_entrega_viernes', 'u_entrega_sabado', 'u_entrega_domingo',
        'u_estatus_cliente', 'u_hora_entrega_inicio', 'u_hora_entrega_fin'
    ]

    def write(self, vals):
        """Override write para detectar cambios y marcar para actualización"""
        # Verificar si se modificó algún campo relevante
        changed_fields = set(vals.keys())
        sync_fields = set(self.SAP_SYNC_FIELDS)
        
        # Ejecutar el write normal primero
        res = super(ResPartner, self).write(vals)
        
        if changed_fields & sync_fields:
            # Si hay cambios en campos relevantes
            _logger.info(f"🔄 CAMBIOS DETECTADOS en: {changed_fields & sync_fields}")
            
            for record in self:
                if record.u_is_sap_client and record.id_secondary:
                    # Marcar cambios pendientes
                    super(ResPartner, record).write({'u_has_pending_changes': True})
                    
                    # Si es un hijo, también marcar al padre
                    if record.parent_id and record.parent_id.u_is_sap_client:
                        super(ResPartner, record.parent_id).write({'u_has_pending_changes': True})
                        _logger.info(f"  → También marcando padre '{record.parent_id.name}' con cambios pendientes")
        
        return res

    def action_sync_sap_contact(self):
        """Sincronización manual completa (botón): Padre + todos los hijos"""
        url = "http://b1.ativy.mx:22258/Sap/sync_bp"
        headers = {"X-API-KEY": "2d33fa57-0f91", "Content-Type": "application/json"}

        for record in self:
            target_parent = record.parent_id if record.parent_id else record
            
            # 1. SINCRONIZAR PADRE
            _logger.info(f"--- DISPARO SAP PADRE: {target_parent.name} ---")
            payload_parent = target_parent._build_sap_payload(mode='parent')
            resp_parent = self._send_to_sap_partner(url, payload_parent, headers)

            if resp_parent and isinstance(resp_parent, dict) and resp_parent.get('cardCode'):
                parent_code = resp_parent.get('cardCode')
                target_parent.write({'id_secondary': parent_code, 'u_is_sap_client': True})
                self.env.cr.commit() 

                # 2. SINCRONIZAR HIJOS
                for child in target_parent.child_ids:
                    _logger.info(f"--- DISPARO SAP HIJO: {child.name} ({child.type}) ---")
                    payload_child = child._build_sap_payload(mode='child')
                    if payload_child:
                        resp_child = self._send_to_sap_partner(url, payload_child, headers)
                        if resp_child and isinstance(resp_child, dict) and resp_child.get('cardCode'):
                            child.write({
                                'id_secondary': resp_child.get('cardCode'),
                                'u_is_sap_client': True
                            })
                            self.env.cr.commit()
            else:
                _logger.error(f"Error en Padre {target_parent.name}")

    def action_update_sap_contact(self):
        """Actualización manual: Actualiza el PADRE + TODOS sus hijos (actualiza existentes y crea nuevos)"""
        url = "http://b1.ativy.mx:22258/Sap/sync_bp"
        headers = {"X-API-KEY": "2d33fa57-0f91", "Content-Type": "application/json"}

        for record in self:
            # Determinar el padre (si es hijo, tomar su padre)
            target_parent = record.parent_id if record.parent_id else record
            
            # Verificar que el padre tenga id_secondary
            if not target_parent.id_secondary:
                _logger.warning(f"⚠️ {target_parent.name} no tiene id_secondary, no se puede actualizar")
                continue
            
            _logger.info(f"=== ACTUALIZACIÓN COMPLETA: {target_parent.name} ===")
            
            # 1. ACTUALIZAR PADRE
            _logger.info(f"--- ACTUALIZAR SAP PADRE: {target_parent.name} ---")
            payload_parent = target_parent._build_sap_payload(mode='parent')
            
            if payload_parent:
                resp_parent = self._send_to_sap_partner(url, payload_parent, headers)
                if resp_parent and isinstance(resp_parent, dict):
                    _logger.info(f"✅ Padre actualizado exitosamente")
                    
                    # 2. ACTUALIZAR/CREAR TODOS LOS HIJOS
                    for child in target_parent.child_ids:
                        _logger.info(f"--- SINCRONIZAR HIJO: {child.name} ({child.type}) ---")
                        payload_child = child._build_sap_payload(mode='child')
                        
                        if payload_child:
                            resp_child = self._send_to_sap_partner(url, payload_child, headers)
                            if resp_child and isinstance(resp_child, dict):
                                # Si SAP retorna un cardCode, guardarlo
                                if resp_child.get('cardCode'):
                                    child.write({
                                        'id_secondary': resp_child.get('cardCode'),
                                        'u_is_sap_client': True,
                                        'u_has_pending_changes': False
                                    })
                                else:
                                    # Aunque no retorne cardCode, marcar como sincronizado
                                    child.write({
                                        'u_is_sap_client': True,
                                        'u_has_pending_changes': False
                                    })
                                _logger.info(f"  ✅ Hijo {child.name} sincronizado")
                            else:
                                _logger.error(f"  ❌ Error al sincronizar hijo {child.name}")
                    
                    # 3. QUITAR LA MARCA DE CAMBIOS PENDIENTES DEL PADRE
                    target_parent.write({
                        'u_is_sap_client': True,
                        'u_has_pending_changes': False
                    })
                    
                    self.env.cr.commit()
                    _logger.info(f"✅ Actualización completa finalizada - Botón ocultado")
                else:
                    _logger.error(f"❌ Error en actualización del padre {target_parent.name}")

    def _build_sap_payload(self, mode='parent'):
        """Construcción de JSON para SAP enviando el nombre del registro actual en el campo address"""
        self.ensure_one()
        def to_sap_bool(val): return "1" if val in [True, '1', 'Yes', '1'] else "0"
        
        data = {}
        if mode == 'parent':
            # PADRE: Registro principal
            if self.id_secondary:
                data["id_secondary"] = self.id_secondary
            
            data.update({
                "active": self.active,
                "company_type": "company",
                "name": self.name,
                "email": self.email,
                "phone": self.phone,
                "vat": self.vat,
                "ref": self.ref,
                "entrega_lunes": to_sap_bool(self.u_entrega_lunes),
                "entrega_martes": to_sap_bool(self.u_entrega_martes),
                "entrega_miercoles": to_sap_bool(self.u_entrega_miercoles),
                "entrega_jueves": to_sap_bool(self.u_entrega_jueves),
                "entrega_viernes": to_sap_bool(self.u_entrega_viernes),
                "entrega_sabado": to_sap_bool(self.u_entrega_sabado),
                "entrega_domingo": to_sap_bool(self.u_entrega_domingo),
                "estatus_cliente": self.u_estatus_cliente,
                "hora_entrega_inicio": int(self.u_hora_entrega_inicio or 900),
                "hora_entrega_fin": int(self.u_hora_entrega_fin or 1800)
            })
            # Agregar salesPersonCode si el contacto tiene un vendedor asignado
            if self.user_id and hasattr(self.user_id, 'sap_sales_person_code') and self.user_id.sap_sales_person_code:
                data["salesPersonCode"] = self.user_id.sap_sales_person_code
                _logger.info(f"   👤 salesPersonCode enviado: {self.user_id.sap_sales_person_code}")
        else:
            # HIJO: Contactos o Direcciones
            if self.type == 'contact':
                name_parts = (self.name or "").strip().split(maxsplit=1)
                data = {
                    "company_type": "person",
                    "name": self.name,
                    "firstname": name_parts[0] if len(name_parts) > 0 else "",
                    "lastname": name_parts[1] if len(name_parts) > 1 else "",
                    "email": self.email,
                    "phone": self.phone,
                    "title": (self.function[:10] if self.function else ""),
                    "contact_address": f"{self.city or ''}, {self.street or ''}".strip(", ")
                }
                data["id_secondary"] = self.id_secondary or (self.parent_id and self.parent_id.id_secondary)
                    
            elif self.type in ['invoice', 'delivery']:
                # Mandar el nombre del contacto actual en mayúsculas
                #address_unique_id = (self.name or "").upper()
                address_unique_id = self.name 
                
                data = {
                    "company_type": "company",
                    "address": address_unique_id,
                    "address_type": "BillTo" if self.type == 'invoice' else "ShipTo",
                    "street": self.street,
                    "street2": self.street2,
                    "city": self.city,
                    #"city": self.l10n_mx_edi_locality_id,
                    "city": self.l10n_mx_edi_locality_id.with_context(lang='es_MX').name if self.l10n_mx_edi_locality_id else "",
                    "zip": self.zip,
                    "vat": self.vat or (self.parent_id.vat if self.parent_id else "")
                }
                if self.state_id:
                    data["state"] = self.state_id.code
                
                data["id_secondary"] = self.id_secondary or (self.parent_id and self.parent_id.id_secondary)
            else:
                return None

        # Limpieza: Eliminamos campos falsos/vacíos
        clean_data = {k: v for k, v in data.items() if v not in [None, "", False]}
        return {"contact_data": clean_data}

    def _send_to_sap_partner(self, url, payload, headers):
        try:
            _logger.info(f"PAYLOAD ENVIADO: {json.dumps(payload, indent=2, ensure_ascii=False)}")
            response = requests.post(url, json=payload, headers=headers, timeout=45)
            _logger.info(f"RESPONSE SAP [{response.status_code}]: {response.text}")
            if response.status_code in [200, 201]:
                return response.json()
            return False
        except Exception as e:
            _logger.error(f"Error conexión: {str(e)}")
            return False