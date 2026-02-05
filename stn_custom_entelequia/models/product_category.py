# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    id_secundario_sap = fields.Char(string="ID SAP", index=True)