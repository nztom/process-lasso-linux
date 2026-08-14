"""Optional NVIDIA per-process GPU-memory sampling via NVML."""
from __future__ import annotations

import logging


log = logging.getLogger(__name__)


class NvidiaGpuMemorySampler:
    """Return framebuffer memory attributed to each PID across all GPUs.

    NVML is optional: systems without the Python binding, an NVIDIA GPU, or
    permission to query accounting simply return an empty sample.
    """

    def __init__(self):
        self._nvml = None
        self._initialized = False
        self._last_utilization_timestamp: dict[int, int] = {}
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._initialized = True
        except Exception as exc:
            log.debug("NVIDIA GPU memory monitoring unavailable: %s", exc)

    def sample(self) -> tuple[dict[int, float], dict[int, int]]:
        if not self._initialized or self._nvml is None:
            return {}, {}

        nvml = self._nvml
        per_device_pid: dict[tuple[int, int], int] = {}
        utilization: dict[int, float] = {}
        try:
            for device_index in range(nvml.nvmlDeviceGetCount()):
                handle = nvml.nvmlDeviceGetHandleByIndex(device_index)
                utilization_getter = getattr(
                    nvml, "nvmlDeviceGetProcessUtilization", None
                )
                if utilization_getter is not None:
                    try:
                        samples = utilization_getter(
                            handle,
                            self._last_utilization_timestamp.get(device_index, 0),
                        )
                        if samples:
                            self._last_utilization_timestamp[device_index] = max(
                                int(sample.timeStamp) for sample in samples
                            )
                        for sample in samples:
                            pid = int(sample.pid)
                            # Sum work across GPUs, capped at a familiar percent.
                            utilization[pid] = min(
                                100.0,
                                utilization.get(pid, 0.0) + float(sample.smUtil),
                            )
                    except Exception:
                        pass
                processes = []
                for getter_name in (
                    "nvmlDeviceGetComputeRunningProcesses",
                    "nvmlDeviceGetGraphicsRunningProcesses",
                ):
                    getter = getattr(nvml, getter_name, None)
                    if getter is None:
                        continue
                    try:
                        processes.extend(getter(handle))
                    except Exception:
                        # Some driver/device combinations expose only one list.
                        continue
                for process in processes:
                    used = getattr(process, "usedGpuMemory", 0)
                    if not isinstance(used, int) or used <= 0:
                        continue
                    key = (device_index, int(process.pid))
                    # A C+G process appears in both NVML lists for one device.
                    per_device_pid[key] = max(per_device_pid.get(key, 0), used)
        except Exception as exc:
            log.debug("Could not sample NVIDIA GPU memory: %s", exc)
            return {}, {}

        totals: dict[int, int] = {}
        for (_device_index, pid), used in per_device_pid.items():
            totals[pid] = totals.get(pid, 0) + used
        return utilization, totals

    def close(self):
        if self._initialized and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False
