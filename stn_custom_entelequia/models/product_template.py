# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = "product.template"

    id_secundario_sap = fields.Char(
        string="ID Secundario SAP",
        help="Identificador único del producto proveniente de SAP."
    )
    grupo_de_unidad_de_medida_sap = fields.Char(
        string="Grupo de unidad de medida",
        help="Grupo de unidad de medida"
    )