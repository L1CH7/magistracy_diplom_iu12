#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

#include "agent_pool.hpp"
#include "common/graph_types.hpp"
#include "physics_context.hpp"
#include "route_arena.hpp"

namespace traffic::data_provider
{

/**
 * @brief Подсистема противодействия заторам и дедлокам (Deadlock & Queue Mitigation System).
 * Инкапсулирует обработку виртуального буфера SUMO и игрового деспавна Cities Skylines.
 */
class DeadlockMitigationSystem
{
public:
    DeadlockMitigationSystem( AgentPool & pool, RouteArena & arena )
    :   pool_( pool ),
        arena_( arena )
    {}

    /**
     * @brief Обработка агентов в виртуальном буфере SUMO и очереди ожидания заторов.
     * @param dt Шаг времени физики [сек].
     * @param ctx Контекст физических вычислений.
     */
    void Process( float dt, const PhysicsContext & ctx ) noexcept
    {
        if( !ctx.deadlock_mitigation_enabled )
        {
            return;
        }

        // 1. Процессинг агентов в виртуальном буфере SUMO
        size_t vb_idx = 0;
        while( vb_idx < pool_.virtual_buffer_queue.size() )
        {
            uint32_t agent_idx = pool_.virtual_buffer_queue[vb_idx];

            if( pool_.status[agent_idx] != AgentStatus::VIRTUAL_BUFFER )
            {
                pool_.virtual_buffer_queue[vb_idx] = pool_.virtual_buffer_queue.back();
                pool_.virtual_buffer_queue.pop_back();
                continue;
            }

            float v_virt = ctx.min_virtual_speed_mps;
            if( ctx.edge_attributes && ctx.live_volumes )
            {
                traffic::EdgeID curr_edge = pool_.current_edge[agent_idx];
                uint32_t vis_cap = ctx.edge_attributes[curr_edge].visual_capacity;
                uint32_t live_vol = ctx.live_volumes[curr_edge];
                float w = ctx.edge_attributes[curr_edge].t_free_base;
                float len = ( ctx.edge_lengths_m ) ? ctx.edge_lengths_m[curr_edge] : ( 1.0f / pool_.inv_edge_length_m[agent_idx] );
                if( w < 0.001f ) w = 0.001f;
                float v_free = len / w;
                float C_vis = std::max< float >( 1.0f, static_cast< float >( vis_cap ) );
                float v_bpr = ( live_vol > vis_cap ) ? v_free * ( C_vis / static_cast< float >( live_vol ) ) : v_free;
                v_virt = std::max< float >( 1.3f, v_bpr );
            }
            pool_.pos_meters[agent_idx] += v_virt * dt;

            float edge_len = 1.0f / pool_.inv_edge_length_m[agent_idx];
            if( pool_.pos_meters[agent_idx] >= edge_len )
            {
                auto route = arena_.GetRoute( agent_idx );
                uint16_t next_idx = pool_.route_progress_idx[agent_idx] + 1;

                if( route.empty() )
                {
                    pool_.pos_meters[agent_idx] = edge_len;
                    vb_idx++;
                    continue;
                }

                if( next_idx < route.size() )
                {
                    traffic::EdgeID next_edge = route[next_idx];
                    uint32_t jam_cap_next = 1;
                    if( ctx.edge_attributes )
                    {
                        jam_cap_next = std::max< uint32_t >( 1, ctx.edge_attributes[next_edge].jam_capacity );
                    }
                    uint32_t load_next = ctx.live_volumes ? ctx.live_volumes[next_edge] : 0;

                    // Проверяем: есть ли свободное место на физической дороге?
                    if( load_next + 1 <= jam_cap_next )
                    {
                        // Место появилось! Агент возвращается из виртуального буфера на физическое ребро
                        traffic::EdgeID old_edge = pool_.current_edge[agent_idx];
                        if( ctx.live_volumes && ctx.live_volumes[old_edge] > 0 )
                        {
                            ctx.live_volumes[old_edge]--;
                        }

                        pool_.status[agent_idx] = AgentStatus::ACTIVE_FREE_FLOW;
                        pool_.route_progress_idx[agent_idx] = next_idx;
                        pool_.current_edge[agent_idx] = next_edge;
                        pool_.pos_meters[agent_idx] = 0.0f;
                        pool_.edge_enter_time_sec[agent_idx] = ctx.current_time_sec;

                        if( ctx.live_volumes )
                        {
                            ctx.live_volumes[next_edge]++;
                        }

                        pool_.virtual_buffer_queue[vb_idx] = pool_.virtual_buffer_queue.back();
                        pool_.virtual_buffer_queue.pop_back();
                        continue;
                    }
                    else
                    {
                        // Ребро забито — ждём на конце текущего ребра до следующего такта.
                        // Не прыгаем вперёд: один такт = максимум одно ребро.
                        pool_.pos_meters[agent_idx] = edge_len - 0.01f;
                    }
                }
                else
                {
                    // Финиш маршрута в виртуальном буфере
                    pool_.status[agent_idx] = AgentStatus::INACTIVE;
                    pool_.pos_meters[agent_idx] = 0.0f;
                    if( ctx.completed_agents_out )
                    {
                        ctx.completed_agents_out->push_back( agent_idx );
                    }
                    pool_.virtual_buffer_queue[vb_idx] = pool_.virtual_buffer_queue.back();
                    pool_.virtual_buffer_queue.pop_back();
                    continue;
                }
            }
            vb_idx++;
        }

        // 2. Процессинг застрявших агентов в очереди spillback_wait_queue
        size_t sb_idx = 0;
        while( sb_idx < pool_.spillback_wait_queue.size() )
        {
            uint32_t agent_idx = pool_.spillback_wait_queue[sb_idx];

            if( pool_.status[agent_idx] != AgentStatus::ACTIVE_QUEUE )
            {
                pool_.spillback_wait_queue[sb_idx] = pool_.spillback_wait_queue.back();
                pool_.spillback_wait_queue.pop_back();
                continue;
            }

            uint32_t wait_time = ctx.current_time_sec - pool_.spillback_start_time_sec[agent_idx];
            if( static_cast< float >( wait_time ) >= ctx.time_to_teleport_sec )
            {
                // Порог простоя превышен! Снимаем машину с застрявшего ребра
                traffic::EdgeID curr_edge = pool_.current_edge[agent_idx];

                // Освобождаем счётчик физической очереди — агент уходит с ребра.
                if( pool_.in_queue[agent_idx] )
                {
                    pool_.in_queue[agent_idx] = 0;
                    if( ctx.queue_volumes )
                    {
                        uint32_t q = ctx.queue_volumes[curr_edge].load( std::memory_order_relaxed );
                        if( q > 0 ) ctx.queue_volumes[curr_edge].fetch_sub( 1, std::memory_order_relaxed );
                    }
                }

                if( ctx.live_volumes && ctx.live_volumes[curr_edge] > 0 )
                {
                    ctx.live_volumes[curr_edge]--; // Освобождаем место, разрывая замкнутое кольцо
                }
                if( ctx.teleported_jam_count_out )
                {
                    ( *ctx.teleported_jam_count_out )++;
                }

                if( ctx.deadlock_mitigation_mode == 0 ) // SUMO Virtual Buffer
                {
                    pool_.status[agent_idx] = AgentStatus::VIRTUAL_BUFFER;
                    pool_.virtual_buffer_queue.push_back( agent_idx );
                }
                else // Cities Skylines Despawn
                {
                    pool_.status[agent_idx] = AgentStatus::INACTIVE;
                    pool_.pos_meters[agent_idx] = 0.0f;
                    pool_.is_waiting_route[agent_idx] = 0;
                    if( ctx.completed_agents_out )
                    {
                        ctx.completed_agents_out->push_back( agent_idx );
                    }
                }

                pool_.spillback_wait_queue[sb_idx] = pool_.spillback_wait_queue.back();
                pool_.spillback_wait_queue.pop_back();
                continue;
            }
            sb_idx++;
        }
    }

private:
    AgentPool & pool_;
    RouteArena & arena_;
};

} // namespace traffic::data_provider
