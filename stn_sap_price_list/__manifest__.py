{
    "name": "Listas de Precio SAP (Ventas)",
    "version": "19.0.1.0.6",
    "category": "Sales",
    "summary": "Listas de precio SAP por Producto + UdM y aplicación automática en líneas de venta",
    "depends": ["sale", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/sap_price_list_views.xml",
        "views/sale_order_views.xml"
    ],
    "installable": True,
    "application": False
}
