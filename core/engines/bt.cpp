#include <pybind11/pybind11.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace py = pybind11;
namespace fs = std::filesystem;

class BtActivityEngine {
public:
    BtActivityEngine() {
        last_time_ = std::chrono::steady_clock::now();
        last_bytes_ = read_all_bytes();
    }

    py::dict get_all_usage() {
        py::dict out;
        auto now = std::chrono::steady_clock::now();
        double elapsed_s = std::chrono::duration<double>(now - last_time_).count();
        if (elapsed_s <= 0.0001) elapsed_s = 0.0;

        auto current = read_all_bytes();
        for (const auto& [adapter, bytes] : current) {
            const auto meta = read_adapter_meta(adapter);

            double rx_mbps = 0.0;
            double tx_mbps = 0.0;
            auto it = last_bytes_.find(adapter);
            if (it != last_bytes_.end() && elapsed_s > 0.0) {
                const auto& prev = it->second;
                const auto d_rx = (bytes.rx_bytes >= prev.rx_bytes) ? (bytes.rx_bytes - prev.rx_bytes) : 0ULL;
                const auto d_tx = (bytes.tx_bytes >= prev.tx_bytes) ? (bytes.tx_bytes - prev.tx_bytes) : 0ULL;
                const double rx_bps = static_cast<double>(d_rx) / elapsed_s;
                const double tx_bps = static_cast<double>(d_tx) / elapsed_s;
                rx_mbps = std::max(0.0, (rx_bps * 8.0) / 1'000'000.0);
                tx_mbps = std::max(0.0, (tx_bps * 8.0) / 1'000'000.0);
            }

            py::dict item;
            item["name"] = py::str(meta.name.empty() ? adapter : meta.name);
            item["rx_mbps"] = rx_mbps;
            item["tx_mbps"] = tx_mbps;
            item["mbps"] = rx_mbps + tx_mbps;
            item["address"] = py::str(meta.address);
            item["driver"] = py::str(meta.driver);
            item["slot"] = py::str(meta.slot);
            item["vendor_id"] = py::str(meta.vendor_id);
            item["device_id"] = py::str(meta.device_id);
            item["rfkill_blocked"] = py::bool_(meta.rfkill_blocked);

            out[py::str(adapter)] = item;
        }

        last_time_ = now;
        last_bytes_ = std::move(current);
        return out;
    }

private:
    struct Bytes {
        unsigned long long rx_bytes = 0;
        unsigned long long tx_bytes = 0;
    };

    struct AdapterMeta {
        std::string name;
        std::string address;
        std::string driver;
        std::string slot;
        std::string vendor_id;
        std::string device_id;
        bool rfkill_blocked = false;
    };

    std::chrono::steady_clock::time_point last_time_;
    std::unordered_map<std::string, Bytes> last_bytes_;

    static std::string read_text(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return {};
        std::string s;
        std::getline(f, s);
        return s;
    }

    static std::string read_all_text(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return {};
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    }

    static unsigned long long read_u64(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return 0ULL;
        unsigned long long v = 0ULL;
        f >> v;
        return v;
    }

    static std::unordered_map<std::string, Bytes> read_all_bytes() {
        std::unordered_map<std::string, Bytes> out;
        const fs::path base("/sys/class/bluetooth");
        if (!fs::exists(base)) return out;

        for (const auto& e : fs::directory_iterator(base)) {
            if (!e.is_directory()) continue;
            const std::string adapter = e.path().filename().string();
            if (adapter.rfind("hci", 0) != 0) continue;

            const fs::path stat_dir = e.path() / "statistics";
            if (!fs::exists(stat_dir)) continue;
            Bytes b;
            b.rx_bytes = read_u64(stat_dir / "rx_bytes");
            b.tx_bytes = read_u64(stat_dir / "tx_bytes");
            out[adapter] = b;
        }
        return out;
    }

    static bool parse_rfkill_for_adapter(const std::string& adapter) {
        const fs::path root("/sys/class/rfkill");
        if (!fs::exists(root)) return false;
        for (const auto& e : fs::directory_iterator(root)) {
            if (!e.is_directory()) continue;
            const auto name = read_text(e.path() / "name");
            if (name.find(adapter) == std::string::npos) continue;
            const auto soft = read_text(e.path() / "soft");
            const auto hard = read_text(e.path() / "hard");
            return (soft == "1" || hard == "1");
        }
        return false;
    }

    static AdapterMeta read_adapter_meta(const std::string& adapter) {
        AdapterMeta m;
        const fs::path base = fs::path("/sys/class/bluetooth") / adapter;
        const fs::path dev = base / "device";

        m.name = read_text(dev / "name");
        m.address = read_text(base / "address");
        m.vendor_id = read_text(dev / "vendor");
        m.device_id = read_text(dev / "device");
        m.rfkill_blocked = parse_rfkill_for_adapter(adapter);

        try {
            const fs::path driver_link = dev / "driver";
            if (fs::is_symlink(driver_link)) {
                m.driver = fs::read_symlink(driver_link).filename().string();
            }
        } catch (...) {
        }

        const auto uevent = read_all_text(dev / "uevent");
        std::istringstream iss(uevent);
        std::string line;
        while (std::getline(iss, line)) {
            if (line.rfind("PCI_SLOT_NAME=", 0) == 0) {
                m.slot = line.substr(std::string("PCI_SLOT_NAME=").size());
                break;
            }
        }

        return m;
    }
};

static BtActivityEngine global_bt;

PYBIND11_MODULE(bt, m) {
    m.doc() = "Bluetooth adapter telemetry engine";
    m.def("get_all_usage", []() { return global_bt.get_all_usage(); }, "Returns Bluetooth adapter telemetry");
}
