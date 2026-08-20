#!/usr/bin/env python3
"""
Unit tests for Open5GS.delete_all_subscriptions() (core_network/open5gs_impl.py).

Verifies that --delete-all removes BOTH the Open5GS WebUI subscribers
and all PyHSS data (ims_subscriber, subscriber, auc, apn).

All HTTP interactions are mocked — no live Open5GS/PyHSS server is needed.

Run:
    python3 -m pytest tests/test_open5gs_delete_all.py -v
"""

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Add project root (for core_network.*) and its parent (for coresimrunner.*)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from core_network.open5gs_impl import Open5GS


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_response(status_code=200, json_data=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


class FakeConfigLoader:
    """Minimal ConfigLoader stub for constructing Open5GS."""

    def __init__(self, enable_ims=True):
        self.enable_ims = enable_ims

    def get_network_config(self, name):
        return {
            "ip": "10.0.0.1",
            "webui_port": "9999",
            "plmn_id": "46009",
            "mcc": "460",
            "mnc": "09",
            "username": "admin",
            "password": "1423",
            "subscription_template": {"msisdn": ["13300000001"]},
            "initial_imsi_index": 1,
        }

    def get(self, key, default=""):
        if key == "ENABLE_IMS":
            return "true" if self.enable_ims else "false"
        if key == "PYHSS_PORT":
            return "8080"
        return default


def _make_open5gs(enable_ims=True):
    """Build an Open5GS instance with a mocked PyHSS client."""
    o5 = Open5GS(FakeConfigLoader(enable_ims=enable_ims))
    o5.pyhss = MagicMock()
    o5.pyhss.delete_all.return_value = True
    return o5


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestDeleteAllSubscriptions(unittest.TestCase):

    SUBSCRIBER_URL = "http://10.0.0.1:9999/api/db/Subscriber"

    @patch.object(Open5GS, "_authenticate")
    def test_deletes_webui_and_pyhss(self, mock_auth):
        """All WebUI subscribers are deleted AND pyhss.delete_all is called."""
        o5 = _make_open5gs()
        session = MagicMock()
        session.get.return_value = _make_response(
            200, [{"imsi": "460090000000001"}, {"imsi": "460090000000002"}]
        )
        session.delete.return_value = _make_response(200)
        mock_auth.return_value = session

        self.assertTrue(o5.delete_all_subscriptions())

        # One DELETE per WebUI subscriber
        self.assertEqual(session.delete.call_count, 2)
        deleted_urls = {c.args[0] for c in session.delete.call_args_list}
        self.assertEqual(deleted_urls, {
            f"{self.SUBSCRIBER_URL}/460090000000001",
            f"{self.SUBSCRIBER_URL}/460090000000002",
        })
        o5.pyhss.delete_all.assert_called_once()

    @patch.object(Open5GS, "_authenticate")
    def test_pyhss_deleted_before_webui(self, mock_auth):
        """PyHSS (ims_subscriber -> subscriber -> auc -> apn) must be
        cleared BEFORE any WebUI subscriber is touched."""
        o5 = _make_open5gs()
        session = MagicMock()
        session.get.return_value = _make_response(200, [{"imsi": "460090000000001"}])
        session.delete.return_value = _make_response(200)
        mock_auth.return_value = session

        webui_query_done = []

        def on_pyhss_delete_all():
            # WebUI list query must NOT have happened yet
            self.assertFalse(webui_query_done, "WebUI was touched before PyHSS cleanup")
            return True

        def tracking_get(*a, **kw):
            webui_query_done.append(True)
            return _make_response(200, [{"imsi": "460090000000001"}])

        o5.pyhss.delete_all.side_effect = on_pyhss_delete_all
        session.get.side_effect = tracking_get

        self.assertTrue(o5.delete_all_subscriptions())
        o5.pyhss.delete_all.assert_called_once()

    @patch.object(Open5GS, "_authenticate")
    def test_empty_webui_still_deletes_pyhss(self, mock_auth):
        """Empty WebUI database is not an error; PyHSS is still cleaned."""
        o5 = _make_open5gs()
        session = MagicMock()
        session.get.return_value = _make_response(200, [])
        mock_auth.return_value = session

        self.assertTrue(o5.delete_all_subscriptions())
        session.delete.assert_not_called()
        o5.pyhss.delete_all.assert_called_once()

    @patch.object(Open5GS, "_authenticate")
    def test_auth_failure_returns_false(self, mock_auth):
        """If WebUI authentication fails, delete-all returns False,
        but PyHSS cleanup is still attempted."""
        o5 = _make_open5gs()
        mock_auth.return_value = None

        self.assertFalse(o5.delete_all_subscriptions())
        o5.pyhss.delete_all.assert_called_once()

    @patch.object(Open5GS, "_authenticate")
    def test_pyhss_failure_returns_false(self, mock_auth):
        """WebUI success + PyHSS failure -> overall False."""
        o5 = _make_open5gs()
        o5.pyhss.delete_all.return_value = False
        session = MagicMock()
        session.get.return_value = _make_response(200, [{"imsi": "460090000000001"}])
        session.delete.return_value = _make_response(200)
        mock_auth.return_value = session

        self.assertFalse(o5.delete_all_subscriptions())
        self.assertEqual(session.delete.call_count, 1)

    @patch.object(Open5GS, "_authenticate")
    def test_webui_delete_failure_returns_false(self, mock_auth):
        """A failed WebUI DELETE makes the whole operation False."""
        o5 = _make_open5gs()
        session = MagicMock()
        session.get.return_value = _make_response(200, [{"imsi": "460090000000001"}])
        session.delete.return_value = _make_response(500)
        mock_auth.return_value = session

        self.assertFalse(o5.delete_all_subscriptions())

    @patch.object(Open5GS, "_authenticate")
    def test_ims_disabled_skips_pyhss(self, mock_auth):
        """When ENABLE_IMS=false only the WebUI part runs."""
        o5 = _make_open5gs(enable_ims=False)
        session = MagicMock()
        session.get.return_value = _make_response(200, [{"imsi": "460090000000001"}])
        session.delete.return_value = _make_response(204)
        mock_auth.return_value = session

        self.assertTrue(o5.delete_all_subscriptions())
        self.assertEqual(session.delete.call_count, 1)


# ------------------------------------------------------------------
# Provisioning — unique MSISDN per subscriber
# ------------------------------------------------------------------

class TestProvisionMsisdn(unittest.TestCase):
    """Every Open5GS subscriber must get a unique MSISDN derived from
    the IMSI index instead of the hardcoded template value."""

    @patch.object(Open5GS, "_authenticate")
    def test_unique_msisdn_per_subscriber(self, mock_auth):
        o5 = _make_open5gs()
        o5.pyhss.ensure_apns.return_value = (1, 2)
        session = MagicMock()
        session.post.return_value = _make_response(201)
        mock_auth.return_value = session

        self.assertTrue(o5.provision_subscriptions(3))

        payloads = [
            json.loads(c.kwargs["data"]) for c in session.post.call_args_list
        ]
        msisdns = [p["msisdn"] for p in payloads]
        # Template starts at index 1 with '13300000001'
        self.assertEqual(
            sorted(msisdns),
            [["13300000001"], ["13300000002"], ["13300000003"]],
        )
        # No duplicates
        self.assertEqual(len(set(map(tuple, msisdns))), 3)

    def test_derive_msisdn_values(self):
        o5 = _make_open5gs()
        self.assertEqual(o5._derive_msisdn(1), "13300000001")
        self.assertEqual(o5._derive_msisdn(42), "13300000042")
        self.assertEqual(o5._derive_msisdn(9999), "13300009999")

    def test_template_not_mutated(self):
        """Deriving MSISDNs must not alter the shared template."""
        o5 = _make_open5gs()
        before = json.dumps(o5.subscription_template)
        o5._derive_msisdn(7)
        self.assertEqual(json.dumps(o5.subscription_template), before)


if __name__ == "__main__":
    unittest.main()
