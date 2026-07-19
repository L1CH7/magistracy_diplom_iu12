#pragma once

#include <cmath>
#include <cstdint>
#include <fstream>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "common/geometry_store.hpp"
#include "common/net/messages.hpp"
#include "data_provider/agent_pool.hpp"

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

class HubScenarioManager {
public:
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
    float center_lat = 55.7879f, center_lon = 49.1221f, center_r = 2.5f;

    while (std::getline(file, line)) {
      if (line.find("hubs_ratio:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &hubs_ratio_);
      } else if (line.find("smoothness:") != std::string::npos) {
        sscanf(line.c_str(), "%*[^:]: %f", &smoothness_);
      } else if (line.find("hour:") != std::string::npos &&
                 line.find("ratio:") != std::string::npos) {
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
          else if (line.find("residential:") != std::string::npos)
            break;
        }
        center_ = {"Center", center_lat, center_lon, center_r, 1.0f, {}};
      }

      auto name_pos = line.find("name:");
      if (name_pos != std::string::npos &&
          line.find("kazan_hubs") == std::string::npos) {
        char name_buf[64] = {0};
        float lat = 0.0f, lon = 0.0f, r = 1.0f, w = 0.1f;
        if (sscanf(line.c_str() + name_pos,
                   "name: \"%63[^\"]\", lat: %f, lon: %f, radius_km: %f, "
                   "weight: %f",
                   name_buf, &lat, &lon, &r, &w) >= 3) {
          if (lat != 0.0f && lon != 0.0f) {
            spokes_.push_back({name_buf, lat, lon, r, w, {}});
          }
        }
      }
    }

    if (profile_points_.empty()) {
      profile_points_ = {{3.0f, 0.10f},
                         {8.0f, 1.00f},
                         {13.0f, 0.50f},
                         {18.0f, 0.90f},
                         {22.0f, 0.25f}};
    }

    std::sort(profile_points_.begin(), profile_points_.end(),
              [](const VolumePoint &a, const VolumePoint &b) {
                return a.hour < b.hour;
              });

    if (center_.lat == 0.0f) {
      center_ = {"Center", 55.7879f, 49.1221f, 2.5f, 1.0f, {}};
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
      for (auto &sp : spokes_) {
        if (is_in_circle(lat, lon, sp.lat, sp.lon, sp.radius_km)) {
          sp.edges.push_back(e);
        }
      }
    }

    initialized_ = !center_.edges.empty();
    return initialized_;
  }

  float GetTargetActiveRatio(uint32_t sim_time_sec) const {
    if (profile_points_.empty())
      return 1.0f;
    if (profile_points_.size() == 1)
      return profile_points_[0].ratio;

    float current_hour =
        std::fmod(static_cast<float>(sim_time_sec) / 3600.0f, 24.0f);
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

  std::pair<traffic::EdgeID, traffic::EdgeID>
  GeneratePair(uint32_t sim_time_sec, uint32_t max_edges, std::mt19937 &gen) {
    if (!initialized_ || center_.edges.empty()) {
      return random_pair(max_edges, gen);
    }

    std::uniform_real_distribution<float> prob(0.0f, 1.0f);
    if (prob(gen) >= hubs_ratio_) {
      return random_pair(max_edges, gen);
    }

    uint32_t hour = (sim_time_sec / 3600) % 24;
    bool is_morning = (hour >= 7 && hour <= 9);
    bool is_evening = (hour >= 17 && hour <= 19);

    if (is_morning) {
      traffic::EdgeID src = pick_spoke_edge(gen, max_edges);
      traffic::EdgeID dst = pick_edge_from_list(center_.edges, gen, max_edges);
      return {src, dst};
    } else if (is_evening) {
      traffic::EdgeID src = pick_edge_from_list(center_.edges, gen, max_edges);
      traffic::EdgeID dst = pick_spoke_edge(gen, max_edges);
      return {src, dst};
    }

    return random_pair(max_edges, gen);
  }

private:
  HubDef center_;
  std::vector<HubDef> spokes_;
  std::vector<VolumePoint> profile_points_;
  float hubs_ratio_ = 0.70f;
  float smoothness_ = 1.0f;
  bool initialized_ = false;

  static bool is_in_circle(float lat, float lon, float clat, float clon,
                           float r_km) {
    float dlat = (lat - clat) * 111.1f;
    float dlon = (lon - clon) * 62.5f;
    return (dlat * dlat + dlon * dlon) <= (r_km * r_km);
  }

  traffic::EdgeID pick_edge_from_list(const std::vector<traffic::EdgeID> &list,
                                      std::mt19937 &gen, uint32_t max_edges) {
    if (list.empty()) {
      std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
      return dist(gen);
    }
    std::uniform_int_distribution<size_t> dist(0, list.size() - 1);
    return list[dist(gen)];
  }

  traffic::EdgeID pick_spoke_edge(std::mt19937 &gen, uint32_t max_edges) {
    std::uniform_real_distribution<float> roll(0.0f, 1.0f);
    float r = roll(gen);
    float accum = 0.0f;
    for (const auto &sp : spokes_) {
      accum += sp.weight;
      if (r <= accum && !sp.edges.empty()) {
        return pick_edge_from_list(sp.edges, gen, max_edges);
      }
    }
    std::uniform_int_distribution<size_t> idx_dist(0, spokes_.size() - 1);
    return pick_edge_from_list(spokes_[idx_dist(gen)].edges, gen, max_edges);
  }

  std::pair<traffic::EdgeID, traffic::EdgeID> random_pair(uint32_t max_edges,
                                                          std::mt19937 &gen) {
    std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
    traffic::EdgeID s = dist(gen);
    traffic::EdgeID t = dist(gen);
    while (t == s)
      t = dist(gen);
    return {s, t};
  }
};

/**
 * @brief Utility for populating the simulation with agents and initial route
 * requests. Designed for hardware-aligned benchmarks and scenario setup.
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
    std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
    std::discrete_distribution<int> wp_dist(wp_probs.begin(), wp_probs.end());

    uint32_t active_count = count;
    if (hub_mgr) {
      active_count = static_cast<uint32_t>(
          std::round(count * hub_mgr->GetTargetActiveRatio(sim_time_sec)));
      if (active_count == 0 && count > 0)
        active_count = 1;
    }

    for (uint32_t i = 0; i < count; ++i) {
      uint8_t num_wp = static_cast<uint8_t>(wp_dist(gen)) + 2;
      pool.total_waypoints[i] = num_wp;
      pool.next_waypoint_idx[i] = 1;

      std::vector<traffic::EdgeID> req_wps;
      req_wps.reserve(num_wp);

      if (hub_mgr) {
        auto [src, dst] = hub_mgr->GeneratePair(sim_time_sec, max_edges, gen);
        req_wps.push_back(src);
        req_wps.push_back(dst);
        for (int w = 2; w < num_wp; ++w) {
          traffic::EdgeID wp = dist(gen);
          while (wp == req_wps.back())
            wp = dist(gen);
          req_wps.push_back(wp);
        }
      } else {
        for (int w = 0; w < num_wp; ++w) {
          traffic::EdgeID wp = dist(gen);
          if (w > 0) {
            while (wp == req_wps.back())
              wp = dist(gen);
          }
          req_wps.push_back(wp);
        }
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
