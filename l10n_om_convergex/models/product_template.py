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
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    """ Extends product template to hold Oman HS code (IBT-158) and ISIC code (BTOM-033)
    for Oman e-invoicing compliance. """
    _inherit = 'product.template'

    l10n_om_hs_code = fields.Char(
        string="Oman HS Code",
        size=12,
        copy=False,
        help="12-digit Oman Harmonized System code (IBT-158) mandatory for B2B Goods lines.",
    )
    l10n_om_isic_code = fields.Char(
        string="Oman ISIC Code",
        size=6,
        copy=False,
        help="6-digit Oman Industrial Classification Code (BTOM-033). Overrides the company default if set.",
    )

    @api.constrains('l10n_om_hs_code')
    def _check_l10n_om_hs_code(self):
        """ Ensure the Oman HS Code is exactly 12 numeric digits (IBT-158). """
        for product in self:
            if product.l10n_om_hs_code:
                code = product.l10n_om_hs_code.strip()
                if not (code.isdigit() and len(code) == 12):
                    raise ValidationError(_(
                        "Oman HS Code must be exactly 12 digits for product '%s'.", product.display_name
                    ))

    @api.constrains('l10n_om_isic_code')
    def _check_l10n_om_isic_code(self):
        """ Ensure the Oman ISIC Code is exactly 6 numeric digits (BTOM-033). """
        for product in self:
            if product.l10n_om_isic_code:
                code = product.l10n_om_isic_code.strip()
                if not (code.isdigit() and len(code) == 6):
                    raise ValidationError(_(
                        "Oman ISIC Code must be exactly 6 digits for product '%s'.", product.display_name
                    ))
