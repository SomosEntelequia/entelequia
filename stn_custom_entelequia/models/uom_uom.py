# -*- coding: utf-8 -*-
from odoo import models, fields

class UomUom(models.Model):
    _inherit = 'uom.uom'

    # Campos nuevos para integración con SAP
    grupo_de_unidad_de_medida_sap = fields.Char(string='Grupo de Unidad de Medida SAP')
    cantidad_base_sap = fields.Float(string='Cantidad Base SAP', digits=(16, 4))
    cantidad_de_equivalencia = fields.Float(string='Cantidad de equivalencia SAP', digits=(16, 4))
    alt_code =fields.Char(string='Codigo BASE SAP')