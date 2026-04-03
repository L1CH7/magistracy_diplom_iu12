#pragma once

#include "concurrentqueue/concurrentqueue.h"
#include <thread>
#include <vector>
#include <functional>
#include <atomic>
#include <print>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace traffic::core
{
inline thread_local int g_worker_id = -1;

class ThreadPool
{
public:
    // avoid_os_cores - если true, потоки не будут привязываться к 0-му и 1-му ядру
    explicit ThreadPool( unsigned num_threads = 0, bool use_affinity = false, bool avoid_os_cores = true )
    :   stop_( false ),
        active_tasks_( 0 )
    {
        if( num_threads == 0 )
        {
            num_threads = std::thread::hardware_concurrency();
            if( avoid_os_cores && num_threads > 2 )
            {
                num_threads -= 2;
            }
        }

        for( unsigned i = 0; i < num_threads; ++i )
        {
            workers_.emplace_back( [this, i, use_affinity, avoid_os_cores, num_threads]() {
                g_worker_id = static_cast<int>(i);
#ifdef __linux__
                if( use_affinity )
                {
                    unsigned hw_threads = std::thread::hardware_concurrency();
                    unsigned phys_cores = hw_threads > 1 ? hw_threads / 2 : 1; 
                    unsigned core_id = 0;

                    if (avoid_os_cores && phys_cores > 2 && num_threads <= phys_cores - 1) {
                        core_id = (i % (phys_cores - 1)) + 1;
                    } 
                    else if (num_threads <= phys_cores) {
                        core_id = i % phys_cores;
                    } 
                    else {
                        core_id = i % hw_threads;
                    }
                    
                    SetAffinity( core_id );
                }
#endif
                WorkerLoop();
            } );
        }
    }

    /**
     * @brief Constructor for explicit CPU core mapping.
     * @param core_ids List of CPU core IDs to bind threads to.
     */
    explicit ThreadPool( const std::vector< int > & core_ids )
    :   stop_( false ),
        active_tasks_( 0 )
    {
        for( size_t i = 0; i < core_ids.size(); ++i )
        {
            int target_core = core_ids[ i ];
            workers_.emplace_back( [this, i, target_core]() {
                g_worker_id = static_cast< int >( i );
#ifdef __linux__
                SetAffinity( target_core );
#endif
                WorkerLoop();
            } );
        }
    }

    ~ThreadPool()
    {
        stop_.store( true, std::memory_order_release );
        for( auto & worker : workers_ )
        {
            if( worker.joinable() )
            {
                worker.join();
            }
        }
    }

    template< class F >
    void Enqueue( F && f )
    {
        active_tasks_.fetch_add( 1, std::memory_order_relaxed );
        tasks_.enqueue( [this, task = std::forward< F >( f )]() {
            task();
            active_tasks_.fetch_sub( 1, std::memory_order_release );
        } );
    }

    void WaitForAll()
    {
        while( active_tasks_.load( std::memory_order_acquire ) > 0 )
        {
            std::this_thread::yield();
        }
    }

    static int GetWorkerId() { return g_worker_id; }

private:
    void SetAffinity( int core_id )
    {
#ifdef __linux__
        cpu_set_t cpuset;
        CPU_ZERO( &cpuset );
        CPU_SET( core_id, &cpuset );
        pthread_setaffinity_np( pthread_self(), sizeof( cpu_set_t ), &cpuset );
#else
        (void)core_id;
#endif
    }

    void WorkerLoop()
    {
        while( true )
        {
            std::function< void() > task;
            if( tasks_.try_dequeue( task ) )
            {
                task();
            }
            else if( stop_.load( std::memory_order_acquire ) )
            {
                break;
            }
            else
            {
                std::this_thread::yield();
            }
        }
    }

private:
    std::vector< std::thread > workers_;
    moodycamel::ConcurrentQueue< std::function< void() > > tasks_;
    std::atomic< bool > stop_;
    std::atomic< int > active_tasks_;
};

} // namespace traffic::core
