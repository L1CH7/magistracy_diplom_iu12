#pragma once

#include <cmath>
#include <cstdint>
#include <fstream>
#include <memory>
#include <random>
#include <string>
#include <vector>
#include <algorithm>

#include "common/geometry_store.hpp"
#include "common/net/messages.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/population_manager.hpp"

namespace traffic::data_provider {

struct HubDef {
  std::string name;
  float lat;
  float lon;
  float radius_km;
  float weight;
  std::vector<traffic::EdgeID> edges;
};

struct VolumePoint {
  float hour;
  float ratio;
};

/**
 * @brief Полностью абстрактный менеджер сценария транспортных хабов и населения.
 * Загружает конфигурацию из YAML без каких-либо захардкоженных имен городов или координат.
 */
class HubScenarioManager {
public:
  HubScenarioManager() {
    pop_mgr_ = std::make_unique<ConfigurablePopulationManager>();
  }

  bool LoadConfig(const std::string &config_path,
                  const common::GeometryStore *geom_store, uint32_t num_edges) {
    if (!geom_store || num_edges == 0)
      return false;

    std::ifstream file(config_path);
    if (!file.is_open()) {
      file.open("configs/simulation/scenario.yaml");
      if (!file.is_open()) {
        file.open("../configs/simulation/scenario.yaml");
      }
    }

    if (!file.is_open())
      return false;

    spokes_.clear();
    profile_points_.clear();
    std::string line;
    float center_lat = 0.0f, center_lon = 0.0f, center_r = 2.5f;
    PopulationConfig pop_cfg;

    while (std::getline(file, line)) {
      if (line.find("hubs_ratio:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &hubs_ratio_);
      } else if (line.find("smoothness:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &smoothness_);
      } else if (line.find("dt_sec:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.dt_sec);
      } else if (line.find("commuters:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.commuters_pct);
      } else if (line.find("commercial:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.commercial_pct);
      } else if (line.find("public_transport:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.public_transport_pct);
      } else if (line.find("random:") != std::string::npos && line.find("random_pair") == std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.random_pct);
      } else if (line.find("morning_peak_hour:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.morning_peak_hour);
      } else if (line.find("evening_peak_hour:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.evening_peak_hour);
      } else if (line.find("gaussian_sigma_hours:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &pop_cfg.gaussian_sigma_hours);
      } else if (line.find("hour:") != std::string::npos && line.find("ratio:") != std::string::npos) {
        float h = 0.0f, r = 1.0f;
        auto h_pos = line.find("hour:");
        auto r_pos = line.find("ratio:");
        if (h_pos != std::string::npos && r_pos != std::string::npos) {
          sscanf(line.c_str() + h_pos, "hour: %f", &h);
          sscanf(line.c_str() + r_pos, "ratio: %f", &r);
          profile_points_.push_back({h, r});
        }
      } else if (line.find("center:") != std::string::npos) {
        while (std::getline(file, line)) {
          if (line.find("lat:") != std::string::npos)
            sscanf(line.c_str(), "%*[^:]: %f", &center_lat);
          else if (line.find("lon:") != std::string::npos)
            sscanf(line.c_str(), "%*[^:]: %f", &center_lon);
          else if (line.find("radius_km:") != std::string::npos)
            sscanf(line.c_str(), "%*[^:]: %f", &center_r);
          else if (line.find("residential:") != std::string::npos || line.find("suburbs:") != std::string::npos)
            break;
        }
        center_ = {"Center", center_lat, center_lon, center_r, 1.0f, {}};
      } else if (line.find("lat:") != std::string::npos && line.find("lon:") != std::string::npos && line.find("radius_km:") != std::string::npos) {
        // Парсинг хабов из любого списка (residential, suburbs, industrial и т.д.)
        char name_buf[64] = {0};
        float lat = 0.0f, lon = 0.0f, r = 1.0f, w = 0.1f;
        auto name_pos = line.find("name:");
        if (name_pos != std::string::npos) {
          if (sscanf(line.c_str() + name_pos,
                     "name: \"%63[^\"]\", lat: %f, lon: %f, radius_km: %f, weight: %f",
                     name_buf, &lat, &lon, &r, &w) >= 3 ||
              sscanf(line.c_str() + name_pos,
                     "name: %63s, lat: %f, lon: %f, radius_km: %f, weight: %f",
                     name_buf, &lat, &lon, &r, &w) >= 3) {
            if (lat != 0.0f && lon != 0.0f) {
              spokes_.push_back({name_buf, lat, lon, r, w, {}});
            }
          }
        }
      }
    }

    if (profile_points_.empty()) {
      profile_points_ = {{3.0f, 0.10f}, {8.0f, 1.00f}, {13.0f, 0.50f}, {18.0f, 0.90f}, {22.0f, 0.25f}};
    }

    std::sort(profile_points_.begin(), profile_points_.end(),
              [](const VolumePoint &a, const VolumePoint &b) { return a.hour < b.hour; });

    // Динамический расчёт центроида графа, если центр не был явно задан в YAML
    if (center_.lat == 0.0f || center_.lon == 0.0f) {
      double sum_lat = 0.0, sum_lon = 0.0;
      uint64_t count_pts = 0;
      for (uint32_t e = 0; e < num_edges; ++e) {
        auto geom = geom_store->get_geometry(e);
        if (!geom.points.empty()) {
          sum_lon += geom.points[0].x;
          sum_lat += geom.points[0].y;
          count_pts++;
        }
      }
      if (count_pts > 0) {
        center_ = {"Center", static_cast<float>(sum_lat / count_pts), static_cast<float>(sum_lon / count_pts), 2.5f, 1.0f, {}};
      }
    }

    spoke_edges_.clear();
    spoke_weights_.clear();
    spoke_edges_.resize(spokes_.size());
    spoke_weights_.reserve(spokes_.size());

    for (const auto &sp : spokes_) {
      spoke_weights_.push_back(sp.weight);
    }

    for (uint32_t e = 0; e < num_edges; ++e) {
      auto geom = geom_store->get_geometry(e);
      if (geom.points.empty())
        continue;

      float lon = geom.points[0].x;
      float lat = geom.points[0].y;

      if (is_in_circle(lat, lon, center_.lat, center_.lon, center_.radius_km)) {
        center_.edges.push_back(e);
      }
      for (size_t i = 0; i < spokes_.size(); ++i) {
        if (is_in_circle(lat, lon, spokes_[i].lat, spokes_[i].lon, spokes_[i].radius_km)) {
          spokes_[i].edges.push_back(e);
          spoke_edges_[i].push_back(e);
        }
      }
    }

    if (auto *cfg_mgr = dynamic_cast<ConfigurablePopulationManager *>(pop_mgr_.get())) {
      cfg_mgr->SetConfig(pop_cfg);
    }

    initialized_ = !center_.edges.empty();
    return initialized_;
  }

  float GetTargetActiveRatio(uint32_t sim_time_sec) const {
    if (profile_points_.empty())
      return 1.0f;
    if (profile_points_.size() == 1)
      return profile_points_[0].ratio;

    float current_hour = std::fmod(static_cast<float>(sim_time_sec) / 3600.0f, 24.0f);
    size_t n = profile_points_.size();
    size_t idx1 = n - 1;
    size_t idx2 = 0;

    for (size_t i = 0; i < n; ++i) {
      if (profile_points_[i].hour > current_hour) {
        idx2 = i;
        idx1 = (i == 0) ? (n - 1) : (i - 1);
        break;
      }
    }

    float h1 = profile_points_[idx1].hour;
    float r1 = profile_points_[idx1].ratio;
    float h2 = profile_points_[idx2].hour;
    float r2 = profile_points_[idx2].ratio;

    float interval = h2 - h1;
    if (interval <= 0.0f)
      interval += 24.0f;

    float delta = current_hour - h1;
    if (delta < 0.0f)
      delta += 24.0f;

    float u = delta / interval;
    u = std::clamp(u, 0.0f, 1.0f);

    float s = u * u * (3.0f - 2.0f * u);
    float factor = (1.0f - smoothness_) * u + smoothness_ * s;

    return r1 + (r2 - r1) * factor;
  }

  IPopulationManager *GetPopulationManager() { return pop_mgr_.get(); }

  std::pair<traffic::EdgeID, traffic::EdgeID>
  GeneratePairForAgent(uint32_t agent_id, const AgentPool &pool, uint32_t sim_time_sec,
                       uint32_t max_edges, std::mt19937 &gen) {
    if (!initialized_ || center_.edges.empty() || !pop_mgr_) {
      return random_pair(max_edges, gen);
    }
    return pop_mgr_->GenerateTrip(agent_id, pool, sim_time_sec, max_edges, gen,
                                  center_.edges, spoke_edges_, spoke_weights_);
  }

  bool ShouldWakeupAgent(uint32_t agent_id, const AgentPool &pool, uint32_t sim_time_sec,
                         float target_ratio, std::mt19937 &gen) {
    if (!pop_mgr_)
      return true;
    return pop_mgr_->ShouldWakeupAgent(agent_id, pool, sim_time_sec, target_ratio, gen);
  }

  void AssignAgentProperties(uint32_t agent_id, AgentPool &pool, std::mt19937 &gen, uint32_t max_edges) {
    if (pop_mgr_) {
      pop_mgr_->AssignAgentProperties(agent_id, pool, gen, center_.edges, spoke_edges_, spoke_weights_, max_edges);
    }
  }

private:
  HubDef center_;
  std::vector<HubDef> spokes_;
  std::vector<std::vector<traffic::EdgeID>> spoke_edges_;
  std::vector<float> spoke_weights_;
  std::vector<VolumePoint> profile_points_;
  std::unique_ptr<IPopulationManager> pop_mgr_;
  float hubs_ratio_ = 0.70f;
  float smoothness_ = 1.0f;
  bool initialized_ = false;

  static bool is_in_circle(float lat, float lon, float clat, float clon, float r_km) {
    float dlat = (lat - clat) * 111.1f;
    float dlon = (lon - clon) * 62.5f;
    return (dlat * dlat + dlon * dlon) <= (r_km * r_km);
  }

  std::pair<traffic::EdgeID, traffic::EdgeID> random_pair(uint32_t max_edges, std::mt19937 &gen) {
    std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
    traffic::EdgeID s = dist(gen);
    traffic::EdgeID t = dist(gen);
    while (t == s)
      t = dist(gen);
    return {s, t};
  }
};

/**
 * @brief Утилита наполнения автопарка агентов без физической телепортации.
 */
class ScenarioGenerator {
public:
  static void SpawnRandomAgents(
      AgentPool &pool, uint32_t count, uint32_t max_edges, uint16_t default_asf,
      std::vector<traffic::common::net::RouteRequest> &initial_requests,
      HubScenarioManager *hub_mgr = nullptr, uint32_t sim_time_sec = 0,
      const std::vector<double> &wp_probs = {0.90, 0.05, 0.03, 0.02}) {
    pool.Allocate(count);
    initial_requests.reserve(count);

    static std::mt19937 gen{std::random_device{}()};
    std::discrete_distribution<int> wp_dist(wp_probs.begin(), wp_probs.end());

    uint32_t active_count = count;
    if (hub_mgr) {
      active_count = static_cast<uint32_t>(
          std::round(count * hub_mgr->GetTargetActiveRatio(sim_time_sec)));
      if (active_count == 0 && count > 0)
        active_count = 1;
    }

    for (uint32_t i = 0; i < count; ++i) {
      if (hub_mgr) {
        hub_mgr->AssignAgentProperties(i, pool, gen, max_edges);
      }

      uint8_t num_wp = static_cast<uint8_t>(wp_dist(gen)) + 2;
      pool.total_waypoints[i] = num_wp;
      pool.next_waypoint_idx[i] = 1;

      std::vector<traffic::EdgeID> req_wps;
      req_wps.reserve(num_wp);

      if (hub_mgr) {
        auto [src, dst] = hub_mgr->GeneratePairForAgent(i, pool, sim_time_sec, max_edges, gen);
        req_wps.push_back(src);
        req_wps.push_back(dst);
      } else {
        std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
        traffic::EdgeID src = dist(gen);
        traffic::EdgeID dst = dist(gen);
        while (dst == src) dst = dist(gen);
        req_wps.push_back(src);
        req_wps.push_back(dst);
      }

      for (size_t w = 0; w < req_wps.size(); ++w) {
        pool.waypoints[i][w] = req_wps[w];
      }

      pool.current_edge[i] = req_wps[0];
      pool.velocity_mps[i] = 0.0f;
      pool.pos_meters[i] = 0.0f;
      pool.edge_enter_time_sec[i] = 0;
      pool.route_progress_idx[i] = 0;
      pool.route_epoch[i] = 1;

      if (i < active_count) {
        pool.is_active[i] = 2;
        pool.is_waiting_route[i] = 1;

        traffic::common::net::RouteRequest req;
        req.agent_id = i;
        req.epoch = pool.route_epoch[i];
        req.num_waypoints = static_cast<uint8_t>(req_wps.size());
        for (uint8_t w = 0; w < req.num_waypoints; ++w) {
          req.waypoints[w] = req_wps[w];
        }
        req.asf = default_asf;
        req.current_time_sec = sim_time_sec;

        initial_requests.push_back(std::move(req));
      } else {
        pool.is_active[i] = 0;
        pool.is_waiting_route[i] = 0;
      }
    }
  }
};

} // namespace traffic::data_provider
