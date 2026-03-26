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
            workers_.emplace_back( [this]() {
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
            } );

            if( use_affinity )
            {
#ifdef __linux__
                // Пропускаем 0 и 1 ядро если requested
                unsigned core_id = i;
                if( avoid_os_cores )
                {
                    core_id += 2;
                }
                
                cpu_set_t cpuset;
                CPU_ZERO( &cpuset );
                CPU_SET( core_id % std::thread::hardware_concurrency(), &cpuset );
                
                int rc = pthread_setaffinity_np( workers_.back().native_handle(), sizeof( cpu_set_t ), &cpuset );
                if( rc != 0 )
                {
                    std::println( stderr, "Failed to set thread affinity for core {}", core_id );
                }
#endif
            }
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

private:
    std::vector< std::thread > workers_;
    moodycamel::ConcurrentQueue< std::function< void() > > tasks_;
    std::atomic< bool > stop_;
    std::atomic< int > active_tasks_;
};

} // namespace traffic::core
