# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    id_secondary = fields.Char(string="ID Sistema Compartido")

    # Campo de control: check que indica si ya está en SAP
    u_is_sap_client = fields.Boolean(
        string="Sincronizado con SAP", default=False)

    # Definimos la selección para reutilizarla
    OPCIONES_ENTREGA = [('Yes', 'Yes'), ('No', 'No')]

    # Días de entrega como Selección
    u_entrega_lunes = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Lunes", default='No')
    u_entrega_martes = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Martes", default='No')
    u_entrega_miercoles = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Miércoles", default='No')
    u_entrega_jueves = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Jueves", default='No')
    u_entrega_viernes = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Viernes", default='No')
    u_entrega_sabado = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Sábado", default='No')
    u_entrega_domingo = fields.Selection(
        OPCIONES_ENTREGA, string="Entrega Domingo", default='No')

    u_hora_entrega_inicio = fields.Integer(string="Hora Entrega Inicio")
    u_hora_entrega_fin = fields.Integer(string="Hora Entrega Fin")

    u_estatus_cliente = fields.Selection([
        ('0', 'Nuevo'),
        ('1', 'Recuperado'),
        ('2', 'Recompra'),
        ('3', 'Perdido')
    ], string="Estatus Cliente", default='0')

    u_dias_revision = fields.Char(string="Días de Revisión", size=15)

    # Campos de Crédito SAP
    u_sap_credit_limit = fields.Float(
        string="Límite de Crédito SAP", digits=(16, 2))
    u_sap_credit_balance = fields.Float(
        string="Saldo en SAP", digits=(16, 2), readonly=True)
    u_sap_credit_available = fields.Float(string="Crédito Disponible SAP")
    u_sap_use_credit_limit = fields.Boolean(
        string="Validar Crédito SAP", default=True)


