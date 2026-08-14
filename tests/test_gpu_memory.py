import unittest
from types import SimpleNamespace

from gpu_memory import NvidiaGpuMemorySampler


class _FakeNvml:
    @staticmethod
    def nvmlDeviceGetCount():
        return 2

    @staticmethod
    def nvmlDeviceGetHandleByIndex(index):
        return index

    @staticmethod
    def nvmlDeviceGetProcessUtilization(handle, _timestamp):
        return [SimpleNamespace(pid=42, smUtil=25 + handle, timeStamp=100 + handle)]

    @staticmethod
    def nvmlDeviceGetComputeRunningProcesses(handle):
        return [SimpleNamespace(pid=42, usedGpuMemory=(handle + 1) * 100)]

    @staticmethod
    def nvmlDeviceGetGraphicsRunningProcesses(handle):
        return [
            SimpleNamespace(pid=42, usedGpuMemory=(handle + 1) * 100),
            SimpleNamespace(pid=7, usedGpuMemory=50),
        ]


class NvidiaGpuMemorySamplerTests(unittest.TestCase):
    def test_combines_gpu_usage_without_double_counting_c_plus_g_processes(self):
        sampler = NvidiaGpuMemorySampler.__new__(NvidiaGpuMemorySampler)
        sampler._nvml = _FakeNvml()
        sampler._initialized = True
        sampler._last_utilization_timestamp = {}

        utilization, memory = sampler.sample()

        self.assertEqual(utilization, {42: 51.0})
        self.assertEqual(memory, {42: 300, 7: 100})
        self.assertEqual(sampler._last_utilization_timestamp, {0: 100, 1: 101})

    def test_unavailable_nvml_returns_empty_metrics(self):
        sampler = NvidiaGpuMemorySampler.__new__(NvidiaGpuMemorySampler)
        sampler._nvml = None
        sampler._initialized = False
        sampler._last_utilization_timestamp = {}

        self.assertEqual(sampler.sample(), ({}, {}))
