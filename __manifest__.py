# -*- coding: utf-8 -*-
{
    'name': 'Supplier KSA',
    'version': '19.0.1.0.0',
    'category': 'Operations',
    'summary': 'Merged module: Custom Invoice, Import Procurement, Partner Payment Profile, Fleet Distribution',
    'description': """
Supplier KSA
============
Merged from four modules:
* Custom Invoice Report — styled Arabic/English QWeb PDF invoice with QR support
* Import Procurement — manage import shipments, landed costs, vendor bills
* Partner Payment Profile — per-client payment plans, installments, overdue tracking
* Fleet Distribution — delivery cars, regions, trips, client deliveries, portal
    """,
    'author': 'Custom Development',
    'depends': [
        'base',
        'account',
        'base_setup',
        'purchase',
        'stock',
        'stock_landed_costs',
        'contacts',
        'mail',
        'sale_management',
        'portal',
        'website',
        'advanced_vat_invoice',
    ],
    'data': [
        # Security
        'security/supplier_ksa_security.xml',
        'security/ir.model.access.csv',
        # Sequences & data
        'data/sequences.xml',
        'data/cron.xml',
        # Partner Ledger – Account Statement button
        'data/partner_ledger_patch.xml',
        # Wizards
        'wizards/generate_installments_wizard_views.xml',
        # Views — custom invoice
        'views/account_move_views.xml',
        'views/sale_order_views.xml',
        'views/warehouse_custodian_views.xml',
        'views/supplier_dashboard_views.xml',
        'views/non_invoiced_views.xml',

        # Views — partner payment profile
        'views/partner_payment_profile_views.xml',
        'views/partner_contract_views.xml',
        'views/res_partner_views.xml',

        # Menus
        # Reports
        'report/custom_invoice_report_action.xml',
        'report/custom_invoice_report_template.xml',
        'report/account_statement_pdf_template.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'supplier_ksa/static/src/js/supplier_dashboard.js',
            'supplier_ksa/static/src/xml/supplier_dashboard.xml',
            'supplier_ksa/static/src/scss/supplier_dashboard.scss',
        ],
        'web.report_assets_pdf': [
            'supplier_ksa/static/src/css/custom_invoice_report.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
