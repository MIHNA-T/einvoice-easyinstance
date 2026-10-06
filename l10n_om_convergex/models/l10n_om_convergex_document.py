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
import base64
import logging
import time
from zoneinfo import ZoneInfo

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.l10n_om_convergex.lib.convergex_client import (
    BUSINESS_PROCESS_TYPE, SPECIFICATION_IDENTIFIER, TRANSACTION_TYPE_B2B, TRANSACTION_TYPE_B2C,
)

_logger = logging.getLogger(__name__)

# Oman never observes daylight saving, so this offset (UTC+4) never changes - safe to fix here
# rather than expose as a configurable field.
_OMAN_TZ = ZoneInfo('Asia/Muscat')

# ConvergeX's own sandbox has been observed responding anywhere from a few seconds to over 40s,
# and occasionally drops a connection outright on a request it still processes successfully. These
# control how many times the whole sync+create(+recover) sequence is retried within a single
# _action_submit() call before actually giving up - so a transient blip resolves itself
# automatically instead of requiring a manual "Retry Submission" click every time.
MAX_SUBMIT_ATTEMPTS = 3
SUBMIT_RETRY_DELAY = 5  # seconds between attempts

# UN/ECE Rec 20 unit codes (https://docs.peppol.eu/poac/om/pint-om/trn-invoice/codelist/UNECERec20/)
UOM_TO_UNECE_CODE = {
    'uom.product_uom_unit': 'H87',       # piece / each (preferred by Oman OTA)
    'uom.product_uom_dozen': 'DZN',
    'uom.product_uom_kgm': 'KGM',
    'uom.product_uom_gram': 'GRM',
    'uom.product_uom_day': 'DAY',
    'uom.product_uom_hour': 'HUR',
    'uom.product_uom_minute': 'MIN',
    'uom.product_uom_ton': 'TNE',
    'uom.product_uom_meter': 'MTR',
    'uom.product_uom_km': 'KMT',
    'uom.product_uom_cm': 'CMT',
    'uom.product_uom_litre': 'LTR',
    'uom.product_uom_cubic_meter': 'MTQ',
    'uom.product_uom_lb': 'LBR',
    'uom.product_uom_oz': 'ONZ',
    'uom.product_uom_inch': 'INH',
    'uom.product_uom_foot': 'FOT',
    'uom.product_uom_mile': 'SMI',
    'uom.product_uom_floz': 'OZA',
    'uom.product_uom_qt': 'QTL',
    'uom.product_uom_gal': 'GLL',
    'uom.product_uom_cubic_inch': 'INQ',
    'uom.product_uom_cubic_foot': 'FTQ',
    'uom.product_uom_square_meter': 'MTK',
    'uom.product_uom_square_foot': 'FTK',
    'uom.product_uom_yard': 'YRD',
    'uom.product_uom_millimeter': 'MMT',
    'uom.product_uom_kwh': 'KWH',
}


def _get_uom_unece_code(uom, is_service=False):
    """ Map a product UoM to its UN/ECE Rec 20 code. Defaults to 'E48' for service items,
    and 'H87' (piece) for other items. """
    if is_service:
        return 'E48'
    if uom:
        xmlid = uom.get_external_id()
        if xmlid and uom.id in xmlid:
            return UOM_TO_UNECE_CODE.get(xmlid[uom.id], 'H87')
    return 'H87'


def _get_item_type(product):
    """ BTOM-019 Goods vs Services: 'goods' (or 'G') vs 'services' (or 'SVC').
    Blank defaults to goods on ConvergeX. """
    return 'services' if product and product.type == 'service' else 'goods'


def _convergex_invoice_number(move):
    """ The invoice_number actually sent to ConvergeX for `move`.

    ConvergeX's own URL routing 404s on a literal "/" in an invoice-number path segment (used by
    both the fast by-number lookup and the compliance/TDD-report endpoints) - and Odoo's default
    sequence format always contains one (e.g. "INV/2026/00011"). Replacing it with "-" here avoids
    that bug entirely, at the cost of ConvergeX showing a slightly different-looking reference than
    Odoo's own invoice number; Odoo's own name/display is completely unaffected either way.
    """
    return (move.name or '').replace('/', '-')


