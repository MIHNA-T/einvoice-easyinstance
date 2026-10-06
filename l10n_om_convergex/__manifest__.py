# -- coding: utf-8 --
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    This program is under the terms of the Odoo Proprietary License v1.0(OPL-1)
#    It is forbidden to publish, distribute, sublicense, or sell copies of the
#    Software or modified copies of the Software.
#
#    THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NON INFRINGEMENT. IN NO EVENT SHALL
#    THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,DAMAGES OR OTHER
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,ARISING
#    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#    DEALINGS IN THE SOFTWARE.
#
###############################################################################
{
    'name': 'Oman E-Invoicing - ConvergeX',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localizations/EDI',
    'summary': "Submit Oman e-invoices and credit notes to the ConvergeX ASP platform with Peppol PINT OM compliance and Single Entry support",
    'description': """
    Oman E-Invoicing - ConvergeX
    =============================

    A standalone connector to the ConvergeX (convergex.biz) Accredited Service Provider platform for
    Oman's Fawtara e-invoicing mandate:

    * Submits customer invoices and credit notes to ConvergeX's Customer Invoice API, built directly
      from the invoice/credit note data already in Odoo.
    * Supports both Single Entry API workflow (POST /api/invoices/single_entry/create/) and the
      legacy two-step Customer Master sync workflow.
    * Aligned with Peppol PINT OM requirements:
      - 12-digit Oman HS Code (item_classification_identifier / IBT-158) for Full Tax Goods lines.
      - 6-digit Oman ISIC Code (industrial_classification_code / BTOM-033) for invoice lines.
      - UN/ECE Rec 20 unit of measure codes (unit_of_measure / IBT-130).
    * Retrieves and stores the OTA QR code, tracking number, and processed reference on each
      submission.
    * Polls ConvergeX for the latest status until an invoice is acknowledged by the Oman Tax
      Authority.

    SCOPE: this covers the core customer-invoice flow only (standard invoices and credit notes).
    ConvergeX's API also documents supplier invoices, offline/POS QR reservation, Excel bulk upload,
    and dedicated compliance/TDD-evidence endpoints - none of those are implemented here yet.
    """,
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['account', 'l10n_om', 'base_vat'],
    'data': [
        'security/ir.model.access.csv',
        'security/l10n_om_convergex_security.xml',
        'data/ir_cron.xml',
        'views/l10n_om_convergex_document_views.xml',
        'views/account_move_view.xml',
        'views/product_template_views.xml',
        'views/res_config_settings_view.xml',
    ],

    'images': ['static/description/banner.jpg'],
    'license': 'OPL-1',
    'installable': True,
    'auto_install': False,
    'application': False,
    'price': 99,
    'currency': 'EUR',
}
