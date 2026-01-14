{
    'name': 'API integracion con SAP',
    'version': '1.0',
    'category': 'Integration',
    'summary': 'API Integration for SAP',
    'description': """
        Este módulo permite la integración con una API externa mediante claves de seguridad (API Key y Secret Key).
        Permite la creación de contactos mediante solicitudes API.
        
        Configura las claves de API necesarias para la autenticación y uso de la API.
        También incluye una vista para gestionar las claves de API dentro de Odoo.
    """,
    'author': 'Juan Jose Moreno',
    'website': 'https://www.stones.solutions', 
    'depends': ['base', 'contacts', 'product','stock','l10n_mx','uom',],
    'data': [
        'security/ir.model.access.csv',
        'views/inherit_res_partner.xml',
        'views/inherit_product_oum_form.xml',
        'views/inherit_stock_quant_editable.xml',
        'views/stings_key_views.xml',  
        'views/inherit_stock_quant_list_views.xml',
        'views/inherit_product_template.xml'
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
