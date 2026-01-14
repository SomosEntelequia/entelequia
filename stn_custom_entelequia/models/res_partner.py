# -*- coding: utf-8 -*-
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'  # Heredamos de res.partner para no crear un modelo nuevo

    id_secondary = fields.Char(string="ID Sistema Compartido", help="Este campo guarda el ID del sistema externo compartido.")
