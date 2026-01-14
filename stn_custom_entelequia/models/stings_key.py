# -*- coding: utf-8 -*-
from odoo import models, fields

class StingsKey(models.Model):
    _name = 'stings.key'
    _description = 'API Keys de conexión'

    name = fields.Char(string="Nombre", required=True)
    key = fields.Char(string="API Key", required=True)
    secret_key = fields.Char(string="SecretKey", required=True)
    active = fields.Boolean(default=True)
    notes = fields.Text(string="Notas")
