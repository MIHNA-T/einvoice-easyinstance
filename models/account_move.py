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
from odoo.exceptions import UserError


class AccountMove(models.Model):
    """ Adds the "Submit to ConvergeX" action/smart button. """
    _inherit = 'account.move'

    l10n_om_convergex_document_ids = fields.One2many(
        comodel_name='l10n.om.convergex.document', inverse_name='move_id', string="ConvergeX Documents")
    l10n_om_convergex_document_count = fields.Integer(compute='_compute_l10n_om_convergex_document_count')
    l10n_om_convergex_state = fields.Selection(
        related='l10n_om_convergex_document_ids.state', string="ConvergeX Status")

    @api.depends('l10n_om_convergex_document_ids')
    def _compute_l10n_om_convergex_document_count(self):
        """ Count this move's ConvergeX documents, for the smart button's visibility/badge. """
        for move in self:
            move.l10n_om_convergex_document_count = len(move.l10n_om_convergex_document_ids)

    def _l10n_om_convergex_get_or_create_document(self):
        """ Return this move's active (not rejected) ConvergeX document, creating one if none
        exists yet. """
        self.ensure_one()
        document = self.l10n_om_convergex_document_ids.filtered(lambda d: d.state != 'rejected')[:1]
        if not document:
            document = self.env['l10n.om.convergex.document'].create({
                'move_id': self.id,
                'company_id': self.company_id.id,
            })
        return document

    def action_l10n_om_convergex_submit(self):
        """ Submit this move to ConvergeX.

        Checks credentials are configured *before* creating a document or making any API call, and
        raises immediately if not - Odoo shows a UserError raised from a button action as a
        blocking popup right away, which is a much clearer signal than creating a document, letting
        the whole submit flow fail, and burying the same message in that document's Error field.
        """
        for move in self:
            company = move.company_id
            if not (company.l10n_om_convergex_client_id and company.l10n_om_convergex_client_secret):
                raise UserError(_(
                    "No ConvergeX Client ID/Client Secret is configured for %(company)s. Please "
                    "enter your credentials in Settings > Accounting > ConvergeX before submitting.",
                    company=company.display_name,
                ))
            document = move._l10n_om_convergex_get_or_create_document()
            document._action_submit()

    def action_l10n_om_convergex_view_documents(self):
        """ Open this move's ConvergeX documents (the smart button action). """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "ConvergeX Documents",
            'res_model': 'l10n.om.convergex.document',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
        }
