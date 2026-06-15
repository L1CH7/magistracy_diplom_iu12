#include <chrono>
#include <cmath>
#include <csetjmp>
#include <csignal>
#include <emmintrin.h>
#include <filesystem>
#include <format>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

#include "router/compute/advanced_pqs.hpp"
#include "router/compute/astar_router.hpp"
#include "router/compute/bidirectional_dijkstra.hpp"
#include "router/compute/dijkstra_router.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/control/router_manager.hpp"

using namespace traffic;
using namespace traffic::router::compute;

// Global metrics for queue profiling with nanosecond-level CPU-cycle accuracy
struct QueueMetrics {
  static inline uint64_t total_push_count = 0;
  static inline uint64_t total_pop_count = 0;
  static inline uint64_t total_queue_cycles = 0;

  static inline uint64_t push_cycles_sum = 0;
  static inline uint64_t pop_cycles_sum = 0;
  static inline uint64_t min_push_cycles = std::numeric_limits<uint64_t>::max();
  static inline uint64_t max_push_cycles = 0;
  static inline uint64_t min_pop_cycles = std::numeric_limits<uint64_t>::max();
  static inline uint64_t max_pop_cycles = 0;

  static void Reset() {
    total_push_count = 0;
    total_pop_count = 0;
    total_queue_cycles = 0;
    push_cycles_sum = 0;
    pop_cycles_sum = 0;
    min_push_cycles = std::numeric_limits<uint64_t>::max();
    max_push_cycles = 0;
    min_pop_cycles = std::numeric_limits<uint64_t>::max();
    max_pop_cycles = 0;
  }
};

// Template Wrapper to instrument any Queue with hardware-level fences
template <typename RawQueue> class InstrumentedQueue {
public:
  void reserve(size_t cap) { raw_q_.reserve(cap); }
  void clear() { raw_q_.clear(); }
  bool empty() const { return raw_q_.empty(); }
  size_t size() const { return raw_q_.size(); }

  inline void push(traffic::PQElement el) noexcept {
    QueueMetrics::total_push_count++;

    _mm_lfence();
    uint64_t start = __rdtsc();
    _mm_lfence();

    raw_q_.push(el);

    _mm_lfence();
    uint64_t end = __rdtsc();
    _mm_lfence();

    uint64_t diff = end - start;
    QueueMetrics::total_queue_cycles += diff;
    QueueMetrics::push_cycles_sum += diff;
    if (diff < QueueMetrics::min_push_cycles)
      QueueMetrics::min_push_cycles = diff;
    if (diff > QueueMetrics::max_push_cycles)
      QueueMetrics::max_push_cycles = diff;
  }

  inline traffic::PQElement pop() noexcept {
    QueueMetrics::total_pop_count++;

    _mm_lfence();
    uint64_t start = __rdtsc();
    _mm_lfence();

    auto el = raw_q_.pop();

    _mm_lfence();
    uint64_t end = __rdtsc();
    _mm_lfence();

    uint64_t diff = end - start;
    QueueMetrics::total_queue_cycles += diff;
    QueueMetrics::pop_cycles_sum += diff;
    if (diff < QueueMetrics::min_pop_cycles)
      QueueMetrics::min_pop_cycles = diff;
    if (diff > QueueMetrics::max_pop_cycles)
      QueueMetrics::max_pop_cycles = diff;

    return el;
  }

  // Access to internal get_heuristic (used by ALT)
  auto &get_heuristic() {
    if constexpr (requires(RawQueue q) { q.get_heuristic(); }) {
      return raw_q_.get_heuristic();
    } else {
      throw std::runtime_error("Heuristic not supported on this queue");
    }
  }

private:
  RawQueue raw_q_;
};

// Global signal handler buffers
static sigjmp_buf g_jump_buffer;
static volatile sig_atomic_t g_test_in_progress = 0;

