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
import re
import uuid

from odoo import fields, models
from odoo.exceptions import UserError

_check_vat_om_re = re.compile(r"^OM\d{10}$")


class ResPartner(models.Model):
    """ Tracks whether this partner has been synced to ConvergeX's Customer Master, and its last
    known PEPPOL network status there. """
    _inherit = 'res.partner'

    l10n_om_convergex_erp_uuid = fields.Char(
        string="ConvergeX ERP UUID", copy=False,
        help="The erp_uuid this partner is synced to ConvergeX's Customer Master under - this "
             "module uses the partner's own database id, converted to text.",
    )

    def check_vat_om(self, vat):
        """ Format-only check: 'OM' followed by 10 digits.

        Wired into base_vat's country-specific check_vat_<code> mechanism, so a bad Oman VAT is
        caught when the customer is saved in Odoo, rather than only surfacing later when ConvergeX
        rejects it at submission (their own validator enforces this exact same format, IBR-003-OM).
        """
        return bool(_check_vat_om_re.match(vat))

    def _l10n_om_convergex_recover_erp_uuid(self, client):
        """ Recover this partner's real erp_uuid from ConvergeX directly, since `sync_customer`
        reported its customer_name as already existing there.

        ConvergeX enforces customer_name uniqueness case-insensitively across the whole account,
        not per erp_uuid - so this can happen even when *this* partner has never been synced
        successfully before, if some other previously-synced record (possibly a stale leftover
        from earlier testing, or a different partner renamed to the same name) already holds it.

        Only adopts the match if its erp_uuid is itself UUID-shaped: a colliding record left over
        from before this format was enforced (e.g. a bare database id) can't be adopted here, since
        `create_invoice`'s own validator would then reject it - that case is left to the caller to
        report clearly rather than silently accepting a value that would only fail differently
        one step later.

        :return: True if a usable erp_uuid was recovered and saved, False otherwise.
        :rtype: bool
        """
        self.ensure_one()
        partner = self.commercial_partner_id
        try:
            customers = client.list_customers().get('results') or []
        except UserError:
            return False
        target = (partner.name or '').strip().casefold()
        for customer in customers:
            if (customer.get('customer_name') or '').strip().casefold() != target:
                continue
            candidate = customer.get('erp_uuid')
            if isinstance(candidate, str):
                try:
                    uuid.UUID(candidate)
                except ValueError:
                    return False
                partner.l10n_om_convergex_erp_uuid = candidate
                return True
            return False
        return False

    def _l10n_om_convergex_get_customer_payload(self):
        """ Build the Customer Master sync payload ConvergeX expects for this partner (the invoice
        buyer), from whatever Odoo already has on the commercial partner.

        ConvergeX's own Customer Master sync docs say `erp_uuid` can be any string (their example
        is "ERP-CUST-0001") - but the *create invoice* endpoint's live validator rejects
        `customer_erp_uuid` values that aren't actually UUID-shaped. To satisfy both, a real UUID4
        is generated and persisted here the first time a partner is synced, rather than using the
        partner's own (non-UUID) database id.
        """
        self.ensure_one()
        partner = self.commercial_partner_id
        existing = partner.l10n_om_convergex_erp_uuid
        is_valid_uuid = False
        if isinstance(existing, str):
            try:
                uuid.UUID(existing)
                is_valid_uuid = True
            except ValueError:
                pass
        if not is_valid_uuid:
            # Empty, or a leftover non-UUID value from before this validation existed (e.g. the
            # partner's own database id) - either way, replace it with a real UUID4.
            partner.l10n_om_convergex_erp_uuid = str(uuid.uuid4())
        # 'l10n_om_cr_number' (the Oman CR Number) is only present when 'l10n_om_edi' is also
        # installed - this module doesn't depend on it, so fall back to the VAT number when absent.
        cr_number = getattr(partner, 'l10n_om_cr_number', False)
        return {
            'erp_uuid': partner.l10n_om_convergex_erp_uuid,
            'customer_name': partner.name,
            'tax_id': partner.vat or '',
            'registration_number': cr_number or partner.vat or '',
            'email': partner.email or '',
            'phone': partner.phone or '',
            'website': partner.website or '',
            'address_line1': partner.street or '',
            'address_line2': partner.street2 or '',
            'city': partner.city or '',
            'postal_code': partner.zip or '',
            'country': partner.country_id.name or '',
            'country_code': partner.country_id.code or '',
            'endpoint_scheme': '0248',
            'endpoint_id': partner.vat or '',
            'is_active': True,
        }
