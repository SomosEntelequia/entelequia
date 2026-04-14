from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    stn_existencia = fields.Float(
        string='Existencia',
        compute='_compute_stn_stock_snapshot',
        compute_sudo=True,
        digits='Product Unit of Measure',
        store=False,
        readonly=True,
        help='Suma de inventory_quantity_auto_apply en stock.quant para el producto y almacén seleccionados.',
    )
    stn_comprometido = fields.Float(
        string='Comprometido',
        compute='_compute_stn_stock_snapshot',
        compute_sudo=True,
        digits='Product Unit of Measure',
        store=False,
        readonly=True,
        help='Suma de pronosticado_sap en stock.quant para el producto y almacén seleccionados.',
    )
    stn_disponible_para_uso = fields.Float(
        string='Disponible para uso',
        compute='_compute_stn_stock_snapshot',
        compute_sudo=True,
        digits='Product Unit of Measure',
        store=False,
        readonly=True,
        help='Existencia menos comprometido.',
    )

    def _stn_get_target_product_ids(self):
        self.ensure_one()
        if self.product_id:
            return [self.product_id.id]

        template = self.product_template_id
        if template:
            return template.product_variant_ids.ids

        return []

    def _stn_get_target_warehouse(self):
        self.ensure_one()
        return self.line_warehouse_id or self.order_id.warehouse_id

    @api.depends(
        'product_id',
        'product_template_id',
        'line_warehouse_id',
        'order_id.warehouse_id',
        'order_id.company_id',
    )
    def _compute_stn_stock_snapshot(self):
        quant_model = self.env['stock.quant'].sudo()
        has_inventory_quantity_auto_apply = 'inventory_quantity_auto_apply' in quant_model._fields
        has_pronosticado_sap = 'pronosticado_sap' in quant_model._fields

        for line in self:
            existencia = 0.0
            comprometido = 0.0

            warehouse = line._stn_get_target_warehouse()
            product_ids = line._stn_get_target_product_ids()

            if warehouse and warehouse.view_location_id and product_ids:
                domain = [
                    ('product_id', 'in', product_ids),
                    ('location_id', 'child_of', warehouse.view_location_id.id),
                    ('location_id.usage', '=', 'internal'),
                ]

                if line.order_id.company_id:
                    domain.append(('company_id', '=', line.order_id.company_id.id))

                quants = quant_model.search(domain)

                if has_inventory_quantity_auto_apply:
                    existencia = sum(quants.mapped('inventory_quantity_auto_apply'))

                if has_pronosticado_sap:
                    comprometido = sum(quants.mapped('pronosticado_sap'))

            line.stn_existencia = existencia
            line.stn_comprometido = comprometido
            line.stn_disponible_para_uso = existencia - comprometido

    @api.onchange(
        'product_id',
        'product_template_id',
        'line_warehouse_id',
        'order_id.warehouse_id',
    )
    def _onchange_stn_stock_snapshot(self):
        self._compute_stn_stock_snapshot()
