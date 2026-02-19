Fecha: 2025-12-31
Responsable: Juan Jose Moreno
Contexto: Se implementó un override del método write() en el modelo sale.order. Se configuró la detección del cambio de estado de Cotización (draft) a Orden de Venta (sale). Al confirmarse la orden: Se construye un payload JSON completo de la orden.
Contactos y Direcciones (res.partner). Se definió una lista de campos sensibles cuyo cambio debe detonar el proceso. Se implementó lógica en el método write() del modelo res.partner. Al modificarse cualquiera de los campos definidos: Se construye un payload JSON completo del contacto. El payload se imprime en consola para revisión.

----------------------------------------------------------------------------------------------------------

