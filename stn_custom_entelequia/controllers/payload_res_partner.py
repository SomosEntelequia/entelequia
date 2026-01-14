# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    def _build_sap_payload(self):
        self.ensure_one()
        
        # Estructura según tus requerimientos
        # Se envuelve en la llave "contact_data"
        return {
            "contact_data": {
                "id_secondary": self.id_secondary or "", # CardCode en SAP
                "active": self.active,
                "company_type": self.company_type,      # 'company' o 'person'
                "name": self.name or "",
                "email": self.email or "",
                "phone": self.phone or "",
                "street": self.street or "",
                "street2": self.street2 or "",
                "city": self.city or "",
                "state": self.state_id.code if self.state_id else "",
                "zip": self.zip or "",
                "vat": self.vat or "",
                "l10n_mx_edi_usage": self.l10n_mx_edi_usage or "",
                "l10n_mx_edi_fiscal_regime": self.l10n_mx_edi_fiscal_regime or "",
                "ref": self.ref or "",               
            }
        }

    def action_sync_sap_contact(self):
        """
        Función para sincronizar manualmente o ser llamada desde otros modelos.
        Garantiza la impresión del payload antes de intentar el envío.
        """
        url = "http://b1.ativy.mx:22258/Sap/sync_bp"
        headers = {
            "X-API-KEY": "2d33fa57-0f91",
            "Content-Type": "application/json"
        }

        for partner in self:
            payload = partner._build_sap_payload()
            
            # IMPRESIÓN GARANTIZADA
            _logger.info(
                "\n================= ENVIANDO CONTACTO A SAP =================\n"
                "URL: %s\n"
                "PAYLOAD:\n%s\n"
                "============================================================",
                url, json.dumps(payload, indent=2, ensure_ascii=False)
            )

            try:
                # Usamos json=payload para que la librería maneje el encoding correctamente
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                
                if response.status_code in [200, 201]:
                    _logger.info(">>> SAP: Contacto [%s] sincronizado exitosamente.", partner.name)
                else:
                    _logger.error(">>> SAP ERROR [CONTACTO]: %s - %s", response.status_code, response.text)
                    
            except Exception as e:
                _logger.error(">>> SAP CRITICAL ERROR [CONTACTO]: %s", str(e))