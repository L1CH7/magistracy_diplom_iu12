#pragma once

#include <cmath>
#include <cstdint>
#include <fstream>
#include <memory>
#include <random>
#include <string>
#include <vector>
#include <algorithm>

#include "data_provider/agent_pool.hpp"

namespace traffic::data_provider {

/**
 * @brief Перечисление типов населения транспортной модели.
 */
enum class PopulationType : uint8_t {
  Commuter = 0,         ///< Маятниковая миграция (Дом <-> Работа)
  Commercial = 1,       ///< Коммерческий трафик / Грузовые / Такси
  PublicTransport = 2,  ///< Общественный транспорт (Маршрутные кольца)
  RandomBackground = 3  ///< Случайный фоновый трафик
};

/**
 * @brief Структура конфигурации распределения населения.
 */
struct PopulationConfig {
  float commuters_pct = 0.65f;
  float commercial_pct = 0.20f;
  float public_transport_pct = 0.05f;
  float random_pct = 0.10f;

  float morning_peak_hour = 8.0f;
  float evening_peak_hour = 18.0f;
  float gaussian_sigma_hours = 1.0f;
  float dt_sec = 0.1f;
};

/**
 * @brief Абстрактный интерфейс менеджера населения (IPopulationManager).
 */
class IPopulationManager {
public:
  virtual ~IPopulationManager() = default;

  /**
   * @brief Инициализирует свойства агента (Дом, Работа, Смещение расписания) при первом спавне.
   */
  virtual void AssignAgentProperties(uint32_t agent_id, AgentPool &pool,
                                     std::mt19937 &gen,
                                     const std::vector<traffic::EdgeID> &center_edges,
                                     const std::vector<std::vector<traffic::EdgeID>> &spoke_edges,
                                     const std::vector<float> &spoke_weights,
                                     uint32_t max_edges) = 0;

  /**
   * @brief Генерирует следующую поездку агента (Start -> Target) без физической телепортации.
   */
  virtual std::pair<traffic::EdgeID, traffic::EdgeID>
  GenerateTrip(uint32_t agent_id, const AgentPool &pool, uint32_t sim_time_sec,
               uint32_t max_edges, std::mt19937 &gen,
               const std::vector<traffic::EdgeID> &center_edges,
               const std::vector<std::vector<traffic::EdgeID>> &spoke_edges,
               const std::vector<float> &spoke_weights) = 0;

  /**
   * @brief Проверяет стохастическое условие пробуждения агента (Hazard Rate / Gaussian Process).
   */
  virtual bool ShouldWakeupAgent(uint32_t agent_id, const AgentPool &pool,
                                 uint32_t sim_time_sec, float target_ratio,
                                 std::mt19937 &gen) = 0;
};

/**
 * @brief Конфигурируемая реализация IPopulationManager.
 * Читает проценты распределения из YAML. Если процент типа == 0, его вычисления полностью пропускаются.
 */
class ConfigurablePopulationManager : public IPopulationManager {
public:
  explicit ConfigurablePopulationManager(PopulationConfig cfg = {})
      : cfg_(cfg) {}

  void SetConfig(const PopulationConfig &cfg) { cfg_ = cfg; }
  const PopulationConfig &GetConfig() const { return cfg_; }

  void AssignAgentProperties(uint32_t agent_id, AgentPool &pool,
                             std::mt19937 &gen,
                             const std::vector<traffic::EdgeID> &center_edges,
                             const std::vector<std::vector<traffic::EdgeID>> &spoke_edges,
                             const std::vector<float> &spoke_weights,
                             uint32_t max_edges) override {
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    float roll = dist(gen);

    float c_cum = cfg_.commuters_pct;
    float m_cum = c_cum + cfg_.commercial_pct;
    float p_cum = m_cum + cfg_.public_transport_pct;

    PopulationType ptype = PopulationType::RandomBackground;
    if (roll < c_cum && cfg_.commuters_pct > 0.0f) {
      ptype = PopulationType::Commuter;
    } else if (roll < m_cum && cfg_.commercial_pct > 0.0f) {
      ptype = PopulationType::Commercial;
    } else if (roll < p_cum && cfg_.public_transport_pct > 0.0f) {
      ptype = PopulationType::PublicTransport;
    }

    pool.population_type[agent_id] = static_cast<uint8_t>(ptype);

    // Гауссово смещение индивидуального времени выезда (-1.5h .. +1.5h)
    std::normal_distribution<float> jitter_dist(0.0f, cfg_.gaussian_sigma_hours * 3600.0f);
    pool.schedule_offset_sec[agent_id] = jitter_dist(gen);

    // Выбор Home & Work ребер
    traffic::EdgeID home = pick_spoke_edge(spoke_edges, spoke_weights, gen, max_edges);
    traffic::EdgeID work = pick_edge_from_list(center_edges, gen, max_edges);

    pool.home_edge[agent_id] = home;
    pool.work_edge[agent_id] = work;
  }

