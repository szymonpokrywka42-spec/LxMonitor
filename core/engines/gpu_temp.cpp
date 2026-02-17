#include <pybind11/pybind11.h>
#include <fstream>
#include <string>
#include <filesystem>
#include <vector>
#include <algorithm>

namespace py = pybind11;
namespace fs = std::filesystem;

class GpuTempEngine {
public:
    double get_usage() {
        // 1. Najpierw szukamy tempów GPU przez /sys/class/drm/card*/device/hwmon/hwmon*/temp*_input
        double best = scan_drm_hwmon();
        if (best > 0.0) return best;

        // 2. Fallback: globalne hwmon z nazwą sterownika GPU.
        best = scan_global_hwmon();
        if (best > 0.0) return best;

        return 0.0;
    }

private:
    static bool is_temp_input_file(const fs::path& p) {
        auto name = p.filename().string();
        return name.rfind("temp", 0) == 0 && name.find("_input") != std::string::npos;
    }

    static double read_temp_file(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return 0.0;
        double v = 0.0;
        if (!(f >> v)) return 0.0;
        // Najczęściej millicelsius
        if (v > 1000.0) v /= 1000.0;
        if (v < 0.0 || v > 150.0) return 0.0;
        return v;
    }

    static std::string read_text_file(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return "";
        std::string s;
        std::getline(f, s);
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return s;
    }

    double scan_drm_hwmon() {
        fs::path drm_base("/sys/class/drm");
        if (!fs::exists(drm_base)) return 0.0;

        double max_temp = 0.0;
        try {
            for (const auto& card_entry : fs::directory_iterator(drm_base)) {
                auto card_name = card_entry.path().filename().string();
                if (card_name.rfind("card", 0) != 0) continue;

                fs::path hwmon_dir = card_entry.path() / "device" / "hwmon";
                if (!fs::exists(hwmon_dir)) continue;

                for (const auto& hwmon_entry : fs::directory_iterator(hwmon_dir)) {
                    if (!fs::is_directory(hwmon_entry.path())) continue;
                    for (const auto& f : fs::directory_iterator(hwmon_entry.path())) {
                        if (!fs::is_regular_file(f.path())) continue;
                        if (!is_temp_input_file(f.path())) continue;
                        double t = read_temp_file(f.path());
                        if (t > max_temp) max_temp = t;
                    }
                }
            }
        } catch (...) {
            return max_temp;
        }
        return max_temp;
    }

    double scan_global_hwmon() {
        fs::path hwmon_base("/sys/class/hwmon");
        if (!fs::exists(hwmon_base)) return 0.0;

        double max_temp = 0.0;
        try {
            for (const auto& entry : fs::directory_iterator(hwmon_base)) {
                if (!fs::is_directory(entry.path())) continue;

                std::string driver = read_text_file(entry.path() / "name");
                if (driver.empty()) continue;

                bool looks_like_gpu =
                    driver.find("amdgpu") != std::string::npos ||
                    driver.find("nouveau") != std::string::npos ||
                    driver.find("nvidia") != std::string::npos ||
                    driver.find("xe") != std::string::npos ||
                    driver.find("i915") != std::string::npos;

                if (!looks_like_gpu) continue;

                for (const auto& f : fs::directory_iterator(entry.path())) {
                    if (!fs::is_regular_file(f.path())) continue;
                    if (!is_temp_input_file(f.path())) continue;
                    double t = read_temp_file(f.path());
                    if (t > max_temp) max_temp = t;
                }
            }
        } catch (...) {
            return max_temp;
        }
        return max_temp;
    }
};

static GpuTempEngine global_gpu_temp;

PYBIND11_MODULE(gpu_temp, m) {
    m.def("get_usage", []() { return global_gpu_temp.get_usage(); }, "Returns GPU temperature in Celsius");
}
