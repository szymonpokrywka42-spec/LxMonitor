#include <pybind11/pybind11.h>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include <chrono>

namespace py = pybind11;

class NetActivityEngine {
public:
    NetActivityEngine() {
        last_time = std::chrono::steady_clock::now();
        last_bytes = read_counters();
    }

    double get_usage() {
        try {
            auto all = compute_all_usage();
            double total = 0.0;
            for (const auto& [_, mbps] : all) total += mbps;
            last_total_mbps = total;
            return total;
        } catch (...) {
            return 0.0;
        }
    }

    py::dict get_all_usage() {
        py::dict out;
        try {
            auto all = compute_all_usage();
            for (const auto& [iface, mbps] : all) out[py::str(iface)] = mbps;
        } catch (...) {
            // leave empty dict
        }
        return out;
    }

    double get_total_mbps() const { return last_total_mbps; }
    double get_rx_mbps() const { return last_rx_mbps; }
    double get_tx_mbps() const { return last_tx_mbps; }

private:
    struct IfCounters {
        unsigned long long rx_bytes = 0;
        unsigned long long tx_bytes = 0;
    };

    std::chrono::steady_clock::time_point last_time;
    std::unordered_map<std::string, IfCounters> last_bytes;
    double last_total_mbps = 0.0;
    double last_rx_mbps = 0.0;
    double last_tx_mbps = 0.0;

    static bool is_virtual_iface(const std::string& iface) {
        static const std::vector<std::string> skip_prefixes = {
            "lo", "docker", "veth", "br-", "virbr", "vmnet", "tun", "tap", "zt", "tailscale"
        };
        for (const auto& p : skip_prefixes) {
            if (iface.rfind(p, 0) == 0) return true;
        }
        return false;
    }

    static std::string trim_copy(const std::string& s) {
        size_t b = 0;
        while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) b++;
        size_t e = s.size();
        while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) e--;
        return s.substr(b, e - b);
    }

    static std::unordered_map<std::string, IfCounters> read_counters() {
        std::unordered_map<std::string, IfCounters> out;
        std::ifstream f("/proc/net/dev");
        if (!f.is_open()) return out;

        std::string line;
        int line_no = 0;
        while (std::getline(f, line)) {
            line_no++;
            if (line_no <= 2) continue; // headers

            auto colon = line.find(':');
            if (colon == std::string::npos) continue;

            std::string iface = trim_copy(line.substr(0, colon));
            if (iface.empty() || is_virtual_iface(iface)) continue;

            std::string rest = line.substr(colon + 1);
            std::istringstream iss(rest);

            // /proc/net/dev:
            // rx_bytes rx_packets rx_errs rx_drop rx_fifo rx_frame rx_compressed rx_multicast
            // tx_bytes tx_packets tx_errs tx_drop tx_fifo tx_colls tx_carrier tx_compressed
            unsigned long long rx_bytes = 0, tx_bytes = 0;
            unsigned long long tmp = 0;
            if (!(iss >> rx_bytes)) continue;
            for (int i = 0; i < 7; ++i) {
                if (!(iss >> tmp)) break;
            }
            if (!(iss >> tx_bytes)) continue;

            out[iface] = {rx_bytes, tx_bytes};
        }
        return out;
    }

    std::unordered_map<std::string, double> compute_all_usage() {
        auto now = std::chrono::steady_clock::now();
        double elapsed_s = std::chrono::duration<double>(now - last_time).count();
        if (elapsed_s <= 0.0001) return {};

        auto current = read_counters();
        if (current.empty()) return {};

        std::unordered_map<std::string, double> out;
        double total_rx_bps = 0.0;
        double total_tx_bps = 0.0;

        for (const auto& [iface, cur] : current) {
            auto it = last_bytes.find(iface);
            if (it == last_bytes.end()) continue;

            unsigned long long d_rx = (cur.rx_bytes >= it->second.rx_bytes) ? (cur.rx_bytes - it->second.rx_bytes) : 0ULL;
            unsigned long long d_tx = (cur.tx_bytes >= it->second.tx_bytes) ? (cur.tx_bytes - it->second.tx_bytes) : 0ULL;

            double rx_bps = static_cast<double>(d_rx) / elapsed_s;
            double tx_bps = static_cast<double>(d_tx) / elapsed_s;
            double mbps = ((rx_bps + tx_bps) * 8.0) / 1'000'000.0;

            total_rx_bps += rx_bps;
            total_tx_bps += tx_bps;
            out[iface] = std::max(0.0, mbps);
        }

        last_rx_mbps = (total_rx_bps * 8.0) / 1'000'000.0;
        last_tx_mbps = (total_tx_bps * 8.0) / 1'000'000.0;
        last_total_mbps = last_rx_mbps + last_tx_mbps;

        last_bytes = std::move(current);
        last_time = now;
        return out;
    }
};

static NetActivityEngine global_net;

PYBIND11_MODULE(net, m) {
    m.def("get_usage", []() { return global_net.get_usage(); }, "Returns total network traffic in Mbps");
    m.def("get_all_usage", []() { return global_net.get_all_usage(); }, "Returns traffic per interface in Mbps");
    m.def("get_total_mbps", []() { return global_net.get_total_mbps(); }, "Returns cached total traffic in Mbps");
    m.def("get_rx_mbps", []() { return global_net.get_rx_mbps(); }, "Returns total RX in Mbps");
    m.def("get_tx_mbps", []() { return global_net.get_tx_mbps(); }, "Returns total TX in Mbps");
}
