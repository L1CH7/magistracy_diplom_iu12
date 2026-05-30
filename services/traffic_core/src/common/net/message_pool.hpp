#pragma once

#include <vector>
#include <cstdint>

#include <concurrentqueue/concurrentqueue.h>

namespace traffic
{
namespace common
{
namespace net
{

/**
 * @brief Zero-Allocation pool for byte buffers.
 * Maintains a free_list of vectors to avoid re-allocations in the hot loop.
 */
class MessagePool
{
public:
    /**
     * @brief Acquires a buffer from the pool or creates a new one if the pool is empty.
     * @return std::vector< uint8_t > buffer with preserved capacity.
     */
    std::vector< uint8_t > Acquire()
    {
        std::vector< uint8_t > buf;
        
        if( !free_list_.try_dequeue( buf ) )
        {
            // Initial allocation if pool is empty
            return std::vector< uint8_t >();
        }

        return buf;
    }

    /**
     * @brief Returns the buffer to the pool for reuse.
     * @param buf Buffer to release. Ownership is transferred back to the pool.
     */
    void Release( std::vector< uint8_t > && buf )
    {
        // We don't clear the capacity, only the size
        buf.clear();
        free_list_.enqueue( std::move( buf ) );
    }

private:
    moodycamel::ConcurrentQueue< std::vector< uint8_t > > free_list_;
};

} // namespace net
} // namespace common
} // namespace traffic