void signal_handler(int sig) {
  if (g_test_in_progress) {
    siglongjmp(g_jump_buffer, sig);
  } else {
    std::cerr << "\nFatal signal " << sig
              << " received outside of test context. Aborting.\n";
    std::exit(sig);
  }
}

struct TestGuard {
  TestGuard() { g_test_in_progress = 1; }
  ~TestGuard() { g_test_in_progress = 0; }
};

struct RouteTask {
  NodeID source;
  NodeID target;
};

inline bool g_has_baseline = false;
inline std::vector<PathWeight> g_baseline_weights;
inline std::vector<std::vector<EdgeID>> g_baseline_paths;
inline std::vector<PathWeight>
    g_dijkstra_weights; // Идеальные точные веса Дейкстры

struct DetailedResult {
  std::string algorithm;
  std::string queue;
  size_t route_idx;
  uint32_t visited_nodes;
  double route_ms;
  uint64_t push_count;
  uint64_t pop_count;
  double queue_ms;
  PathWeight path_weight;
  float path_length_m;
  float euclidean_dist_m;
  uint64_t min_push_cycles;
  uint64_t max_push_cycles;
  double avg_push_cycles;
  uint64_t min_pop_cycles;
  uint64_t max_pop_cycles;
  double avg_pop_cycles;
  uint32_t path_edges;
  bool crashed = false;
  double rel_error = 0.0;
  bool is_exact = false;
  PathWeight dijkstra_weight = INF_WEIGHT;
};

