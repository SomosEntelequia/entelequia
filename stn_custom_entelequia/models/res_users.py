# -*- coding: utf-8 -*-
from odoo import models, fields

class ResUsers(models.Model):
    _inherit = "res.users"

    sap_sales_person_code = fields.Integer(
        string='Código de Vendedor SAP',
        help='Código del vendedor en SAP (salesPersonCode)'
    )