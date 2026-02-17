#include <pybind11/pybind11.h>
#include <fstream>
#include <string>
#include <filesystem>
#include <vector>
#include <glob.h> // Potrzebne do obsługi "*" w ścieżkach
#include <cctype>

namespace py = pybind11;
namespace fs = std::filesystem;

class GpuOthers {
public:
    GpuOthers() {
        find_gpu_path();
    }

    double get_usage() {
        if (usage_path.empty()) {
            find_gpu_path();
            if (usage_path.empty()) return 0.0;
        }

        std::ifstream file(usage_path);
        if (!file.is_open()) {
            // Path may disappear/change after driver reset; try to rediscover once.
            usage_path.clear();
            find_gpu_path();
            if (usage_path.empty()) return 0.0;
            file.open(usage_path);
        }
        std::string line;
        if (std::getline(file, line)) {
            try {
                std::string cleaned;
                cleaned.reserve(line.size());
                for (char c : line) {
                    if (std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == '-') cleaned.push_back(c);
                    else if (!cleaned.empty()) break;
                }
                if (cleaned.empty()) return 0.0;
                double v = std::stod(cleaned);
                if (v < 0.0) return 0.0;
                if (v > 100.0) return 100.0;
                return v;
            } catch (...) {
                return 0.0;
            }
        }
        return 0.0;
    }

private:
    std::string usage_path = "";

    void find_gpu_path() {
        // 1. Sprawdzenie sztywnych ścieżek (najczęstsze)
        std::vector<std::string> hard_targets = {
            "/sys/class/drm/card0/device/gpu_busy_percent",
            "/sys/class/drm/card1/device/gpu_busy_percent",
            "/sys/class/drm/card0/device/usage",
            "/sys/kernel/debug/dri/0/amdgpu_pm_info"
        };

        for (const auto& t : hard_targets) {
            if (fs::exists(t)) {
                usage_path = t;
                return;
            }
        }

        // 2. Dynamiczne szukanie przez glob (obsługa hwmon*/device/...)
        glob_t glob_result;
        const char* pattern = "/sys/class/hwmon/hwmon*/device/gpu_busy_percent";
        
        if (glob(pattern, GLOB_TILDE, NULL, &glob_result) == 0) {
            if (glob_result.gl_pathc > 0) {
                usage_path = std::string(glob_result.gl_pathv[0]);
            }
            globfree(&glob_result);
        }

        // 3. Generic DRM scan across all cards.
        for (int i = 0; i < 16; ++i) {
            const std::string p1 = "/sys/class/drm/card" + std::to_string(i) + "/device/gpu_busy_percent";
            const std::string p2 = "/sys/class/drm/card" + std::to_string(i) + "/device/usage";
            if (fs::exists(p1)) {
                usage_path = p1;
                return;
            }
            if (fs::exists(p2)) {
                usage_path = p2;
                return;
            }
        }
    }
};

static GpuOthers global_gpu;

PYBIND11_MODULE(gpu_others, m) {
    m.def("get_usage", []() { return global_gpu.get_usage(); });
}
