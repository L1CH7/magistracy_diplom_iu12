#pragma once

#include <cstring>
#include <stdexcept>

#include "transport_interfaces.hpp"
#include "message_pool.hpp"

namespace traffic
{
namespace common
{
namespace net
{

/**
 * @brief Implementation of ITransport for high-performance In-Process communication.
 * Uses a message pool and lock-free queues to achieve zero allocation in the hot loop.
 */
class InProcTransport final
:   public ITransport
{
public:
    InProcTransport() = default;
    ~InProcTransport() override = default;

    /**
     * @brief Sends byte data through the ready queue.
     * @param data View of the byte sequence.
     */
    void SendBytes( std::span< const uint8_t > data ) override
    {
        std::vector< uint8_t > buf = pool_.Acquire();
        
        // resize() here might allocate if capacity is smaller,
        // but pool's vectors should quickly reach a steady state.
        buf.resize( data.size() );
        std::memcpy( buf.data(), data.data(), data.size() );
        
        ready_queue_.enqueue( std::move( buf ) );
    }

    /**
     * @brief Receives byte data from the ready queue.
     * @param out_buffer Output buffer that preserves capacity across calls.
     * @return true if data was received, false otherwise.
     */
    bool ReceiveBytes( std::vector< uint8_t > & out_buffer ) override
    {
        std::vector< uint8_t > buf;
        
        if( ready_queue_.try_dequeue( buf ) )
        {
            // Zero-allocation goal: preserve capacity of the user-provided buffer.
            if( out_buffer.capacity() < buf.size() )
            {
                out_buffer.reserve( buf.size() );
            }
            
            out_buffer.resize( buf.size() );
            std::memcpy( out_buffer.data(), buf.data(), buf.size() );
            
            pool_.Release( std::move( buf ) );
            return true;
        }

        return false;
    }

    /**
     * @brief Always returns false for In-Process transport.
     */
    bool IsNetwork() const noexcept override
    {
        return false;
    }

private:
    MessagePool pool_;
    moodycamel::ConcurrentQueue< std::vector< uint8_t > > ready_queue_;
};

} // namespace net
} // namespace common
} // namespace traffic