def _convergex_invoice_datetime(move):
    """ The invoice_date/time actually sent to ConvergeX for `move`.

    ConvergeX's compliance validator rejects a document whose invoice_date/time is later than its
    own server's current time in Oman (Asia/Muscat) - so a fixed placeholder time (e.g. "09:00")
    would fail for any invoice dated today and submitted before that fixed time passes. Using the
    real current time here instead is always safe: for an invoice dated today it's exactly "now",
    and for one dated any earlier day the whole day has already passed regardless of which time is
    picked.
    """
    now_muscat = fields.Datetime.now().replace(tzinfo=ZoneInfo('UTC')).astimezone(_OMAN_TZ)
    return "%s %s" % (fields.Date.to_string(move.invoice_date), now_muscat.strftime('%H:%M'))



class L10nOmConvergexDocument(models.Model):
    """ Tracks the submission of one invoice/credit note to ConvergeX's Customer Invoice API.

    Unlike Flick Network's connector (see `l10n_om_edi`), ConvergeX's API takes structured JSON
    fields directly rather than a PINT OM XML file - ConvergeX generates the e-invoice, QR code, and
    OTA submission itself from that JSON, so this module never builds/sends XML.
    """
    _name = 'l10n.om.convergex.document'
    _inherit = ['mail.thread']
    _description = "ConvergeX Oman E-Invoicing Document"
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(comodel_name='res.company', required=True, readonly=True,
                                  default=lambda self: self.env.company)
    move_id = fields.Many2one(comodel_name='account.move', string="Invoice/Credit Note", required=True,
                               readonly=True, index=True, check_company=True)

    state = fields.Selection(
        string="Status",
        selection=[
            ('to_send', "To Send"),
            ('submitted', "Submitted"),
            ('ota_accepted', "Acknowledged"),
            ('rejected', "Rejected"),
            ('error', "Error"),
        ],
        default='to_send',
        copy=False,
        readonly=True,
        tracking=True,
    )
    convergex_invoice_id = fields.Char(string="ConvergeX Invoice ID", copy=False, readonly=True)
    tracking_number = fields.Char(string="Tracking Number", copy=False, readonly=True)
    processed_reference_number = fields.Char(string="Processed Reference", copy=False, readonly=True,
                                               help="The Oman Tax Authority's own reference for this "
                                                    "submission, once acknowledged.")
    convergex_status = fields.Char(string="Raw ConvergeX Status", copy=False, readonly=True,
                                    help="The literal status string last reported by ConvergeX (e.g. "
                                         "'submitted', 'ota_accepted') - kept alongside the mapped "
                                         "'Status' selection above for transparency.")
    qr_code = fields.Image(string="QR Code", copy=False, readonly=True, max_width=256, max_height=256)
    error_message = fields.Text(string="Error Message", copy=False, readonly=True)
    retry_count = fields.Integer(default=0, copy=False, readonly=True)

    @api.depends('move_id.name')
    def _compute_name(self):
        """ Use the invoice/credit note's own name as this document's display name. """
        for document in self:
            document.name = document.move_id.name or _("New")

    # -------------------------------------------------------------------------
    # Submission
    # -------------------------------------------------------------------------

    def action_retry_submission(self):
        """ Public wrapper around `_action_submit`, callable from view buttons. """
        self._action_submit()

    def _validate_before_submission(self, move, is_b2b):
        """ Validate line items and partner attributes against Oman Peppol PINT rules before sending to ConvergeX. """
        company = self.company_id
        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        if not lines:
            raise UserError(_("Invoice %s has no product lines to submit.", move.name))

        for index, line in enumerate(lines, start=1):
            product = line.product_id
            item_type = _get_item_type(product)
            hs_code = (line.l10n_om_hs_code or (product.l10n_om_hs_code if product else '') or '').strip()
            isic_code = (
                line.l10n_om_isic_code
                or (product.l10n_om_isic_code if product else '')
                or company.l10n_om_default_isic_code
                or ''
            ).strip()

            # Rule IBR-079-OM / IBR-080-OM / IBR-174-OM: Full Tax B2B Goods lines require 12-digit HS code
            if is_b2b and item_type == 'goods':
                if not hs_code:
                    raise UserError(_(
                        "Line %d ('%s'): 12-digit Oman HS Code (item_classification_identifier) is mandatory "
                        "for Goods lines on B2B / Full Tax invoices. Please set it on the invoice line or the product.",
                        index, line.name or product.name or '/'
                    ))
                if not (hs_code.isdigit() and len(hs_code) == 12):
                    raise UserError(_(
                        "Line %d ('%s'): Oman HS Code must be exactly 12 digits, found '%s'.",
                        index, line.name or product.name or '/', hs_code
                    ))

            # Rule IBR-081-OM: Full Tax lines require 6-digit ISIC code
            if is_b2b:
                if not isic_code:
                    raise UserError(_(
                        "Line %d ('%s'): 6-digit Oman ISIC Code (BTOM-033) is required for Full Tax invoices. "
                        "Please configure the Default Oman ISIC Code in Settings > Accounting > ConvergeX "
                        "or set it on the line/product.",
                        index, line.name or product.name or '/'
                    ))
                if not (isic_code.isdigit() and len(isic_code) == 6):
                    raise UserError(_(
                        "Line %d ('%s'): Oman ISIC Code must be exactly 6 digits, found '%s'.",
                        index, line.name or product.name or '/', isic_code
                    ))

    def _action_submit(self):
        """ Submit the invoice/credit note to ConvergeX, using either Single Entry or legacy two-step workflow.

        Retries the whole sequence up to MAX_SUBMIT_ATTEMPTS times on failure (see the module-level
        comment on that constant) - a genuinely persistent problem still ends in 'error' with a
        clear message; only transient blips self-heal here.
        """
        for document in self:
            move = document.move_id
            company = document.company_id
            if not (company.l10n_om_convergex_client_id and company.l10n_om_convergex_client_secret):
                raise UserError(_(
                    "No ConvergeX Client ID/Client Secret is configured for %(company)s. Please "
                    "enter your credentials in Settings > Accounting > ConvergeX before submitting.",
                    company=company.display_name,
                ))

            buyer = move.partner_id.commercial_partner_id
            is_b2b = bool(buyer.is_company)
            document._validate_before_submission(move, is_b2b)

            client = company._l10n_om_convergex_get_client()
            last_error = None
            response = None

            for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
                try:
                    try:
                        sync_response = client.sync_customer(move.partner_id._l10n_om_convergex_get_customer_payload())
                    except UserError as sync_error:
                        if not buyer._l10n_om_convergex_recover_erp_uuid(client):
                            raise
                        sync_response = client.sync_customer(move.partner_id._l10n_om_convergex_get_customer_payload())
                    customer = sync_response.get('customer') or {}
                    if customer.get('erp_uuid'):
                        buyer.l10n_om_convergex_erp_uuid = customer['erp_uuid']

                    payload = document._build_invoice_payload(client=client)
                    try:
                        response = client.create_invoice(payload)
                    except UserError as create_error:
                        try:
                            response = document._recover_existing_invoice(client)
                        except UserError:
                            raise create_error
                    last_error = None
                    break
                except UserError as e:
                    last_error = e
                    if attempt < MAX_SUBMIT_ATTEMPTS:
                        _logger.info(
                            "ConvergeX submission attempt %s/%s failed for %s, retrying: %s",
                            attempt, MAX_SUBMIT_ATTEMPTS, move.name, e,
                        )
                        time.sleep(SUBMIT_RETRY_DELAY)

            if last_error:
                document.write({'state': 'error', 'error_message': str(last_error), 'retry_count': document.retry_count + 1})
                continue

            document._write_response(response)

    def _recover_existing_invoice(self, client):
        """ Recover this document's tracking details from ConvergeX directly by invoice number,
        since `create_invoice` reported it as already existing there. Uses the fast by-number
        lookup (includes qr_code) and fetches compliance evidence to retrieve the internal invoice UUID. """
        self.ensure_one()
        move = self.move_id
        inv_number = _convergex_invoice_number(move)
        try:
            ref = client.get_references_by_number(inv_number)
            if not ref.get('id'):
                try:
                    comp = client.get_compliance_evidence(inv_number)
                    if isinstance(comp, list) and comp and comp[0].get('invoice'):
                        ref['id'] = comp[0]['invoice']
                except Exception:
                    pass
            return ref
        except UserError:
            date_str = fields.Date.to_string(move.invoice_date)
            summary = client.get_summary_by_date_range(date_str, date_str)
            for result in summary.get('results') or []:
                if result.get('invoice_number') == inv_number:
                    if not result.get('id'):
                        try:
                            comp = client.get_compliance_evidence(inv_number)
                            if isinstance(comp, list) and comp and comp[0].get('invoice'):
                                result['id'] = comp[0]['invoice']
                        except Exception:
                            pass
                    return result
            raise UserError(_(
                "ConvergeX reports invoice number '%(number)s' already exists, but it could not be "
                "recovered by either the by-number lookup or a search of its issue date "
                "(%(date)s).",
                number=inv_number, date=date_str,
            ))

    def _build_invoice_payload(self, client=None):
        """ Build the JSON body for ConvergeX invoice create endpoint from `self.move_id`.

        Includes required line-level fields: UN/ECE Rec 20 unit_of_measure,
        item_type, item_classification_identifier (Oman HS code), and industrial_classification_code (ISIC).
        """
        self.ensure_one()
        move = self.move_id
        company = self.company_id
        is_credit_note = move.move_type == 'out_refund'
        buyer = move.partner_id.commercial_partner_id
        is_b2b = bool(buyer.is_company)

        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        line_items = []
        tax_totals = {}
        for index, line in enumerate(lines, start=1):
            tax = line.tax_ids[:1]
            tax_rate = tax.amount if tax else 0.0
            product = line.product_id
            is_service = product.type == 'service' if product else False
            item_type = _get_item_type(product)
            uom_code = _get_uom_unece_code(line.product_uom_id, is_service=is_service)
            hs_code = (line.l10n_om_hs_code or (product.l10n_om_hs_code if product else '') or '').strip()
            isic_code = (
                line.l10n_om_isic_code
                or (product.l10n_om_isic_code if product else '')
                or company.l10n_om_default_isic_code
                or ''
            ).strip()

            line_dict = {
                'line_number': index,
                'item_description': line.name or product.name or '/',
                'quantity': "%.3f" % line.quantity,
                'unit_price': "%.3f" % line.price_unit,
                'tax_rate': "%.2f" % tax_rate,
                'tax_amount': "%.3f" % (line.price_total - line.price_subtotal),
                'line_total': "%.3f" % line.price_total,
                'invoice_line_identifier': str(index),
                'item_net_amount': "%.3f" % line.price_subtotal,
                'item_vat_category_code': 'S' if tax_rate else 'Z',
                'unit_of_measure': uom_code,
                'item_type': item_type,
            }
            if hs_code:
                line_dict['item_classification_identifier'] = hs_code
            if isic_code:
                line_dict['industrial_classification_code'] = isic_code

            line_items.append(line_dict)
            key = "%.2f" % tax_rate
            bucket = tax_totals.setdefault(key, {'tax_category_code': 'S' if tax_rate else 'Z',
                                                  'tax_rate': key, 'taxable_amount': 0.0, 'tax_amount': 0.0})
            bucket['taxable_amount'] += line.price_subtotal
            bucket['tax_amount'] += (line.price_total - line.price_subtotal)

        payload = {
            'invoice_type': (
                company.l10n_om_convergex_credit_note_type_uuid if is_credit_note
                else company.l10n_om_convergex_invoice_type_uuid
            ),
            'seller_trading_name': company.name,
            'seller_identifier': company.vat or company.partner_id.vat or '',
            'seller_vat_identifier': company.vat or company.partner_id.vat or '',
            'seller_address_line_1': company.street or '',
            'seller_address_line_2': company.street2 or '',
            'seller_city': company.city or '',
            'seller_postal_code': company.zip or '',
            'seller_country_code': company.country_id.code or '',
            'invoice_number': _convergex_invoice_number(move),
            'invoice_date': _convergex_invoice_datetime(move),
            'currency': move.currency_id.name,
            'customer_erp_uuid': buyer.l10n_om_convergex_erp_uuid,
            'subtotal': "%.3f" % move.amount_untaxed,
            'tax_amount': "%.3f" % move.amount_tax,
            'total_amount': "%.3f" % move.amount_total,
            'compliance_profile': 'credit_note' if is_credit_note else 'standard',
            'document_side': 'customer',
            'invoice_type_code': '381' if is_credit_note else '380',
            'invoice_transaction_type': TRANSACTION_TYPE_B2B if is_b2b else TRANSACTION_TYPE_B2C,
            'specification_identifier': SPECIFICATION_IDENTIFIER,
            'business_process_type': BUSINESS_PROCESS_TYPE,
            'send_to_government': True,
            'line_items': line_items,
            'tax_details': [
                {
                    'tax_category_code': bucket['tax_category_code'],
                    'tax_rate': bucket['tax_rate'],
                    'taxable_amount': "%.3f" % bucket['taxable_amount'],
                    'tax_amount': "%.3f" % bucket['tax_amount'],
                }
                for bucket in tax_totals.values()
            ],
        }

        if is_credit_note and move.reversed_entry_id:
            preceding = move.reversed_entry_id
            preceding_document = preceding.l10n_om_convergex_document_ids[:1]
            preceding_uuid = preceding_document.convergex_invoice_id
            if not preceding_uuid:
                c = client or company._l10n_om_convergex_get_client()
                try:
                    comp = c.get_compliance_evidence(_convergex_invoice_number(preceding))
                    if isinstance(comp, list) and comp and comp[0].get('invoice'):
                        preceding_uuid = comp[0]['invoice']
                        preceding_document.convergex_invoice_id = preceding_uuid
                except Exception:
                    pass
            payload.update({
                'preceding_invoice_number': _convergex_invoice_number(preceding),
                'preceding_invoice_issue_date': fields.Date.to_string(preceding.invoice_date),
                'preceding_invoice_uuid': preceding_uuid or '',
                'credit_debit_note_reason_code': 'Correction',
            })

        return payload


    def _write_response(self, response):
        """ Store a successful create-invoice response on `self`. """
        self.ensure_one()
        qr = response.get('qr_code') or response.get('oman_qr') or {}
        image_data_url = qr.get('image_data_url') or ''
        qr_binary = False
        if image_data_url.startswith('data:image'):
            try:
                qr_binary = base64.b64encode(base64.b64decode(image_data_url.split(',', 1)[1]))
            except (IndexError, ValueError):
                _logger.warning("Could not decode ConvergeX qr_code.image_data_url for %s", self.name)

        raw_status = response.get('status') or 'submitted'
        self.write({
            'state': 'ota_accepted' if raw_status == 'ota_accepted' else 'submitted',
            'convergex_status': raw_status,
            'convergex_invoice_id': response.get('id') or self.convergex_invoice_id,
            'tracking_number': response.get('tracking_number') or self.tracking_number,
            'processed_reference_number': response.get('processed_reference_number') or self.processed_reference_number,
            'qr_code': qr_binary or self.qr_code,
            'error_message': False,
        })

    # -------------------------------------------------------------------------
    # Status polling
    # -------------------------------------------------------------------------

    def _cron_poll_status(self):
        """ Poll ConvergeX for the latest status of documents still 'submitted'. Degrades to a
        no-op for companies without ConvergeX credentials configured. """
        documents = self.search([('state', '=', 'submitted'), ('tracking_number', '!=', False)])
        for company, company_documents in documents.grouped('company_id').items():
            if not (company.l10n_om_convergex_client_id and company.l10n_om_convergex_client_secret):
                continue
            client = company._l10n_om_convergex_get_client()
            for document in company_documents:
                try:
                    summary = client.get_summary_by_tracking(document.tracking_number)
                except UserError as e:
                    _logger.warning("Error polling ConvergeX status for %s: %s", document.name, e)
                    continue
                status = summary.get('status')
                if status:
                    document.write({
                        'convergex_status': status,
                        'state': 'ota_accepted' if status == 'ota_accepted' else document.state,
                        'processed_reference_number': summary.get('processed_reference_number') or document.processed_reference_number,
                    })