  std::pair<traffic::EdgeID, traffic::EdgeID>
  GenerateTrip(uint32_t agent_id, const AgentPool &pool, uint32_t sim_time_sec,
               uint32_t max_edges, std::mt19937 &gen,
               const std::vector<traffic::EdgeID> &center_edges,
               const std::vector<std::vector<traffic::EdgeID>> &spoke_edges,
               const std::vector<float> &spoke_weights) override {
    PopulationType ptype = static_cast<PopulationType>(pool.population_type[agent_id]);
    traffic::EdgeID start_edge = pool.current_edge[agent_id];

    if (ptype == PopulationType::Commuter) {
      // Zero-teleportation: выезд происхоид с текущей припаркованной позиции
      if (start_edge == 0) {
        start_edge = pool.home_edge[agent_id];
      }

      uint32_t hour = (sim_time_sec / 3600) % 24;
      bool is_evening = (hour >= static_cast<uint32_t>(cfg_.evening_peak_hour - 1.0f) &&
                         hour <= static_cast<uint32_t>(cfg_.evening_peak_hour + 2.0f));

      traffic::EdgeID target_edge = is_evening ? pool.home_edge[agent_id] : pool.work_edge[agent_id];
      if (target_edge == start_edge) {
        target_edge = (start_edge == pool.home_edge[agent_id]) ? pool.work_edge[agent_id] : pool.home_edge[agent_id];
      }
      return {start_edge, target_edge};
    }

    if (ptype == PopulationType::Commercial) {
      // Коммерческий/такси трафик: выезд с текущей точки в случайный новый хаб
      traffic::EdgeID target_edge = pick_spoke_edge(spoke_edges, spoke_weights, gen, max_edges);
      while (target_edge == start_edge) {
        target_edge = pick_edge_from_list(center_edges, gen, max_edges);
      }
      return {start_edge, target_edge};
    }

    // Случайный фоновый трафик
    std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
    traffic::EdgeID target_edge = dist(gen);
    while (target_edge == start_edge) {
      target_edge = dist(gen);
    }
    return {start_edge, target_edge};
  }

  bool ShouldWakeupAgent(uint32_t agent_id, const AgentPool &pool,
                         uint32_t sim_time_sec, float target_ratio,
                         std::mt19937 &gen) override {
    PopulationType ptype = static_cast<PopulationType>(pool.population_type[agent_id]);
    float current_hour = std::fmod(static_cast<float>(sim_time_sec) / 3600.0f, 24.0f);

    if (ptype == PopulationType::Commuter) {
      // Пробуждаем по Гауссову распределению вокруг пиков с учетом выровненной нормы
      float sched_time = current_hour * 3600.0f + pool.schedule_offset_sec[agent_id];
      float sched_hour = std::fmod(sched_time / 3600.0f + 24.0f, 24.0f);

      bool near_morning = std::abs(sched_hour - cfg_.morning_peak_hour) <= (cfg_.gaussian_sigma_hours * 2.0f);
      bool near_evening = std::abs(sched_hour - cfg_.evening_peak_hour) <= (cfg_.gaussian_sigma_hours * 2.0f);

      if (near_morning || near_evening) {
        std::uniform_real_distribution<float> roll(0.0f, 1.0f);
        return roll(gen) <= (target_ratio * 1.5f);
      }
    }

    // Для остальных типов вероятность выезда напрямую зависит от текущей дневной кривой
    std::uniform_real_distribution<float> roll(0.0f, 1.0f);
    return roll(gen) <= target_ratio;
  }

private:
  PopulationConfig cfg_;

  static traffic::EdgeID pick_edge_from_list(const std::vector<traffic::EdgeID> &list,
                                             std::mt19937 &gen, uint32_t max_edges) {
    if (list.empty()) {
      std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
      return dist(gen);
    }
    std::uniform_int_distribution<size_t> dist(0, list.size() - 1);
    return list[dist(gen)];
  }

  static traffic::EdgeID pick_spoke_edge(const std::vector<std::vector<traffic::EdgeID>> &spoke_edges,
                                        const std::vector<float> &spoke_weights,
                                        std::mt19937 &gen, uint32_t max_edges) {
    if (spoke_edges.empty()) {
      std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
      return dist(gen);
    }

    std::uniform_real_distribution<float> roll(0.0f, 1.0f);
    float r = roll(gen);
    float accum = 0.0f;

    for (size_t i = 0; i < spoke_edges.size(); ++i) {
      accum += (i < spoke_weights.size()) ? spoke_weights[i] : (1.0f / spoke_edges.size());
      if (r <= accum && !spoke_edges[i].empty()) {
        return pick_edge_from_list(spoke_edges[i], gen, max_edges);
      }
    }

    std::uniform_int_distribution<size_t> idx_dist(0, spoke_edges.size() - 1);
    return pick_edge_from_list(spoke_edges[idx_dist(gen)], gen, max_edges);
  }
};

} // namespace traffic::data_provider
