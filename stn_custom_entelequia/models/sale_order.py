# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # --- CAMPOS DE CONTROL SAP ---
    x_payload_printed = fields.Boolean(string="Sincronizado SAP", copy=False)
    u_sap_id = fields.Integer(
        string="ID de SAP (DocEntry)", readonly=True, copy=False)
    u_sap_doc_num = fields.Char(
        string="Número de Folio SAP", readonly=True, copy=False)
    u_sap_notes = fields.Text(string="Notas para SAP")

    # Nuevos campos para folios de documentos SAP
    u_sap_invoice_num = fields.Html(string="Folios Facturas SAP", copy=False)
    u_sap_delivery_num = fields.Html(string="Folios Entregas SAP", copy=False)
    u_sap_credit_note_num = fields.Html(
        string="Folios Notas de Crédito SAP", copy=False)
    u_sap_folio_devolucion = fields.Html(string="Folio de devolusion")

    # --- CAMPOS DE LOGÍSTICA Y TIPOS (ÍNDICES SAP) ---
    u_cond_entrega = fields.Selection([
        ('0', 'Se va en ruta'),
        ('1', 'Por Paqueteria'),
        ('2', 'En Tienda')
    ], string="Condición de Entrega", default='0')

    u_form_envio = fields.Selection([
        ('0', 'Tienda CDMX'),
        ('1', 'Transporte Experto'),
        ('2', 'Paqueteria - Fedex'),
        ('3', 'Paqueteria - 3 guerras'),
        ('4', 'Estafeta'),
        ('6', 'TIENDA CDMX'),
        ('8', 'TRANSPORTE EXTERNO'),
        ('9', 'Ruta Sur'),
        ('10', 'Ruta Norte'),
        ('11', 'Tres Guerras'),
        ('12', 'Ruta Toluca'),
        ('13', 'Ruta Centro'),
        ('14', 'Ruta Tienda Polanco'),
        ('15', 'Ruta Tienda Roma'),
        ('16', 'Ruta Entrada Cdmx'),
        ('17', 'Fedex Estafeta'),
        ('18', 'Ruta con Cita'),
        ('19', 'Tres Guerras')
    ], string="Forma de Envío", default='0')

    u_tipo_pedido = fields.Selection([
        ('0', 'Entrega En Tienda'),
        ('1', 'Programado Institucional'),
        ('2', 'Programado Estándar')
    ], string="Tipo de Pedido", default='0')

    u_tipo_envio = fields.Selection([
        ('0', 'Urgente'),
        ('1', 'Normal')
    ], string="Tipo de Envío", default='1')

    u_tipo_devolucion = fields.Selection([
        ('0', 'Total'),
        ('1', 'Parcial')
    ], string="Tipo de Devolución")

    u_devolucion = fields.Selection([
        ('0', 'Error en cotización'),
        ('1', 'Calidad de Impresión'),
        ('2', 'Calidad Producto'),
        ('3', 'Producto Incompleto'),
        ('4', 'Error de Surtido de Producto')
    ], string="Motivo de Devolución")

    u_cancelacion = fields.Selection([
        ('0', 'Devolucion Producto'),
        ('1', 'Error en Facturación'),
        ('2', 'Datos del Cliente incorrectos'),
        ('3', 'Solicitud de cambio datos por Cliente.')
    ], string="Motivo de Cancelación")

    # --- OTROS CAMPOS ---
    u_zona = fields.Char(string="Zona")
    u_referencia_pago = fields.Char(string="Referencia de Pago")
    u_numRef = fields.Char(string="Número de Referencia")

    # --- ESTADO SAP ---
    u_estado = fields.Selection([
        ('0', 'Nuevo'),
        ('1', 'Facturado'),
        ('2', 'Entregado'),
        ('3', 'Cancelado'),
        ('5', 'Devuelto Total'),
        ('6', 'Devuelto Parcial')
    ], string="Estado SAP", default='0', copy=False)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    line_warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Almacén (línea)",
        help="Almacén específico para esta línea. "
            "Si no se define, se usará el almacén de la orden."
    )

    @api.onchange("line_warehouse_id")
    def _onchange_line_warehouse_id(self):
        for line in self:
            if line.line_warehouse_id:
                line.warehouse_id = line.line_warehouse_id
            elif line.order_id:
                line.warehouse_id = line.order_id.warehouse_id

    @api.onchange("order_id")
    def _onchange_order_id_warehouse(self):
        for line in self:
            if not line.line_warehouse_id and line.order_id:
                line.warehouse_id = line.order_id.warehouse_id
