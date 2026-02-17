#include <pybind11/pybind11.h>
#include <fstream>
#include <string>
#include <vector>
#include <numeric>
#include <unistd.h>


namespace py = pybind11;

class CpuSensing {
public:
    CpuSensing() {
        // Pierwszy pomiar przy starcie
        read_stats(last_total, last_idle_total);
    }

    double get_usage() {
        unsigned long long total = 0, idle_total = 0;
        if (!read_stats(total, idle_total)) return last_value;

        // Obliczamy różnice między pomiarami
        unsigned long long total_diff = (total >= last_total) ? (total - last_total) : 0ULL;
        unsigned long long idle_diff = (idle_total >= last_idle_total) ? (idle_total - last_idle_total) : 0ULL;

        // Zabezpieczenie przed dzieleniem przez zero
        double usage = 0.0;
        if (total_diff > 0) {
            usage = 100.0 * (1.0 - static_cast<double>(idle_diff) / total_diff);
        }

        // Zapisujemy obecne wartości jako "poprzednie" dla następnego ticku
        last_total = total;
        last_idle_total = idle_total;

        if (usage < 0.0) usage = 0.0;
        if (usage > 100.0) usage = 100.0;
        last_value = usage;
        return last_value;
    }

private:
    unsigned long long last_total = 0;
    unsigned long long last_idle_total = 0;
    double last_value = 0.0;

    bool read_stats(unsigned long long &total, unsigned long long &idle_total) {
        std::ifstream file("/proc/stat");
        std::string cpu_label;
        unsigned long long user = 0, nice = 0, system = 0, idle = 0;
        unsigned long long iowait = 0, irq = 0, softirq = 0, steal = 0;
        if (!(file >> cpu_label >> user >> nice >> system >> idle)) return false;
        // Optional fields depending on kernel.
        file >> iowait >> irq >> softirq >> steal;
        total = user + nice + system + idle + iowait + irq + softirq + steal;
        idle_total = idle + iowait;
        return total > 0;
    }
};

static CpuSensing global_cpu;

PYBIND11_MODULE(cpu, m) {
    m.def("get_usage", []() { return global_cpu.get_usage(); }, "Returns total CPU usage %");
}
