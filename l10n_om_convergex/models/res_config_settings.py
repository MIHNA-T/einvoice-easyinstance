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


class ResConfigSettings(models.TransientModel):
    """ Exposes the company's ConvergeX credentials on the Accounting settings screen. """
    _inherit = 'res.config.settings'

    l10n_om_convergex_base_url = fields.Char(related='company_id.l10n_om_convergex_base_url', readonly=False)
    l10n_om_convergex_client_id = fields.Char(related='company_id.l10n_om_convergex_client_id', readonly=False)
    l10n_om_convergex_client_secret = fields.Char(related='company_id.l10n_om_convergex_client_secret', readonly=False)
    l10n_om_convergex_invoice_type_uuid = fields.Char(related='company_id.l10n_om_convergex_invoice_type_uuid',
                                                      readonly=False)
    l10n_om_convergex_credit_note_type_uuid = fields.Char(related='company_id.l10n_om_convergex_credit_note_type_uuid',
                                                          readonly=False)
    l10n_om_default_isic_code = fields.Char(
        related='company_id.l10n_om_default_isic_code',
        readonly=False,
        size=6,
    )

    @api.constrains('l10n_om_default_isic_code')
    def _check_l10n_om_default_isic_code(self):
        """ Ensure the Default Oman ISIC Code is exactly 6 numeric digits (BTOM-033). """
        for setting in self:
            if setting.l10n_om_default_isic_code:
                code = setting.l10n_om_default_isic_code.strip()
                if not (code.isdigit() and len(code) == 6):
                    raise ValidationError(_(
                        "Default Oman ISIC Code must be exactly 6 digits."
                    ))


    def action_l10n_om_convergex_test_connection(self):
        """ Fetch a JWT token with the currently-saved Client ID/Secret to confirm they're valid.
        Raises a clear UserError (via the client's shared request handling) on failure; on success,
        shows a plain confirmation - no invoice or customer data is touched either way. """
        self.company_id._l10n_om_convergex_get_client().test_connection()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Connection successful"),
                'message': _("ConvergeX accepted the configured Client ID and Client Secret."),
                'type': 'success',
                'sticky': False,
            },
        }
