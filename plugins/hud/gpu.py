"""Optional installed NVIDIA driver API. No nvidia-smi process or dependency."""
import ctypes
import os


class GPU:
    def __init__(self):
        self.library = None
        if os.name != 'nt':
            return
        try:
            library = ctypes.WinDLL('nvml.dll')  # Default safe DLL search; no repository DLL loading.
            if library.nvmlInit_v2() != 0:
                return
            self.library = library
            self.device = ctypes.c_void_p()
            library.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            library.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            if library.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.device)) != 0:
                self.close()
        except (OSError, AttributeError):
            self.close()

    def read(self):
        if self.library:
            values = (ctypes.c_uint * 2)()
            if self.library.nvmlDeviceGetUtilizationRates(self.device, ctypes.byref(values)) == 0:
                return {'percent': min(100, values[0])}
        return None

    def close(self):
        if self.library:
            self.library.nvmlShutdown()
            self.library = None
