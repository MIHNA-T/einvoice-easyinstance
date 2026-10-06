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
import logging
from json import JSONDecodeError

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# BTOM-001 transaction-type bit strings (20 chars, bits 1/2 mutually exclusive - CL-03-OM-1/2).
TRANSACTION_TYPE_B2B = "1" + "X" * 19
TRANSACTION_TYPE_B2C = "X1" + "X" * 18

SPECIFICATION_IDENTIFIER = "urn:peppol:pint:billing-1@om-1"
BUSINESS_PROCESS_TYPE = "urn:peppol:pint:billing"


class ConvergeXClient:
    """ Thin REST client for the ConvergeX (convergex.biz) E-Invoicing Platform API.

    Covers only the subset of ConvergeX's documented API this module actually uses: JWT auth,
    Customer Master sync, and customer-invoice create. ConvergeX's API also documents supplier
    invoices, offline/POS QR reservation, Excel bulk upload, and separate compliance/TDD-evidence
    endpoints - none of those are implemented here.

    A fresh JWT is requested on every call rather than cached/refreshed, trading a small amount of
    extra latency for simplicity - ConvergeX's own docs show the token lasting 1 hour, so caching it
    would be a reasonable later optimization, not a correctness requirement.
    """

    def __init__(self, base_url, client_id, client_secret, timeout=60):
        """ Store the credentials/config this client will use for every call - no request is made
        here; a fresh JWT is only fetched once an actual call needs one (see `_get_token`).

        :param str base_url: ConvergeX API base URL (e.g. "https://convergex.biz").
        :param str client_id: ConvergeX Client ID.
        :param str client_secret: ConvergeX Client Secret.
        :param int timeout: request timeout in seconds. Defaults to 60s, not the more typical
            ~15s: the summary-by-date-range endpoint (used for "already exists" recovery) was
            observed live taking ~44s to respond on ConvergeX's own sandbox - a shorter timeout
            here was the actual cause of repeated false "Network connectivity issue" failures,
            not a real connectivity problem.
        """
        self.base_url = (base_url or "").rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._session = requests.Session()

    # -------------------------------------------------------------------------
    # Auth
    # -------------------------------------------------------------------------

    def test_connection(self):
        """ Verify the configured Client ID/Secret actually authenticate, without touching invoice
        or customer data. ConvergeX documents no dedicated side-effect-free "verify" endpoint (unlike
        e.g. Flick Network's GET /v1/auth/verify) - fetching a JWT token IS the side-effect-free
        check: a successful token response proves the credentials are valid on its own. """
        self._get_token()
        return True

    def _get_token(self):
        """ POST /api/auth/token/ - exchange the configured Client ID/Secret for a JWT access token. """
        if not (self.client_id and self.client_secret):
            raise UserError(_(
                "No ConvergeX Client ID/Client Secret is configured. Go to Settings > Accounting > "
                "ConvergeX to enter your credentials."
            ))
        payload = self._request(
            "POST", "/api/auth/token/",
            json={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret},
            authenticated=False,
        )
        token = payload.get("access")
        if not token:
            raise UserError(_("ConvergeX did not return an access token for the configured credentials."))
        return token

    # -------------------------------------------------------------------------
    # Customer Master
    # -------------------------------------------------------------------------

    def sync_customer(self, customer_payload):
        """ POST /api/invoices/customers/erp/sync/ - create/update a Customer Master record.

        :param dict customer_payload: see ConvergeX's documented fields (erp_uuid, customer_name,
            tax_id, registration_number, address fields, endpoint_scheme/endpoint_id, ...).
        :return: the parsed response, including ``customer`` and ``peppol_lookup``.
        :rtype: dict
        """
        return self._request("POST", "/api/invoices/customers/erp/sync/", json=customer_payload)

    def list_customers(self):
        """ GET /api/invoices/customers/erp/ - list every Customer Master record already on
        ConvergeX for this account.

        Used only for "customer_name already exists" recovery: ConvergeX enforces customer_name
        uniqueness case-insensitively across the whole account, not per erp_uuid, so a sync can
        collide with an unrelated, previously-synced record sharing (a case-insensitive variant of)
        the same name. There is no documented lookup-by-name endpoint, so the full list is fetched
        and matched client-side - fine at the small scale of one account's Customer Master.
        """
        return self._request("GET", "/api/invoices/customers/erp/")

    # -------------------------------------------------------------------------
    # Invoices
    # -------------------------------------------------------------------------

    def create_invoice(self, invoice_payload):
        """ POST /api/invoices/create/ - create a customer invoice or credit note.

        :param dict invoice_payload: see ConvergeX's documented fields.
        :return: the parsed response, including ``tracking_number`` and ``qr_code`` on success.
        :rtype: dict
        """
        return self._request("POST", "/api/invoices/create/", json=invoice_payload)

    def get_compliance_evidence(self, invoice_number):
        """ GET /api/invoices/<invoice_number>/compliance/ - retrieve compliance evidence for an invoice,
        which also exposes the ConvergeX internal invoice UUID. """
        from urllib.parse import quote
        return self._request("GET", f"/api/invoices/{quote(invoice_number, safe='')}/compliance/")

    def get_references_by_number(self, invoice_number):
        """ GET /api/invoices/by-number/<invoice_number>/references/ - recover the tracking number,
        processed reference, and QR code for an invoice that ConvergeX reports as already created.

        Only pass a slash-free invoice_number here (see `l10n_om_convergex_document.py`'s
        invoice-number sanitization) - ConvergeX's routing 404s on a URL-encoded "/" in this path
        segment, which is exactly why the invoice number sent to ConvergeX is sanitized before this
        method is ever called with it.
        """
        from urllib.parse import quote
        return self._request("GET", f"/api/invoices/by-number/{quote(invoice_number, safe='')}/references/")

    def get_summary_by_date_range(self, date_from, date_to):
        """ GET /api/invoices/summary/?date_from=&date_to= - list invoice summaries for the given
        issue-date range (max 500 results, per ConvergeX's docs).

        Kept as a fallback only: observed live taking 40-60+ seconds even with a modest number of
        invoices for one day, and degrading further as more accumulate - `get_references_by_number`
        above should be preferred whenever the invoice number is available.
        """
        return self._request("GET", f"/api/invoices/summary/?date_from={date_from}&date_to={date_to}")

    def get_summary_by_tracking(self, tracking_number):
        """ GET /api/invoices/summary/by-tracking/<tracking_number>/ - current status/summary for one
        previously-created invoice, used to poll for OTA acknowledgement. """
        from urllib.parse import quote
        return self._request("GET", f"/api/invoices/summary/by-tracking/{quote(tracking_number, safe='')}/")

    # -------------------------------------------------------------------------
    # Shared HTTP helper
    # -------------------------------------------------------------------------

    def _request(self, method, path, json=None, authenticated=True):
        """ Perform one HTTP call against ``self.base_url + path``, attaching a fresh Bearer token
        unless ``authenticated=False`` (the token endpoint itself), and raising a clear UserError on
        transport/auth/compliance failures. """
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._get_token()}"

        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(method, url, json=json, headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            _logger.info("Network error calling ConvergeX (%s %s): %s", method, path, e)
            raise UserError(_(
                "Network connectivity issue while contacting ConvergeX. Please check your internet "
                "connection and try again."
            ))

        if response.status_code >= 400:
            _logger.info('"%s %s" %s - response body: %s', method, url, response.status_code, response.text[:2000])
        else:
            _logger.info('"%s %s" %s', method, url, response.status_code)

        if response.status_code in (401, 403):
            raise UserError(_(
                "Authentication with ConvergeX failed. Please check the Client ID/Client Secret "
                "configured in Settings > Accounting > ConvergeX."
            ))
        if response.status_code == 429:
            raise UserError(_("ConvergeX rate limit exceeded. Please wait a moment and try again."))

        try:
            payload = response.json()
        except (JSONDecodeError, ValueError):
            raise UserError(_(
                "ConvergeX returned an unexpected (non-JSON) response (%(status)s):\n%(body)s",
                status=response.status_code, body=response.text[:2000],
            ))

        if response.status_code >= 400:
            raise UserError(_("ConvergeX rejected this request:\n%(details)s", details=self._format_error(payload)))

        return payload

    @staticmethod
    def _format_error(payload):
        """ Format ConvergeX's error/compliance response shape into a readable message, without
        assuming every failure carries the same keys (plain "error", field "details", or a
        structured "compliance.issues" list on create-time compliance failures). """
        if not isinstance(payload, dict):
            return str(payload)
        lines = []
        if payload.get("error"):
            lines.append(str(payload["error"]))
        details = payload.get("details") or {}
        for field, messages in details.items():
            lines.append("%s: %s" % (field, ", ".join(messages) if isinstance(messages, list) else messages))
        compliance = payload.get("compliance") or {}
        for issue in compliance.get("issues") or []:
            lines.append("%s: %s" % (issue.get("code", "?"), issue.get("message", "")))
        return "\n".join(lines) if lines else str(payload)
