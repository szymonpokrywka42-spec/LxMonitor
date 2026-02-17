#include <pybind11/pybind11.h>
#include <nvml.h>
#include <string>

namespace py = pybind11;

class NvidiaSensing {
public:
    NvidiaSensing() {
        // Inicjalizacja biblioteki NVML
        nvmlReturn_t result = nvmlInit();
        if (result == NVML_SUCCESS) {
            // Pobieramy uchwyt do pierwszej wykrytej karty (index 0)
            nvmlReturn_t handle_res = nvmlDeviceGetHandleByIndex(0, &device);
            initialized = (handle_res == NVML_SUCCESS);
        } else {
            initialized = false;
        }
    }

    ~NvidiaSensing() {
        if (initialized) {
            nvmlShutdown();
        }
    }

    double get_usage() {
        if (!initialized) return 0.0;

        nvmlUtilization_t utilization;
        // Pobieramy stopień wykorzystania GPU (rdzeni) i pamięci
        nvmlReturn_t result = nvmlDeviceGetUtilizationRates(device, &utilization);
        
        if (result == NVML_SUCCESS) {
            // Zwracamy tylko obciążenie rdzeni GPU
            double v = static_cast<double>(utilization.gpu);
            if (v < 0.0) return 0.0;
            if (v > 100.0) return 100.0;
            return v;
        }
        return 0.0;
    }

private:
    nvmlDevice_t device;
    bool initialized = false;
};

// Singleton, żeby nie męczyć sterownika ciągłą inicjalizacją
static NvidiaSensing global_nvidia;

PYBIND11_MODULE(gpu_nvidia, m) {
    m.doc() = "LxMonitor NVIDIA GPU Engine via NVML";
    m.def("get_usage", []() { return global_nvidia.get_usage(); }, "Returns NVIDIA GPU load %");
}
