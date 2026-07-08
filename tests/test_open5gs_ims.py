"""
Unit tests for Open5GS IMS provisioning logic.

Tests cover:
  - MSISDN generation with prefix cycling
  - APN ensure logic (create if not exist)
  - AuC creation
  - Subscriber creation
  - IMS subscriber creation (realm/scscf formatting)
  - Full IMS provision flow
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from coresimrunner.core_network.open5gs_impl import Open5GS


def _make_config_loader(enable_ims=True, msisdn_prefixes="133,135", msisdn_length=11):
    """Create a mock config_loader for testing."""
    loader = MagicMock()
    loader.get.side_effect = lambda key, default="": {
        "PERMANENT_KEY": "8baf473f2f8fd09487cccbd7097c6862",
        "OPC_VALUE": "8e27b6af0e692e750f32667a3b14605d",
        "AMF": "8000",
        "MSISDN_PREFIXES": msisdn_prefixes,
        "ENABLE_IMS": "true" if enable_ims else "false",
    }.get(key, default)
    loader.get_mcc.return_value = "460"
    loader.get_mnc.return_value = "09"
    loader.get_plmn.return_value = "46009"
    loader.get_int.side_effect = lambda key, default=0: {
        "MSISDN_LENGTH": msisdn_length,
        "INITIAL_IMSI_INDEX": 1,
    }.get(key, default)
    loader.get_core_address.return_value = "192.168.55.53"
    return loader


def _make_open5gs(enable_ims=True, msisdn_prefixes="133,135", msisdn_length=11):
    """Create an Open5GS instance with mock config for testing."""
    loader = _make_config_loader(enable_ims, msisdn_prefixes, msisdn_length)
    with patch.object(Open5GS, '__init__', lambda self, *a, **kw: None):
        o5gs = Open5GS.__new__(Open5GS)

    o5gs.core_ip = "192.168.55.53"
    o5gs.webui_port = "5000"
    o5gs.plmn_id = "46009"
    o5gs.msisdn_prefixes = msisdn_prefixes.split(",")
    o5gs.msisdn_length = msisdn_length
    o5gs.enable_ims = enable_ims
    o5gs.permanent_key = "8baf473f2f8fd09487cccbd7097c6862"
    o5gs.opc_value = "8e27b6af0e692e750f32667a3b14605d"
    o5gs.amf = "8000"
    o5gs.mcc = "460"
    o5gs.mnc = "09"
    o5gs.rest_base = "http://192.168.55.53:8080"
    return o5gs


class TestMsisdnGeneration(unittest.TestCase):
    def test_single_prefix(self):
        o5gs = _make_open5gs(msisdn_prefixes="133", msisdn_length=11)
        self.assertEqual(o5gs._generate_msisdn(1), "13300000000")
        self.assertEqual(o5gs._generate_msisdn(2), "13300000001")

    def test_dual_prefix_cycling(self):
        o5gs = _make_open5gs(msisdn_prefixes="133,135", msisdn_length=11)
        self.assertEqual(o5gs._generate_msisdn(1), "13300000000")
        self.assertEqual(o5gs._generate_msisdn(100000000), "13399999999")
        self.assertEqual(o5gs._generate_msisdn(100000001), "13500000000")
        self.assertEqual(o5gs._generate_msisdn(100000002), "13500000001")

    def test_dual_prefix_short(self):
        o5gs = _make_open5gs(msisdn_prefixes="133,135", msisdn_length=6)
        self.assertEqual(o5gs._generate_msisdn(1), "133000")
        self.assertEqual(o5gs._generate_msisdn(1000), "133999")
        self.assertEqual(o5gs._generate_msisdn(1001), "135000")
        self.assertEqual(o5gs._generate_msisdn(1002), "135001")

    def test_short_msisdn(self):
        o5gs = _make_open5gs(msisdn_prefixes="86", msisdn_length=8)
        self.assertEqual(o5gs._generate_msisdn(1), "86000000")
        self.assertEqual(o5gs._generate_msisdn(10000000), "86999999")


class TestEnsureApns(unittest.TestCase):
    @patch("coresimrunner.core_network.open5gs_impl.requests.get")
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_both_exist(self, mock_put, mock_get):
        o5gs = _make_open5gs()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"apn": "internet", "apn_id": 1},
                {"apn": "ims", "apn_id": 2},
            ],
        )
        result = o5gs._ensure_apns()
        self.assertEqual(result, (1, 2))
        mock_put.assert_not_called()

    @patch("coresimrunner.core_network.open5gs_impl.requests.get")
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_create_missing(self, mock_put, mock_get):
        o5gs = _make_open5gs()
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_put.side_effect = [
            MagicMock(status_code=201, json=lambda: {"apn_id": 1}),
            MagicMock(status_code=201, json=lambda: {"apn_id": 2}),
        ]
        result = o5gs._ensure_apns()
        self.assertEqual(result, (1, 2))
        self.assertEqual(mock_put.call_count, 2)

    @patch("coresimrunner.core_network.open5gs_impl.requests.get")
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_one_exists_one_missing(self, mock_put, mock_get):
        o5gs = _make_open5gs()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"apn": "internet", "apn_id": 5}],
        )
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {"apn_id": 6})
        result = o5gs._ensure_apns()
        self.assertEqual(result, (5, 6))
        mock_put.assert_called_once()


class TestCreateAuc(unittest.TestCase):
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_success(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {"auc_id": 42})
        auc_id = o5gs._create_auc("4600900000000001")
        self.assertEqual(auc_id, 42)
        call_args = mock_put.call_args
        self.assertEqual(call_args[0][0], "http://192.168.55.53:8080/auc/")
        body = call_args[1]["json"]
        self.assertEqual(body["ki"], "8baf473f2f8fd09487cccbd7097c6862")
        self.assertEqual(body["opc"], "8e27b6af0e692e750f32667a3b14605d")
        self.assertEqual(body["amf"], "8000")
        self.assertEqual(body["imsi"], "4600900000000001")

    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_failure(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.return_value = MagicMock(status_code=500, json=lambda: {})
        self.assertIsNone(o5gs._create_auc("4600900000000001"))


class TestCreateSubscriber(unittest.TestCase):
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_success(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {})
        result = o5gs._create_subscriber("4600900000000001", "13300000001", 42, 1, 2)
        self.assertTrue(result)
        body = mock_put.call_args[1]["json"]
        self.assertEqual(body["imsi"], "4600900000000001")
        self.assertEqual(body["msisdn"], "13300000001")
        self.assertEqual(body["auc_id"], 42)
        self.assertEqual(body["default_apn"], 1)
        self.assertEqual(body["apn_list"], "1,2")
        self.assertTrue(body["enabled"])


class TestCreateImsSubscriber(unittest.TestCase):
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_realm_formatting(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {})
        result = o5gs._create_ims_subscriber("4600900000000001", "13300000001")
        self.assertTrue(result)
        body = mock_put.call_args[1]["json"]
        self.assertEqual(body["imsi"], "4600900000000001")
        self.assertEqual(body["msisdn"], "13300000001")
        self.assertEqual(body["scscf_peer"], "scscf.ims.mnc009.mcc460.3gppnetwork.org")
        self.assertEqual(body["scscf"], "sip:scscf.ims.mnc009.mcc460.3gppnetwork.org:6060")
        self.assertEqual(body["scscf_realm"], "ims.mnc009.mcc460.3gppnetwork.org")
        self.assertEqual(body["msisdn_list"], "[13300000001]")
        self.assertEqual(body["ifc_path"], "default_ifc.xml")

    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_different_plmn(self, mock_put):
        o5gs = _make_open5gs()
        o5gs.mcc = "208"
        o5gs.mnc = "93"
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {})
        o5gs._create_ims_subscriber("2089300000000001", "13300000001")
        body = mock_put.call_args[1]["json"]
        self.assertEqual(body["scscf_realm"], "ims.mnc093.mcc208.3gppnetwork.org")

    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_short_mnc_padding(self, mock_put):
        o5gs = _make_open5gs()
        o5gs.mcc = "001"
        o5gs.mnc = "1"
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {})
        o5gs._create_ims_subscriber("0010100000000001", "13300000001")
        body = mock_put.call_args[1]["json"]
        self.assertEqual(body["scscf_realm"], "ims.mnc001.mcc001.3gppnetwork.org")


class TestProvisionOneIms(unittest.TestCase):
    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_full_flow(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.side_effect = [
            MagicMock(status_code=201, json=lambda: {"auc_id": 10}),
            MagicMock(status_code=201, json=lambda: {}),
            MagicMock(status_code=201, json=lambda: {}),
        ]
        idx, ok = o5gs._provision_one_ims(1, 1, 2)
        self.assertTrue(ok)
        self.assertEqual(idx, 1)
        self.assertEqual(mock_put.call_count, 3)

    @patch("coresimrunner.core_network.open5gs_impl.requests.put")
    def test_auc_failure_aborts(self, mock_put):
        o5gs = _make_open5gs()
        mock_put.return_value = MagicMock(status_code=500, json=lambda: {})
        idx, ok = o5gs._provision_one_ims(1, 1, 2)
        self.assertFalse(ok)


class TestProvisionMode(unittest.TestCase):
    def test_ims_mode_enabled(self):
        o5gs = _make_open5gs(enable_ims=True)
        self.assertTrue(o5gs.enable_ims)

    def test_ims_mode_disabled(self):
        o5gs = _make_open5gs(enable_ims=False)
        self.assertFalse(o5gs.enable_ims)


if __name__ == "__main__":
    unittest.main()