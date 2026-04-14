# STONES - Stock por línea en venta

## Qué hace
Agrega 3 campos calculados **no almacenados** en `sale.order.line`:

- `stn_existencia` → etiqueta **Existencia**
- `stn_comprometido` → etiqueta **Comprometido**
- `stn_disponible_para_uso` → etiqueta **Disponible para uso**

Los valores se calculan por línea tomando:

- el producto seleccionado (`product_id` o, si aún no existe, las variantes de `product_template_id`)
- el almacén de la línea `line_warehouse_id`
- si la línea no tiene almacén, usa `order_id.warehouse_id`

## Regla de cálculo
Se buscan `stock.quant` dentro de las ubicaciones internas hijas del almacén elegido:

- **Existencia** = suma de `inventory_quantity_auto_apply`
- **Comprometido** = suma de `pronosticado_sap`
- **Disponible para uso** = `Existencia - Comprometido`

## Supuestos importantes
Este módulo asume que en tu base ya existen estos campos:

1. `sale.order.line.line_warehouse_id` (Many2one a `stock.warehouse`)
2. `stock.quant.pronosticado_sap` (numérico)

## Instalación
1. Sube la carpeta del módulo a tu repositorio de Odoo.sh.
2. Actualiza la lista de aplicaciones.
3. Instala el módulo **STONES - Stock por línea en venta**.

## Nota funcional
El módulo sigue exactamente el mapeo pedido por el usuario:

- existencia desde `inventory_quantity_auto_apply`
- comprometido desde `pronosticado_sap`

Si después quieres cambiar **Existencia** para que use cantidad en mano real (`quantity` o `qty_available`) también se puede ajustar.