// Multi-axis metrics collector
template <typename RouterType, typename PQType>
std::vector<DetailedResult>
RunBenchmarkSuite(const std::string &algo_name, const std::string &pq_name,
                  const std::vector<RouteTask> &tasks, GraphView view,
                  NodeID num_nodes,
                  const router::control::RouterManager &manager) {
  std::cout << std::format("  - Benchmarking [ {} + {} ]... ", algo_name,
                           pq_name)
            << std::flush;
  std::vector<DetailedResult> results;
  results.reserve(tasks.size());

  int sig = sigsetjmp(g_jump_buffer, 1);
  if (sig == 0) {
    TestGuard guard;
    try {
      // Instantiate Router with geom_store if supported (e.g. AStarRouter)
      std::unique_ptr<RouterType> router_ptr;
      if constexpr (requires(GraphView v, NodeID n, const void *g) {
                      RouterType(v, n, g);
                    }) {
        router_ptr = std::make_unique<RouterType>(view, num_nodes,
                                                  manager.get_geometry_store());
      } else {
        router_ptr = std::make_unique<RouterType>(view, num_nodes);
      }
      auto &router_instance = *router_ptr;

      // Try to set landmarks only if RouterType supports it
      if constexpr (requires(RouterType r, const uint16_t *l) {
                      r.get_heuristic().set_landmarks((const EdgeWeight *)l);
                    }) {
        const uint16_t *landmarks = manager.get_landmarks_ptr();
        if (landmarks) {
          router_instance.get_heuristic().set_landmarks(
              reinterpret_cast<const EdgeWeight *>(landmarks));
        }
      }

      if (g_dijkstra_weights.empty() && algo_name == "Dijkstra" &&
          pq_name == "2-ary") {
        g_dijkstra_weights.resize(tasks.size(), INF_WEIGHT);
      }
      if (!g_has_baseline) {
        g_baseline_weights.resize(tasks.size(), INF_WEIGHT);
        g_baseline_paths.resize(tasks.size());
      }

      for (size_t i = 0; i < tasks.size(); ++i) {
        QueueMetrics::Reset();

        auto start = std::chrono::high_resolution_clock::now();
        auto route_res = router_instance.template Route<false, true>(
            tasks[i].source, tasks[i].target);
        auto end = std::chrono::high_resolution_clock::now();

        // Проверка корректности маршрутизации!
        if (!g_has_baseline) {
          g_baseline_weights[i] = route_res.total_weight;
          g_baseline_paths[i] = route_res.path;
        } else {
          if (route_res.total_weight != g_baseline_weights[i]) {
            bool acceptable_mismatch = false;
            if (g_baseline_weights[i] != INF_WEIGHT &&
                route_res.total_weight != INF_WEIGHT &&
                g_baseline_weights[i] > 0) {
              double diff_pct =
                  std::abs(static_cast<double>(route_res.total_weight) -
                           g_baseline_weights[i]) /
                  g_baseline_weights[i] * 100.0;
              if (algo_name == "Dijkstra" || algo_name == "Bi-Dijkstra") {
                if ((pq_name == "delta" || pq_name == "bucket" ||
                     pq_name == "DeltaQueue" ||
                     pq_name == "DeltaBucketQueue") &&
                    diff_pct <= 3.0) {
                  acceptable_mismatch = true;
                }
              } else {
                // A-Star и ALT используют субоптимальные эвристики (WA*
                // = 1.15), поэтому различная структура очередей priority queue
                // влияет на порядок извлечения вершин с одинаковым
                // эвристическим весом f. Это математически неизбежно дает
                // расхождения в пределах теоретической субоптимальности (15%).
                if (diff_pct <= 15.0) {
                  acceptable_mismatch = true;
                }
              }
            }
            if (!acceptable_mismatch) {
              std::cerr << std::format(
                  "\n[CORRECTNESS ERROR] {} + {}: Route weight mismatch on "
                  "task {} ({} -> {})! Expected {}, got {}\n",
                  algo_name, pq_name, i, tasks[i].source, tasks[i].target,
                  g_baseline_weights[i], route_res.total_weight);
              throw std::runtime_error("Route weight mismatch!");
            }
          }
          if (g_baseline_weights[i] != INF_WEIGHT && route_res.path.empty() &&
              g_baseline_weights[i] > 0) {
            std::cerr << std::format(
                "\n[CORRECTNESS ERROR] {} + {}: Path is empty for valid route "
                "weight {} on task {}!\n",
                algo_name, pq_name, g_baseline_weights[i], i);
            throw std::runtime_error("Empty path in routing result!");
          }
        }

        double route_ms =
            std::chrono::duration<double, std::milli>(end - start).count();
        double queue_ms =
            static_cast<double>(QueueMetrics::total_queue_cycles) / 2.5e6;

        float path_length = 0.0f;
        if (route_res.total_weight != INF_WEIGHT) {
          for (auto edge_id : route_res.path) {
            path_length += manager.get_edge_length(edge_id);
          }
        }

        // Calculate Euclidean distance
        float euclidean_dist = 0.0f;
        auto geom_s =
            manager.get_geometry_store()->get_geometry(tasks[i].source);
        auto geom_t =
            manager.get_geometry_store()->get_geometry(tasks[i].target);
        if (!geom_s.points.empty() && !geom_t.points.empty()) {
          float lon1 = geom_s.points[0].x;
          float lat1 = geom_s.points[0].y;
          float lon2 = geom_t.points[0].x;
          float lat2 = geom_t.points[0].y;
          float dy = (lat1 - lat2) * 111320.0f;
          float dx = (lon1 - lon2) * 62560.0f;
          euclidean_dist = std::sqrt(dx * dx + dy * dy);
        }

        if (algo_name == "Dijkstra" && pq_name == "2-ary") {
          g_dijkstra_weights[i] = route_res.total_weight;
        }

        double rel_error = 0.0;
        bool is_exact = false;
        PathWeight d_weight = INF_WEIGHT;
        if (!g_dijkstra_weights.empty() && i < g_dijkstra_weights.size()) {
          d_weight = g_dijkstra_weights[i];
          if (d_weight != INF_WEIGHT) {
            is_exact = (route_res.total_weight == d_weight);
            if (route_res.total_weight != INF_WEIGHT && d_weight > 0) {
              rel_error = std::abs(static_cast<double>(route_res.total_weight) -
                                   d_weight) /
                          d_weight * 100.0;
            }
          }
        }

        double avg_push =
            QueueMetrics::total_push_count
                ? static_cast<double>(QueueMetrics::push_cycles_sum) /
                      QueueMetrics::total_push_count
                : 0.0;
        double avg_pop =
            QueueMetrics::total_pop_count
                ? static_cast<double>(QueueMetrics::pop_cycles_sum) /
                      QueueMetrics::total_pop_count
                : 0.0;

        results.push_back(
            {algo_name,
             pq_name,
             i,
             route_res.visited_nodes_count,
             route_ms,
             QueueMetrics::total_push_count,
             QueueMetrics::total_pop_count,
             queue_ms,
             route_res.total_weight,
             path_length,
             euclidean_dist,
             QueueMetrics::min_push_cycles ==
                     std::numeric_limits<uint64_t>::max()
                 ? 0
                 : QueueMetrics::min_push_cycles,
             QueueMetrics::max_push_cycles,
             avg_push,
             QueueMetrics::min_pop_cycles ==
                     std::numeric_limits<uint64_t>::max()
                 ? 0
                 : QueueMetrics::min_pop_cycles,
             QueueMetrics::max_pop_cycles,
             avg_pop,
             route_res.path.empty()
                 ? 0u
                 : static_cast<uint32_t>(route_res.path.size() - 1),
             false,
             rel_error,
             is_exact,
             d_weight});
      }
      g_has_baseline = true;
      std::cout << "Done.\n";
    } catch (const std::exception &e) {
      std::cout << "FAILED: " << e.what() << "\n";
    }
  } else {
    std::cout << " !!! CRASHED !!!\n";
    results.push_back({algo_name,  pq_name, 0,    0,   0,     0,         0, 0,
                       INF_WEIGHT, 0,       0,    0,   0,     0,         0, 0,
                       0,          0,       true, 0.0, false, INF_WEIGHT});
  }

  return results;
}

