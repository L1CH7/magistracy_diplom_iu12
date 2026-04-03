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
     * @brief Connects this transport to another one to form a pipe.
     * @param remote Pointer to the destination transport.
     */
    void SetRemote( InProcTransport * remote )
    {
        remote_ = remote;
    }

    /**
     * @brief Sends byte data through the ready queue (internal or remote).
     * @param data View of the byte sequence.
     */
    void SendBytes( std::span< const uint8_t > data ) override
    {
        std::vector< uint8_t > buf = pool_.Acquire();
        
        buf.resize( data.size() );
        std::memcpy( buf.data(), data.data(), data.size() );
        
        if( remote_ )
        {
            remote_->ready_queue_.enqueue( std::move( buf ) );
        }
        else
        {
            ready_queue_.enqueue( std::move( buf ) );
        }
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

    bool IsNetwork() const noexcept override
    {
        return false;
    }

private:
    MessagePool pool_;
    moodycamel::ConcurrentQueue< std::vector< uint8_t > > ready_queue_;
    InProcTransport * remote_ = nullptr;
};

} // namespace net
} // namespace common
} // namespace traffic
