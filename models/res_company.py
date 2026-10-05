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
from odoo.addons.l10n_om_convergex.lib.convergex_client import ConvergeXClient


class ResCompany(models.Model):
    """ Stores this company's ConvergeX API credentials and exposes the single seam
    (`_l10n_om_convergex_get_client`) the connector is created through. """
    _inherit = 'res.company'

    l10n_om_convergex_base_url = fields.Char(string="ConvergeX API Base URL", default="https://convergex.biz")
    l10n_om_convergex_client_id = fields.Char(string="ConvergeX Client ID")
    l10n_om_convergex_client_secret = fields.Char(string="ConvergeX Client Secret", groups='base.group_system')
    l10n_om_convergex_invoice_type_uuid = fields.Char(
        string="ConvergeX Standard Invoice Type UUID",
        default="92a163ea-b2ba-40b8-8ae1-670edfd975e4",
        help="ConvergeX requires a valid, active invoice_type UUID on every create call - it is "
             "not optional in practice, despite their own Postman examples suggesting otherwise. "
             "The default here is ConvergeX's documented 'Standard' type; confirm it against your "
             "own account's GET /api/customer/invoice-types/ if invoice creation still fails with "
             "an invalid-UUID error.",
    )
    l10n_om_convergex_credit_note_type_uuid = fields.Char(
        string="ConvergeX Credit Note Type UUID",
        default="42596eac-a3b6-40b3-bfbf-67a008b2fc6b",
        help="Same as the Standard Invoice Type UUID above, but for credit notes. ConvergeX's "
             "documented default is their 'Credit Note (OTA)' type.",
    )
    l10n_om_default_isic_code = fields.Char(
        string="Default Oman ISIC Code",
        size=6,
        help="6-digit Oman Industrial Classification Code (BTOM-033) for economic activity.",
    )

    @api.constrains('l10n_om_default_isic_code')
    def _check_l10n_om_default_isic_code(self):
        """ Ensure the Default Oman ISIC Code is exactly 6 numeric digits (BTOM-033). """
        for company in self:
            if company.l10n_om_default_isic_code:
                code = company.l10n_om_default_isic_code.strip()
                if not (code.isdigit() and len(code) == 6):
                    raise ValidationError(_(
                        "Default Oman ISIC Code must be exactly 6 digits."
                    ))


    def _l10n_om_convergex_get_client(self):
        """ Return a `ConvergeXClient` configured with this company's credentials. """
        self.ensure_one()
        return ConvergeXClient(
            base_url=self.l10n_om_convergex_base_url,
            client_id=self.l10n_om_convergex_client_id,
            client_secret=self.l10n_om_convergex_client_secret,
        )