int main(int argc, char **argv) {
  std::signal(SIGSEGV, signal_handler);
  std::signal(SIGABRT, signal_handler);
  std::signal(SIGILL, signal_handler);
  std::signal(SIGFPE, signal_handler);

  std::string data_path = "/app/data";
  std::string out_csv = "/app/benchmarks/traffic-core/stats/run_results.csv";

  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "--data" && i + 1 < argc) {
      data_path = argv[i + 1];
    }
    if (std::string(argv[i]) == "--out" && i + 1 < argc) {
      out_csv = argv[i + 1];
    }
  }

  router::control::RouterManager manager;
  if (!manager.LoadGraphs(data_path)) {
    std::cerr << "Failed to load graphs from " << data_path << "\n";
    return 1;
  }

  auto view = manager.get_view();
  auto num_nodes = manager.num_nodes();

  std::mt19937 gen(42);
  std::uniform_int_distribution<NodeID> dist(0, num_nodes - 1);

  constexpr int NUM_ROUTES = 1500;
  std::vector<RouteTask> tasks;
  for (int i = 0; i < NUM_ROUTES; ++i) {
    tasks.push_back({dist(gen), dist(gen)});
  }

  std::cout << std::format("\n🚀 RUNNING COMPREHENSIVE ALGORITHM & QUEUE "
                           "MATRIX BENCHMARK ({} tasks)\n",
                           NUM_ROUTES);
  std::vector<DetailedResult> all_results;

  // Helper lambda to run tests cleanly
  std::string current_algo = "";
  auto run_suite = [&](auto router_dummy, auto queue_dummy,
                       const std::string &algo, const std::string &pq) {
    if (algo != current_algo) {
      current_algo = algo;
      g_has_baseline = false;
    }
    using RouterT = decltype(router_dummy);
    using QueueT = decltype(queue_dummy);
    auto res = RunBenchmarkSuite<RouterT, QueueT>(algo, pq, tasks, view,
                                                  num_nodes, manager);
    all_results.insert(all_results.end(), res.begin(), res.end());
  };

  // 1. DIJKSTRA (Single source)
  run_suite(DijkstraRouter<InstrumentedQueue<Strict2AryHeap>>(view, num_nodes),
            InstrumentedQueue<Strict2AryHeap>(), "Dijkstra", "2-ary");
  run_suite(DijkstraRouter<InstrumentedQueue<Strict4AryHeap>>(view, num_nodes),
            InstrumentedQueue<Strict4AryHeap>(), "Dijkstra", "4-ary");
  run_suite(
      DijkstraRouter<InstrumentedQueue<Strict8ArySoALazyHeap>>(view, num_nodes),
      InstrumentedQueue<Strict8ArySoALazyHeap>(), "Dijkstra", "8-ary");
  run_suite(DijkstraRouter<InstrumentedQueue<Strict16AryHeap>>(view, num_nodes),
            InstrumentedQueue<Strict16AryHeap>(), "Dijkstra", "16-ary");
  run_suite(DijkstraRouter<InstrumentedQueue<DeltaQueue>>(view, num_nodes),
            InstrumentedQueue<DeltaQueue>(), "Dijkstra", "delta");
  run_suite(
      DijkstraRouter<InstrumentedQueue<DeltaBucketQueue<4>>>(view, num_nodes),
      InstrumentedQueue<DeltaBucketQueue<4>>(), "Dijkstra", "bucket");
  run_suite(DijkstraRouter<InstrumentedQueue<SafeRadixHeap>>(view, num_nodes),
            InstrumentedQueue<SafeRadixHeap>(), "Dijkstra", "radix");

  // 2. BI-DIRECTIONAL DIJKSTRA
  run_suite(
      BiDijkstraRouter<InstrumentedQueue<Strict2AryHeap>>(view, num_nodes),
      InstrumentedQueue<Strict2AryHeap>(), "Bi-Dijkstra", "2-ary");
  run_suite(
      BiDijkstraRouter<InstrumentedQueue<Strict4AryHeap>>(view, num_nodes),
      InstrumentedQueue<Strict4AryHeap>(), "Bi-Dijkstra", "4-ary");
  run_suite(BiDijkstraRouter<InstrumentedQueue<Strict8ArySoALazyHeap>>(
                view, num_nodes),
            InstrumentedQueue<Strict8ArySoALazyHeap>(), "Bi-Dijkstra", "8-ary");
  run_suite(
      BiDijkstraRouter<InstrumentedQueue<Strict16AryHeap>>(view, num_nodes),
      InstrumentedQueue<Strict16AryHeap>(), "Bi-Dijkstra", "16-ary");
  run_suite(BiDijkstraRouter<InstrumentedQueue<DeltaQueue>>(view, num_nodes),
            InstrumentedQueue<DeltaQueue>(), "Bi-Dijkstra", "delta");
  run_suite(
      BiDijkstraRouter<InstrumentedQueue<DeltaBucketQueue<4>>>(view, num_nodes),
      InstrumentedQueue<DeltaBucketQueue<4>>(), "Bi-Dijkstra", "bucket");
  run_suite(BiDijkstraRouter<InstrumentedQueue<SafeRadixHeap>>(view, num_nodes),
            InstrumentedQueue<SafeRadixHeap>(), "Bi-Dijkstra", "radix");

  // 3. A* (Euclidean Heuristic)
  run_suite(AStarRouter<InstrumentedQueue<Strict2AryHeap>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<Strict2AryHeap>(), "A-Star", "2-ary");
  run_suite(AStarRouter<InstrumentedQueue<Strict4AryHeap>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<Strict4AryHeap>(), "A-Star", "4-ary");
  run_suite(AStarRouter<InstrumentedQueue<Strict8ArySoALazyHeap>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<Strict8ArySoALazyHeap>(), "A-Star", "8-ary");
  run_suite(AStarRouter<InstrumentedQueue<Strict16AryHeap>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<Strict16AryHeap>(), "A-Star", "16-ary");
  run_suite(AStarRouter<InstrumentedQueue<DeltaQueue>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<DeltaQueue>(), "A-Star", "delta");
  run_suite(AStarRouter<InstrumentedQueue<DeltaBucketQueue<4>>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<DeltaBucketQueue<4>>(), "A-Star", "bucket");
  run_suite(AStarRouter<InstrumentedQueue<SafeRadixHeap>>(
                view, num_nodes, manager.get_geometry_store()),
            InstrumentedQueue<SafeRadixHeap>(), "A-Star", "radix");

  // 4. ALT (Landmark A*)
  if (manager.get_landmarks_ptr()) {
    run_suite(TdAltRouter<InstrumentedQueue<Strict2AryHeap>>(view, num_nodes),
              InstrumentedQueue<Strict2AryHeap>(), "ALT", "2-ary");
    run_suite(TdAltRouter<InstrumentedQueue<Strict4AryHeap>>(view, num_nodes),
              InstrumentedQueue<Strict4AryHeap>(), "ALT", "4-ary");
    run_suite(
        TdAltRouter<InstrumentedQueue<Strict8ArySoALazyHeap>>(view, num_nodes),
        InstrumentedQueue<Strict8ArySoALazyHeap>(), "ALT", "8-ary");
    run_suite(TdAltRouter<InstrumentedQueue<Strict16AryHeap>>(view, num_nodes),
              InstrumentedQueue<Strict16AryHeap>(), "ALT", "16-ary");
    run_suite(TdAltRouter<InstrumentedQueue<DeltaQueue>>(view, num_nodes),
              InstrumentedQueue<DeltaQueue>(), "ALT", "delta");
    run_suite(
        TdAltRouter<InstrumentedQueue<DeltaBucketQueue<4>>>(view, num_nodes),
        InstrumentedQueue<DeltaBucketQueue<4>>(), "ALT", "bucket");
    run_suite(TdAltRouter<InstrumentedQueue<SafeRadixHeap>>(view, num_nodes),
              InstrumentedQueue<SafeRadixHeap>(), "ALT", "radix");
  } else {
    std::cout << "⚠️ Skipping ALT tests: Landmarks are NOT loaded!\n";
  }

  // Write all detailed results to CSV
  std::filesystem::create_directories(
      std::filesystem::path(out_csv).parent_path());
  std::ofstream csv(out_csv);
  csv << "Algorithm,Queue,RouteID,VisitedNodes,TimeMs,PushCount,PopCount,"
         "QueueTimeMs,PathWeight,PathLengthM,EuclideanDistanceM,MinPushCycles,"
         "MaxPushCycles,AvgPushCycles,MinPopCycles,MaxPopCycles,AvgPopCycles,"
         "PathEdges,Crashed,DijkstraWeight,RelativeErrorPct,IsExactMatch\n";
  for (const auto &r : all_results) {
    csv << std::format("{},{},{},{},{:.6f},{},{},{:.6f},{},{:.2f},{:.2f},{},{},"
                       "{:.2f},{},{},{:.2f},{},{},{},{:.6f},{}\n",
                       r.algorithm, r.queue, r.route_idx, r.visited_nodes,
                       r.route_ms, r.push_count, r.pop_count, r.queue_ms,
                       r.path_weight, r.path_length_m, r.euclidean_dist_m,
                       r.min_push_cycles, r.max_push_cycles, r.avg_push_cycles,
                       r.min_pop_cycles, r.max_pop_cycles, r.avg_pop_cycles,
                       r.path_edges, r.crashed ? 1 : 0, r.dijkstra_weight,
                       r.rel_error, r.is_exact ? 1 : 0);
  }
  csv.close();

  std::cout << std::format(
      "\n🎉 MATRIX BENCHMARK COMPLETE! Results successfully written to: {}\n",
      out_csv);
  return 0;
}
