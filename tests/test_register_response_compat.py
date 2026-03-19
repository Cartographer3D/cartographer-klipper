"""Tests for backward-compatible MCU response registration.

Verifies that cartographer.py, idm.py, and scanner.py correctly use
register_serial_response() on Klipper >= v0.13 and fall back to
register_response() on older Klipper versions.
"""

import unittest
from unittest.mock import MagicMock, patch, call


def _make_mock_mcu(new_api=True):
    """Create a mock MCU with either the new or old registration API.

    Args:
        new_api: If True, MCU has register_serial_response (Klipper >= v0.13).
                 If False, MCU only has register_response (older Klipper).
    """
    mcu = MagicMock()
    if not new_api:
        del mcu.register_serial_response
    return mcu


def _call_registration_compat(mcu, handler, msg_name, msg_format):
    """Replicate the hasattr-based registration pattern used in all 3 files.

    This is the exact pattern we patched into cartographer.py, idm.py,
    and scanner.py — extracted here so we can test the logic in isolation
    without instantiating the full plugin classes (which require the
    entire Klipper runtime).
    """
    if hasattr(mcu, "register_serial_response"):
        mcu.register_serial_response(handler, msg_format)
    else:
        mcu.register_response(handler, msg_name)


class TestNewKlipperAPI(unittest.TestCase):
    """Tests for Klipper >= v0.13 (has register_serial_response)."""

    def test_cartographer_uses_register_serial_response(self):
        mcu = _make_mock_mcu(new_api=True)
        handler = MagicMock(name="handle_cartographer_data")

        _call_registration_compat(
            mcu, handler,
            "cartographer_data",
            "cartographer_data clock=%u data=%u temp=%u",
        )

        mcu.register_serial_response.assert_called_once_with(
            handler, "cartographer_data clock=%u data=%u temp=%u"
        )
        mcu.register_response.assert_not_called()

    def test_idm_uses_register_serial_response(self):
        mcu = _make_mock_mcu(new_api=True)
        handler = MagicMock(name="handle_idm_data")

        _call_registration_compat(
            mcu, handler,
            "idm_data",
            "idm_data clock=%u data=%u temp=%u",
        )

        mcu.register_serial_response.assert_called_once_with(
            handler, "idm_data clock=%u data=%u temp=%u"
        )
        mcu.register_response.assert_not_called()

    def test_scanner_uses_register_serial_response(self):
        mcu = _make_mock_mcu(new_api=True)
        handler = MagicMock(name="handle_scanner_data")
        sensor = "Scanner"

        msg_name = sensor.lower() + "_data"
        msg_format = sensor.lower() + "_data clock=%u data=%u temp=%u"

        _call_registration_compat(mcu, handler, msg_name, msg_format)

        mcu.register_serial_response.assert_called_once_with(
            handler, "scanner_data clock=%u data=%u temp=%u"
        )
        mcu.register_response.assert_not_called()


class TestOldKlipperAPI(unittest.TestCase):
    """Tests for Klipper < v0.13 (only has register_response)."""

    def test_cartographer_falls_back_to_register_response(self):
        mcu = _make_mock_mcu(new_api=False)
        handler = MagicMock(name="handle_cartographer_data")

        _call_registration_compat(
            mcu, handler,
            "cartographer_data",
            "cartographer_data clock=%u data=%u temp=%u",
        )

        mcu.register_response.assert_called_once_with(
            handler, "cartographer_data"
        )
        assert not hasattr(mcu, "register_serial_response")

    def test_idm_falls_back_to_register_response(self):
        mcu = _make_mock_mcu(new_api=False)
        handler = MagicMock(name="handle_idm_data")

        _call_registration_compat(
            mcu, handler,
            "idm_data",
            "idm_data clock=%u data=%u temp=%u",
        )

        mcu.register_response.assert_called_once_with(
            handler, "idm_data"
        )
        assert not hasattr(mcu, "register_serial_response")

    def test_scanner_falls_back_to_register_response(self):
        mcu = _make_mock_mcu(new_api=False)
        handler = MagicMock(name="handle_scanner_data")
        sensor = "Scanner"

        msg_name = sensor.lower() + "_data"
        msg_format = sensor.lower() + "_data clock=%u data=%u temp=%u"

        _call_registration_compat(mcu, handler, msg_name, msg_format)

        mcu.register_response.assert_called_once_with(
            handler, "scanner_data"
        )
        assert not hasattr(mcu, "register_serial_response")


class TestScannerDynamicSensor(unittest.TestCase):
    """Scanner uses a dynamic sensor name — verify format string is correct."""

    def test_cartographer_sensor_name(self):
        mcu = _make_mock_mcu(new_api=True)
        handler = MagicMock()
        sensor = "Cartographer"

        msg_format = sensor.lower() + "_data clock=%u data=%u temp=%u"
        _call_registration_compat(mcu, handler, sensor.lower() + "_data", msg_format)

        mcu.register_serial_response.assert_called_once_with(
            handler, "cartographer_data clock=%u data=%u temp=%u"
        )

    def test_idm_sensor_name(self):
        mcu = _make_mock_mcu(new_api=True)
        handler = MagicMock()
        sensor = "IDM"

        msg_format = sensor.lower() + "_data clock=%u data=%u temp=%u"
        _call_registration_compat(mcu, handler, sensor.lower() + "_data", msg_format)

        mcu.register_serial_response.assert_called_once_with(
            handler, "idm_data clock=%u data=%u temp=%u"
        )

    def test_custom_sensor_name_fallback(self):
        """An arbitrary sensor name still falls back correctly on old API."""
        mcu = _make_mock_mcu(new_api=False)
        handler = MagicMock()
        sensor = "CustomProbe"

        msg_name = sensor.lower() + "_data"
        msg_format = sensor.lower() + "_data clock=%u data=%u temp=%u"
        _call_registration_compat(mcu, handler, msg_name, msg_format)

        mcu.register_response.assert_called_once_with(
            handler, "customprobe_data"
        )


class TestSourceFilePatterns(unittest.TestCase):
    """Verify the actual source files contain the expected hasattr pattern.

    These are lightweight 'grep tests' that ensure the compatibility shim
    is present in each file and hasn't been accidentally reverted.
    """

    def _read_source(self, filename):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", filename)
        with open(path, "r") as f:
            return f.read()

    def test_cartographer_has_compat_shim(self):
        src = self._read_source("cartographer.py")
        assert 'hasattr(self._mcu, "register_serial_response")' in src
        assert "register_serial_response(self._handle_cartographer_data" in src
        assert 'register_response(self._handle_cartographer_data, "cartographer_data")' in src

    def test_idm_has_compat_shim(self):
        src = self._read_source("idm.py")
        assert 'hasattr(self._mcu, "register_serial_response")' in src
        assert "register_serial_response(self._handle_idm_data" in src
        assert 'register_response(self._handle_idm_data, "idm_data")' in src

    def test_scanner_has_compat_shim(self):
        src = self._read_source("scanner.py")
        assert 'hasattr(self._mcu, "register_serial_response")' in src
        assert "register_serial_response(" in src
        assert "register_response(" in src
        # Scanner uses dynamic sensor name, so check the pattern
        assert '_data clock=%u data=%u temp=%u' in src


if __name__ == "__main__":
    unittest.main()
