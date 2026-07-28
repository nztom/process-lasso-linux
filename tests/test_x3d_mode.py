"""Tests for AMD dual-CCD X3D scheduler preference discovery."""
from __future__ import annotations

import unittest
from unittest import mock

import cpu_park


class X3DModeTests(unittest.TestCase):
    @mock.patch("cpu_park.os.path.realpath", side_effect=lambda path: f"/real/{path}")
    @mock.patch("cpu_park.glob.glob")
    def test_discovers_bound_device_without_assuming_instance(self, glob_paths, _realpath):
        glob_paths.return_value = [
            "/sys/bus/platform/drivers/amd_x3d_vcache/AMDI0101:37/amd_x3d_mode"
        ]

        path = cpu_park.get_x3d_mode_path()

        self.assertIn("AMDI0101:37", path)
        glob_paths.assert_called_once_with(
            "/sys/bus/platform/drivers/amd_x3d_vcache/*/amd_x3d_mode"
        )

    @mock.patch("cpu_park.get_x3d_mode_path", return_value="/mode")
    def test_control_requires_asymmetric_amd_x3d(self, _path):
        amd = cpu_park.CPUTopology(
            kind=cpu_park.TopologyKind.AMD_X3D,
            preferred={0, 1},
            non_preferred={2, 3},
        )
        intel = cpu_park.CPUTopology(
            kind=cpu_park.TopologyKind.INTEL_HYBRID,
            preferred={0, 1},
            non_preferred={2, 3},
        )
        uniform = cpu_park.CPUTopology(
            kind=cpu_park.TopologyKind.AMD_X3D,
            preferred={0, 1},
        )

        self.assertTrue(cpu_park.has_dual_ccd_x3d_control(amd))
        self.assertFalse(cpu_park.has_dual_ccd_x3d_control(intel))
        self.assertFalse(cpu_park.has_dual_ccd_x3d_control(uniform))


if __name__ == "__main__":
    unittest.main()
