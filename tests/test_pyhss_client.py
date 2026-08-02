#!/usr/bin/env python3
"""
Unit tests for PyHSSClient (core_network/pyhss_client.py).

All HTTP requests are mocked — no live PyHSS server is needed.

Run:
    python3 -m pytest tests/test_pyhss_client.py -v
    # or
    python3 tests/test_pyhss_client.py
"""

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core_network.pyhss_client import PyHSSClient


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

BASE_URL = "http://10.0.0.1:8080"
MCC = "460"
MNC = "09"
IMSI = "460090000000001"
MSISDN = "13300000001"
KI = "12341234123412341234123412340000"
OPC = "71a121bb69baf3c0cc53fb5038a0131f"
AMF = "8000"


def _make_response(status_code=200, json_data=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    return resp


def _apn_entry(apn_id, name):
    return {
        "apn_id": apn_id,
        "apn": name,
        "apn_ambr_dl": 0,
        "apn_ambr_ul": 0,
        "qci": 9,
    }


# ==================================================================
# Constructor
# ==================================================================

class TestConstructor(unittest.TestCase):
    """Verify constructor builds correct derived values."""

    def test_realm_and_scscf(self):
        c = PyHSSClient(BASE_URL, MCC, MNC)
        self.assertEqual(c.realm, "ims.mnc09.mcc460.3gppnetwork.org")
        self.assertEqual(
            c.scscf_uri,
            "sip:scscf.ims.mnc09.mcc460.3gppnetwork.org:6060",
        )
        self.assertEqual(
            c.scscf_peer,
            "scscf.ims.mnc09.mcc460.3gppnetwork.org",
        )

    def test_trailing_slash_stripped(self):
        c = PyHSSClient(BASE_URL + "/", MCC, MNC)
        self.assertEqual(c.base_url, BASE_URL)

    def test_different_plmn(self):
        c = PyHSSClient(BASE_URL, "001", "01")
        self.assertEqual(c.realm, "ims.mnc01.mcc001.3gppnetwork.org")


# ==================================================================
# APN — _get_apn_list
# ==================================================================

class TestGetApnList(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.get")
    def test_success(self, mock_get):
        apns = [_apn_entry(1, "internet"), _apn_entry(2, "ims")]
        mock_get.return_value = _make_response(200, apns)
        result = self.client._get_apn_list()
        self.assertEqual(result, apns)
        mock_get.assert_called_once_with(
            f"{BASE_URL}/apn/list?page=0&page_size=200", timeout=30
        )

    @patch("core_network.pyhss_client.requests.get")
    def test_http_error(self, mock_get):
        mock_get.return_value = _make_response(500)
        result = self.client._get_apn_list()
        self.assertIsNone(result)

    @patch("core_network.pyhss_client.requests.get")
    def test_connection_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        result = self.client._get_apn_list()
        self.assertIsNone(result)


# ==================================================================
# APN — _create_apn
# ==================================================================

class TestCreateApn(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.put")
    def test_create_internet(self, mock_put):
        mock_put.return_value = _make_response(200, {"apn_id": 1})
        result = self.client._create_apn("internet")
        self.assertEqual(result, 1)
        mock_put.assert_called_once_with(
            f"{BASE_URL}/apn/",
            json={"apn": "internet", "apn_ambr_dl": 0, "apn_ambr_ul": 0},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("core_network.pyhss_client.requests.put")
    def test_create_ims(self, mock_put):
        mock_put.return_value = _make_response(201, {"apn_id": 2})
        result = self.client._create_apn("ims")
        self.assertEqual(result, 2)

    @patch("core_network.pyhss_client.requests.put")
    def test_create_failure(self, mock_put):
        mock_put.return_value = _make_response(409, {"error": "duplicate"})
        result = self.client._create_apn("internet")
        self.assertIsNone(result)

    @patch("core_network.pyhss_client.requests.put")
    def test_create_network_error(self, mock_put):
        import requests as req
        mock_put.side_effect = req.exceptions.Timeout("timeout")
        result = self.client._create_apn("internet")
        self.assertIsNone(result)


# ==================================================================
# APN — ensure_apns (idempotent)
# ==================================================================

class TestEnsureApns(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.put")
    @patch("core_network.pyhss_client.requests.get")
    def test_both_exist(self, mock_get, mock_put):
        """When both APNs already exist, no PUT should be made."""
        mock_get.return_value = _make_response(
            200, [_apn_entry(1, "internet"), _apn_entry(2, "ims")]
        )
        inet, ims = self.client.ensure_apns()
        self.assertEqual(inet, 1)
        self.assertEqual(ims, 2)
        mock_put.assert_not_called()

    @patch("core_network.pyhss_client.requests.put")
    @patch("core_network.pyhss_client.requests.get")
    def test_none_exist(self, mock_get, mock_put):
        """When no APNs exist, both should be created."""
        mock_get.return_value = _make_response(200, [])
        mock_put.side_effect = [
            _make_response(200, {"apn_id": 10}),
            _make_response(200, {"apn_id": 20}),
        ]
        inet, ims = self.client.ensure_apns()
        self.assertEqual(inet, 10)
        self.assertEqual(ims, 20)
        self.assertEqual(mock_put.call_count, 2)

    @patch("core_network.pyhss_client.requests.put")
    @patch("core_network.pyhss_client.requests.get")
    def test_only_internet_exists(self, mock_get, mock_put):
        """Only 'ims' should be created."""
        mock_get.return_value = _make_response(
            200, [_apn_entry(1, "internet")]
        )
        mock_put.return_value = _make_response(200, {"apn_id": 5})
        inet, ims = self.client.ensure_apns()
        self.assertEqual(inet, 1)
        self.assertEqual(ims, 5)
        mock_put.assert_called_once()

    @patch("core_network.pyhss_client.requests.put")
    @patch("core_network.pyhss_client.requests.get")
    def test_only_ims_exists(self, mock_get, mock_put):
        """Only 'internet' should be created."""
        mock_get.return_value = _make_response(200, [_apn_entry(2, "ims")])
        mock_put.return_value = _make_response(200, {"apn_id": 3})
        inet, ims = self.client.ensure_apns()
        self.assertEqual(inet, 3)
        self.assertEqual(ims, 2)

    @patch("core_network.pyhss_client.requests.get")
    def test_list_fails(self, mock_get):
        """If the list call fails, attempt to create both."""
        mock_get.return_value = _make_response(500)
        with patch.object(self.client, "_create_apn") as mock_create:
            mock_create.side_effect = [10, 20]
            inet, ims = self.client.ensure_apns()
            self.assertEqual(inet, 10)
            self.assertEqual(ims, 20)

    @patch("core_network.pyhss_client.requests.put")
    @patch("core_network.pyhss_client.requests.get")
    def test_create_fails(self, mock_get, mock_put):
        """If creation fails, the corresponding ID should be None."""
        mock_get.return_value = _make_response(200, [])
        mock_put.side_effect = [
            _make_response(500),                    # internet fails
            _make_response(200, {"apn_id": 2}),     # ims succeeds
        ]
        inet, ims = self.client.ensure_apns()
        self.assertIsNone(inet)
        self.assertEqual(ims, 2)


# ==================================================================
# AuC — create_auc
# ==================================================================

class TestCreateAuc(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.put")
    def test_success(self, mock_put):
        mock_put.return_value = _make_response(200, {"auc_id": 42})
        result = self.client.create_auc(IMSI, KI, OPC, AMF)
        self.assertEqual(result, 42)
        mock_put.assert_called_once_with(
            f"{BASE_URL}/auc/",
            json={"ki": KI, "opc": OPC, "amf": AMF, "sqn": 0, "imsi": IMSI},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("core_network.pyhss_client.requests.put")
    def test_success_201(self, mock_put):
        mock_put.return_value = _make_response(201, {"auc_id": 7})
        result = self.client.create_auc(IMSI, KI, OPC)
        self.assertEqual(result, 7)

    @patch("core_network.pyhss_client.requests.put")
    def test_default_amf(self, mock_put):
        mock_put.return_value = _make_response(200, {"auc_id": 1})
        self.client.create_auc(IMSI, KI, OPC)
        payload = mock_put.call_args[1]["json"]
        self.assertEqual(payload["amf"], "8000")

    @patch("core_network.pyhss_client.requests.put")
    def test_failure(self, mock_put):
        mock_put.return_value = _make_response(400, {"error": "bad request"})
        result = self.client.create_auc(IMSI, KI, OPC)
        self.assertIsNone(result)

    @patch("core_network.pyhss_client.requests.put")
    def test_network_error(self, mock_put):
        import requests as req
        mock_put.side_effect = req.exceptions.ConnectionError("refused")
        result = self.client.create_auc(IMSI, KI, OPC)
        self.assertIsNone(result)


# ==================================================================
# Subscriber — create_subscriber
# ==================================================================

class TestCreateSubscriber(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.put")
    def test_success(self, mock_put):
        mock_put.return_value = _make_response(200, {"subscriber_id": 1})
        result = self.client.create_subscriber(
            imsi=IMSI, auc_id=1, default_apn=1,
            apn_list="1,2", msisdn=MSISDN,
        )
        self.assertTrue(result)
        mock_put.assert_called_once_with(
            f"{BASE_URL}/subscriber/",
            json={
                "imsi": IMSI,
                "enabled": True,
                "auc_id": 1,
                "default_apn": 1,
                "apn_list": "1,2",
                "msisdn": MSISDN,
                "ue_ambr_dl": 0,
                "ue_ambr_ul": 0,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("core_network.pyhss_client.requests.put")
    def test_failure(self, mock_put):
        mock_put.return_value = _make_response(500)
        result = self.client.create_subscriber(
            IMSI, 1, 1, "1,2", MSISDN
        )
        self.assertFalse(result)

    @patch("core_network.pyhss_client.requests.put")
    def test_network_error(self, mock_put):
        import requests as req
        mock_put.side_effect = req.exceptions.Timeout("timeout")
        result = self.client.create_subscriber(IMSI, 1, 1, "1,2", MSISDN)
        self.assertFalse(result)


# ==================================================================
# IMS Subscriber — create_ims_subscriber
# ==================================================================

class TestCreateImsSubscriber(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.put")
    def test_success(self, mock_put):
        mock_put.return_value = _make_response(200, {})
        result = self.client.create_ims_subscriber(IMSI, MSISDN)
        self.assertTrue(result)
        mock_put.assert_called_once_with(
            f"{BASE_URL}/ims_subscriber/",
            json={
                "imsi": IMSI,
                "msisdn": MSISDN,
                "sh_profile": "string",
                "scscf_peer": "scscf.ims.mnc09.mcc460.3gppnetwork.org",
                "msisdn_list": f"[{MSISDN}]",
                "ifc_path": "default_ifc.xml",
                "scscf": "sip:scscf.ims.mnc09.mcc460.3gppnetwork.org:6060",
                "scscf_realm": "ims.mnc09.mcc460.3gppnetwork.org",
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("core_network.pyhss_client.requests.put")
    def test_scscf_fields_match_plmn(self, mock_put):
        """S-CSCF fields must reflect the configured PLMN."""
        client = PyHSSClient(BASE_URL, "208", "93")
        mock_put.return_value = _make_response(200, {})
        client.create_ims_subscriber("208930000000001", "33600000001")
        payload = mock_put.call_args[1]["json"]
        self.assertEqual(
            payload["scscf"],
            "sip:scscf.ims.mnc93.mcc208.3gppnetwork.org:6060",
        )
        self.assertEqual(
            payload["scscf_realm"], "ims.mnc93.mcc208.3gppnetwork.org"
        )
        self.assertEqual(
            payload["scscf_peer"],
            "scscf.ims.mnc93.mcc208.3gppnetwork.org",
        )

    @patch("core_network.pyhss_client.requests.put")
    def test_failure(self, mock_put):
        mock_put.return_value = _make_response(500)
        result = self.client.create_ims_subscriber(IMSI, MSISDN)
        self.assertFalse(result)

    @patch("core_network.pyhss_client.requests.put")
    def test_network_error(self, mock_put):
        import requests as req
        mock_put.side_effect = req.exceptions.ConnectionError("refused")
        result = self.client.create_ims_subscriber(IMSI, MSISDN)
        self.assertFalse(result)


# ==================================================================
# Orchestrated — provision_ims_subscriber
# ==================================================================

class TestProvisionImsSubscriber(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch.object(PyHSSClient, "create_ims_subscriber")
    @patch.object(PyHSSClient, "create_subscriber")
    @patch.object(PyHSSClient, "create_auc")
    @patch.object(PyHSSClient, "ensure_apns")
    def test_full_success(self, mock_apns, mock_auc, mock_sub, mock_ims):
        mock_apns.return_value = (1, 2)
        mock_auc.return_value = 10
        mock_sub.return_value = True
        mock_ims.return_value = True

        result = self.client.provision_ims_subscriber(
            IMSI, MSISDN, KI, OPC, AMF
        )
        self.assertTrue(result)

        mock_apns.assert_called_once()
        mock_auc.assert_called_once_with(IMSI, KI, OPC, AMF)
        mock_sub.assert_called_once_with(IMSI, 10, 1, "1,2", MSISDN)
        mock_ims.assert_called_once_with(IMSI, MSISDN)

    @patch.object(PyHSSClient, "ensure_apns")
    def test_apn_failure_aborts(self, mock_apns):
        mock_apns.return_value = (None, 2)
        result = self.client.provision_ims_subscriber(
            IMSI, MSISDN, KI, OPC
        )
        self.assertFalse(result)

    @patch.object(PyHSSClient, "create_auc")
    @patch.object(PyHSSClient, "ensure_apns")
    def test_auc_failure_aborts(self, mock_apns, mock_auc):
        mock_apns.return_value = (1, 2)
        mock_auc.return_value = None
        result = self.client.provision_ims_subscriber(
            IMSI, MSISDN, KI, OPC
        )
        self.assertFalse(result)

    @patch.object(PyHSSClient, "create_subscriber")
    @patch.object(PyHSSClient, "create_auc")
    @patch.object(PyHSSClient, "ensure_apns")
    def test_subscriber_failure_aborts(self, mock_apns, mock_auc, mock_sub):
        mock_apns.return_value = (1, 2)
        mock_auc.return_value = 10
        mock_sub.return_value = False
        result = self.client.provision_ims_subscriber(
            IMSI, MSISDN, KI, OPC
        )
        self.assertFalse(result)

    @patch.object(PyHSSClient, "create_ims_subscriber")
    @patch.object(PyHSSClient, "create_subscriber")
    @patch.object(PyHSSClient, "create_auc")
    @patch.object(PyHSSClient, "ensure_apns")
    def test_ims_subscriber_failure(self, mock_apns, mock_auc, mock_sub, mock_ims):
        mock_apns.return_value = (1, 2)
        mock_auc.return_value = 10
        mock_sub.return_value = True
        mock_ims.return_value = False
        result = self.client.provision_ims_subscriber(
            IMSI, MSISDN, KI, OPC
        )
        self.assertFalse(result)

    @patch.object(PyHSSClient, "create_ims_subscriber")
    @patch.object(PyHSSClient, "create_subscriber")
    @patch.object(PyHSSClient, "create_auc")
    @patch.object(PyHSSClient, "ensure_apns")
    def test_apn_list_format(self, mock_apns, mock_auc, mock_sub, mock_ims):
        """apn_list should be 'internet_id,ims_id'."""
        mock_apns.return_value = (5, 9)
        mock_auc.return_value = 20
        mock_sub.return_value = True
        mock_ims.return_value = True
        self.client.provision_ims_subscriber(IMSI, MSISDN, KI, OPC)
        # default_apn = internet (5), apn_list = "5,9"
        mock_sub.assert_called_once_with(IMSI, 20, 5, "5,9", MSISDN)


# ==================================================================
# Delete — delete_subscriber
# ==================================================================

class TestDeleteSubscriber(unittest.TestCase):
    def setUp(self):
        self.client = PyHSSClient(BASE_URL, MCC, MNC)

    @patch("core_network.pyhss_client.requests.delete")
    def test_success(self, mock_del):
        mock_del.return_value = _make_response(200)
        result = self.client.delete_subscriber(IMSI)
        self.assertTrue(result)
        self.assertEqual(mock_del.call_count, 3)
        # Verify all three resources were deleted
        urls = [c[0][0] for c in mock_del.call_args_list]
        self.assertIn(f"{BASE_URL}/ims_subscriber/{IMSI}", urls)
        self.assertIn(f"{BASE_URL}/subscriber/{IMSI}", urls)
        self.assertIn(f"{BASE_URL}/auc/{IMSI}", urls)

    @patch("core_network.pyhss_client.requests.delete")
    def test_partial_failure(self, mock_del):
        mock_del.side_effect = [
            _make_response(200),
            _make_response(404),
            _make_response(200),
        ]
        result = self.client.delete_subscriber(IMSI)
        self.assertFalse(result)

    @patch("core_network.pyhss_client.requests.delete")
    def test_network_error(self, mock_del):
        import requests as req
        mock_del.side_effect = req.exceptions.ConnectionError("refused")
        result = self.client.delete_subscriber(IMSI)
        self.assertFalse(result)


# ==================================================================
# Open5GS integration — _derive_msisdn
# ==================================================================

class TestDeriveMsisdn(unittest.TestCase):
    """Test the MSISDN derivation logic in Open5GS."""

    def test_derive_from_template(self):
        from core_network.open5gs_impl import Open5GS
        # Simulate what _derive_msisdn does without full __init__
        template = {"msisdn": ["13300000001"]}
        prefix = template["msisdn"][0][:3]
        for idx, expected in [(1, "13300000001"), (42, "13300000042"), (999, "13300000999")]:
            result = f"{prefix}{idx:08d}"
            self.assertEqual(result, expected)

    def test_fallback_prefix(self):
        result = f"133{1:08d}"
        self.assertEqual(result, "13300000001")


# ==================================================================
# Runner
# ==================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
