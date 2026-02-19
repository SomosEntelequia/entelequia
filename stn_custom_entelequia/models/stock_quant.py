# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = "stock.quant"

    pronosticado_sap = fields.Float(
        string="Comprometido",
        help="Cantidad pronosticada enviada desde SAP para esta ubicación específica."
    )
    
    def _get_inventory_fields_create(self):
        fields = super()._get_inventory_fields_create()

        custom_fields = [
            'pronosticado_sap',           
        ]
        return fields + custom_fields