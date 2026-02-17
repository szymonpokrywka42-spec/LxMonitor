#include <pybind11/pybind11.h>
#include <fstream>
#include <string>
#include <sstream>
#include <cctype>
#include <unordered_map>

namespace py = pybind11;

class RamSensing {
public:
    double get_usage() {
        std::ifstream file("/proc/meminfo");
        if (!file.is_open()) return 0.0;

        std::string line;
        long long total = 0;
        long long available = -1;
        std::unordered_map<std::string, long long> mem;

        // Linux przechowuje to w kB (kilobajtach)
        while (std::getline(file, line)) {
            auto key_end = line.find(':');
            if (key_end == std::string::npos) continue;
            std::string key = line.substr(0, key_end);
            long long val = parse_value(line);
            mem[key] = val;

            if (key == "MemTotal") total = val;
            else if (key == "MemAvailable") available = val;
        }

        if (total <= 0) return 0.0;

        // Older kernels can miss MemAvailable.
        if (available < 0) {
            const long long mem_free = mem.count("MemFree") ? mem["MemFree"] : 0;
            const long long buffers = mem.count("Buffers") ? mem["Buffers"] : 0;
            const long long cached = mem.count("Cached") ? mem["Cached"] : 0;
            const long long sreclaim = mem.count("SReclaimable") ? mem["SReclaimable"] : 0;
            const long long shmem = mem.count("Shmem") ? mem["Shmem"] : 0;
            available = mem_free + buffers + cached + sreclaim - shmem;
            if (available < 0) available = 0;
        }

        // Procentowe użycie RAM (to co faktycznie zajęte przez apki)
        double used = static_cast<double>(total - available);
        double pct = (used / static_cast<double>(total)) * 100.0;
        if (pct < 0.0) return 0.0;
        if (pct > 100.0) return 100.0;
        return pct;
    }

private:
    long long parse_value(const std::string& line) {
        std::stringstream ss;
        // Skipujemy nazwę (np. "MemTotal:") i wyciągamy liczbę
        for (char c : line) {
            if (isdigit(c)) ss << c;
            else if (ss.str().length() > 0 && !isdigit(c)) break;
        }
        long long val = 0;
        ss >> val;
        return val;
    }
};

static RamSensing global_ram;

PYBIND11_MODULE(ram, m) {
    m.def("get_usage", []() { return global_ram.get_usage(); }, "Returns RAM usage %");
}
