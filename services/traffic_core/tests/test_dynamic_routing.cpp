#include <iostream>
#include <vector>
#include <cassert>
#include "router/compute/td_alt_router.hpp"
#include "router/control/volume_manager.hpp"

using namespace traffic;

// Макрос для красивого вывода assert'ов
#define TEST_ASSERT(condition, message) \
    if (!(condition)) { \
        std::cerr << "❌ [FAIL] " << message << std::endl; \
        std::exit(1); \
    } else { \
        std::cout << "✅ [PASS] " << message << std::endl; \
    }

void RunBucketTests() {
    std::cout << "\n=== STARTING DYNAMIC ROUTING & BUCKET TESTS ===\n";

    // 1. Создаем фейковый граф (Линия: 0 -> 1 -> 2)
    // Узел 0: ребро в 1
    // Узел 1: ребро в 2
    // Узел 2: тупик
    EdgeID row_ptr[] = {0, 1, 2, 2};
    NodeID col_ind[] = {1, 2};
    EdgeWeight weights[] = {100, 100}; // T_free = 100 секунд на каждый участок
    
    GraphView view{row_ptr, col_ind, weights};
    uint32_t num_nodes = 3;

    // Массивы штрафов
    // K_magic = 100'000 (условная константа для заметного штрафа при объеме)
    int32_t k_magic[] = {0, 100000, 100000}; 
    EdgeWeight mpr_penalty[] = {0, 0, 0};

    // 2. Инициализируем Роутер и Менеджер
    router::TdAltRouter router(view, num_nodes);
    router::control::VolumeManager vol_manager(num_nodes);

    AbsoluteTime start_time = 0;

    // --- ТЕСТ 1: Свободный поток (Free Flow) ---
    auto res_free = router.Route<false, false>(0, 2, start_time, nullptr, nullptr, nullptr);
    TEST_ASSERT(res_free.total_weight == 200, "Free Flow (Traffic=false) should be exactly 200s");
    TEST_ASSERT(res_free.path.size() == 3, "Path should contain 3 nodes (0, 1, 2)");
    TEST_ASSERT(res_free.etas[0] == 0 && res_free.etas[1] == 100 && res_free.etas[2] == 200, "ETAs should be exactly 0, 100, 200");

    // --- ТЕСТ 2: Пустые корзинки с включенным трафиком ---
    auto res_empty_traffic = router.Route<true, false>(0, 2, start_time, vol_manager.data(), k_magic, mpr_penalty);
    TEST_ASSERT(res_empty_traffic.total_weight == 200, "Traffic=true with 0 cars should equal Free Flow (200s)");

    // --- ТЕСТ 3: Добавление трафика (Создаем затор на ребре 0->1) ---
    // Бронируем 50 машин на вход в узел 1 в нулевую секунду (0-300с)
    std::vector<NodeID> sim_path = {1};
    std::vector<AbsoluteTime> sim_etas = {50}; 
    for(int i=0; i<50; ++i) vol_manager.book_route(sim_path, sim_etas);

    auto res_congested = router.Route<true, false>(0, 2, start_time, vol_manager.data(), k_magic, mpr_penalty);
    TEST_ASSERT(res_congested.total_weight > 200, "Congested route should take longer than 200s");
    std::cout << "   -> Congested Weight: " << res_congested.total_weight << "s (Penalty: +" << (res_congested.total_weight - 200) << "s)\n";

    // --- ТЕСТ 4: Сдвиг времени (Очистка корзинок) ---
    // Сдвигаем глобальное время на 400 секунд вперед (следующая корзинка)
    vol_manager.advance_time(0, 400);
    
    // Пытаемся проехать в 400-ю секунду
    auto res_cleared = router.Route<true, false>(0, 2, 400, vol_manager.data(), k_magic, mpr_penalty);
    
    // Вес должен вернуться к базовому (но с учетом того, что старт в 400)
    // Вес маршрута хранится как g_score, он равен 200. ETA финиша будет 400 + 200 = 600.
    TEST_ASSERT(res_cleared.total_weight == 200, "After advance_time(), old buckets should be cleared. Weight = 200s");
    TEST_ASSERT(res_cleared.etas[2] == 600, "ETA at destination should be StartTime(400) + Weight(200) = 600s");

    std::cout << "=== ALL TESTS PASSED SUCCESSFULLY ===\n\n";
}

int main() {
    RunBucketTests();
    return 0;
}
