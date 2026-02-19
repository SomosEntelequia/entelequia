# -*- coding: utf-8 -*-
from odoo import models, fields

class AccountPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    sap_payment_term_code = fields.Char(
        string='Código SAP Payment Term', 
        help='Código correspondiente en SAP para este término de pago'
    )