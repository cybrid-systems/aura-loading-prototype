// Same-shaped baselines for the Aura v0.2.0 hot-path probes.
// Times are milliseconds of wall clock, printed as @@key=value.
#include <chrono>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

static double ms_since(std::chrono::steady_clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

static std::int64_t spin(int work) {
    std::int64_t a = 0;
    for (int i = 0; i < work; ++i) a += i % 7;
    return a;
}

static int check_plan(int reps) {
    // Inputs depend on i so the loop cannot be deleted.
    int bad = 0;
    for (int i = 0; i < reps; ++i) {
        double cogx = 0.30 + (i % 80) * 0.005;
        double cogy = 0.40 + (i % 50) * 0.004;
        double util = 0.5 + (i % 10) * 0.01;
        int unplaced = i % 17 == 0 ? 1 : 0;
        double front = 1000.0 + (i % 30) * 100;
        double door = 3800;
        bool ok = unplaced <= 0 && cogx >= 0.30 && cogx <= 0.70 && cogy >= 0.40 && cogy <= 0.60 &&
                  util >= 0 && std::max(front, door) <= 18000;
        if (!ok) ++bad;
    }
    return bad;
}

int main(int argc, char** argv) {
    std::string mode = argc > 1 ? argv[1] : "all";
    int work = argc > 2 ? std::atoi(argv[2]) : 200000;
    int n = argc > 3 ? std::atoi(argv[3]) : 8;
    int reps = argc > 4 ? std::atoi(argv[4]) : 4000;
    if (mode == "spin" || mode == "all") {
        auto t0 = std::chrono::steady_clock::now();
        auto s = spin(work);
        std::cout << "@@cpp_spin_ms=" << ms_since(t0) << "\n@@cpp_spin_sum=" << s << "\n";
    }
    if (mode == "threads" || mode == "all") {
        auto t0 = std::chrono::steady_clock::now();
        std::vector<std::thread> ts;
        std::vector<std::int64_t> out(n);
        for (int i = 0; i < n; ++i)
            ts.emplace_back([&, i] { out[i] = spin(work); });
        for (auto& t : ts) t.join();
        std::int64_t s = 0;
        for (auto v : out) s += v;
        std::cout << "@@cpp_threads_ms=" << ms_since(t0) << "\n@@cpp_threads_sum=" << s
                  << "\n@@cpp_threads_n=" << n << "\n";
    }
    if (mode == "check" || mode == "all") {
        auto t0 = std::chrono::steady_clock::now();
        int bad = check_plan(reps);
        std::cout << "@@cpp_check_ms=" << ms_since(t0) << "\n@@cpp_check_bad=" << bad
                  << "\n@@cpp_check_reps=" << reps << "\n";
    }
    if (mode == "coord" || mode == "all") {
        int rounds = 40;
        auto t0 = std::chrono::steady_clock::now();
        int bad = 0;
        for (int r = 0; r < rounds; ++r) {
            std::vector<int> ids(n);
            std::vector<std::thread> ts;
            for (int i = 0; i < n; ++i)
                ts.emplace_back([&, i] { ids[i] = i; });
            for (auto& t : ts) t.join();
            int winner = ids[0];
            if (winner != 0) ++bad;
        }
        std::cout << "@@cpp_coord_ms=" << ms_since(t0) << "\n@@cpp_coord_bad=" << bad << "\n";
    }
    return 0;
}
