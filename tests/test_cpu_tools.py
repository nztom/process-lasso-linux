"""Tests for AMD dual-CCD X3D scheduler preference discovery."""
from __future__ import annotations

import unittest
from unittest import mock

import cpu_tools


class X3DModeTests(unittest.TestCase):
    def setUp(self):
        cpu_tools.clear_cpu_info_cache()

    def tearDown(self):
        cpu_tools.clear_cpu_info_cache()

    @mock.patch("cpu_tools.is_helper_installed", return_value=True)
    def test_helper_current_requires_exact_generated_content(self, _installed):
        with mock.patch("cpu_tools.open", mock.mock_open(
            read_data=cpu_tools.HELPER_CONTENT
        )):
            self.assertTrue(cpu_tools.is_helper_current())
        with mock.patch("cpu_tools.open", mock.mock_open(
            read_data=cpu_tools.HELPER_CONTENT.replace(
                "Asymmetric L3 topology not found", "old helper"
            )
        )):
            self.assertFalse(cpu_tools.is_helper_current())

    @mock.patch("cpu_tools.get_x3d_mode_path", return_value="/mode")
    @mock.patch("cpu_tools.get_smt_siblings_of", return_value={1, 3})
    @mock.patch("cpu_tools._parse_cpulist_file")
    @mock.patch("cpu_tools.detect_topology")
    def test_cpu_info_exposes_dedicated_feature_flags(
        self, topology, cpulist, _siblings, _path
    ):
        topology.return_value = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1}, non_preferred={2, 3},
        )
        cpulist.side_effect = lambda path: (
            {0, 1, 2, 3} if path.endswith(("/present", "/online")) else set()
        )

        info = cpu_tools.get_cpu_info()

        self.assertTrue(info.features.amd_x3d)
        self.assertTrue(info.features.dual_ccd_x3d)
        self.assertTrue(info.features.x3d_mode_control)
        self.assertFalse(info.features.intel_hybrid)
        self.assertEqual(info.smt_siblings, {1, 3})

    @mock.patch("cpu_tools.get_x3d_mode_path", return_value=None)
    @mock.patch("cpu_tools.get_smt_siblings_of", return_value={1})
    @mock.patch("cpu_tools._parse_cpulist_file")
    @mock.patch("cpu_tools.detect_topology")
    def test_static_topology_is_detected_once_while_online_state_refreshes(
        self, topology, cpulist, _siblings, _path
    ):
        topology.return_value = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.UNIFORM, preferred={0, 1}
        )
        online_states = iter(({0, 1}, {0}))
        cpulist.side_effect = lambda path: (
            {0, 1} if path.endswith("/present") else next(online_states)
        )

        first = cpu_tools.get_cpu_info()
        second = cpu_tools.get_cpu_info()

        topology.assert_called_once_with()
        self.assertEqual(first.online, {0, 1})
        self.assertEqual(second.online, {0})
        self.assertEqual(second.offline, {1})

    @mock.patch(
        "cpu_tools.get_x3d_mode",
        return_value="future-mode",
    )
    def test_available_modes_come_from_detected_control_capability(
        self, _current
    ):
        topology = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1}, non_preferred={2, 3},
        )
        supported = cpu_tools.CPUInfo(
            topology=topology, present={0, 1, 2, 3},
            online={0, 1, 2, 3}, offline=set(), smt_siblings=set(),
            features=cpu_tools.CPUFeatures(
                asymmetric=True, amd_x3d=True, dual_ccd_x3d=True,
                x3d_mode_control=True,
            ),
        )
        unsupported = cpu_tools.CPUInfo(
            topology=cpu_tools.CPUTopology(), present={0}, online={0},
            offline=set(), smt_siblings=set(), features=cpu_tools.CPUFeatures(),
        )

        self.assertEqual(
            [mode.value for mode in cpu_tools.get_available_x3d_modes(supported)],
            ["cache", "frequency", "future-mode"],
        )
        self.assertEqual(
            [mode.label for mode in cpu_tools.get_available_x3d_modes(supported)],
            ["cache", "frequency", "future-mode"],
        )
        self.assertEqual(cpu_tools.get_available_x3d_modes(unsupported), ())

    @mock.patch("cpu_tools._run_helper", return_value=(True, "ok"))
    @mock.patch("cpu_tools.get_x3d_mode_path", return_value="/mode")
    @mock.patch("cpu_tools.get_cpu_info")
    def test_set_mode_accepts_new_safe_driver_values(self, cpu_info, _path, helper):
        cpu_info.return_value.features.x3d_mode_control = True
        self.assertEqual(cpu_tools.set_x3d_mode("future-mode_2"), (True, "ok"))
        helper.assert_called_once_with("x3d-mode", "future-mode_2")

    @mock.patch("cpu_tools._run_helper")
    @mock.patch("cpu_tools.get_x3d_mode_path", return_value="/mode")
    @mock.patch("cpu_tools.get_cpu_info")
    def test_mode_read_and_write_are_blocked_without_dual_x3d_flag(
        self, cpu_info, _path, helper
    ):
        cpu_info.return_value.features.x3d_mode_control = False

        self.assertIsNone(cpu_tools.get_x3d_mode())
        ok, message = cpu_tools.set_x3d_mode("future-mode")

        self.assertFalse(ok)
        self.assertIn("not available", message)
        helper.assert_not_called()

    @mock.patch("cpu_tools.os.path.realpath", side_effect=lambda path: f"/real/{path}")
    @mock.patch("cpu_tools.glob.glob")
    def test_discovers_bound_device_without_assuming_instance(self, glob_paths, _realpath):
        glob_paths.return_value = [
            "/sys/bus/platform/drivers/amd_x3d_vcache/AMDI0101:37/amd_x3d_mode"
        ]

        path = cpu_tools.get_x3d_mode_path()

        self.assertIn("AMDI0101:37", path)
        glob_paths.assert_called_once_with(
            "/sys/bus/platform/drivers/amd_x3d_vcache/*/amd_x3d_mode"
        )

    @mock.patch("cpu_tools.get_x3d_mode_path", return_value="/mode")
    def test_control_requires_asymmetric_amd_x3d(self, _path):
        amd = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1},
            non_preferred={2, 3},
        )
        intel = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.INTEL_HYBRID,
            preferred={0, 1},
            non_preferred={2, 3},
        )
        uniform = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1},
        )

        self.assertTrue(cpu_tools.has_dual_ccd_x3d_control(amd))
        self.assertFalse(cpu_tools.has_dual_ccd_x3d_control(intel))
        self.assertFalse(cpu_tools.has_dual_ccd_x3d_control(uniform))


if __name__ == "__main__":
    unittest.main()
