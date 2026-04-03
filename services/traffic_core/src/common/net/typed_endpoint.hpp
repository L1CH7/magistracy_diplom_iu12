#pragma once

#include <memory>
#include <vector>
#include <span>
#include <cstring>

#include "transport_interfaces.hpp"

namespace traffic
{
namespace common
{
namespace net
{

/**
 * @brief High-level facade for modules to exchange typed messages.
 * Maps high-level types to byte-oriented transport with Zero-Allocation focus.
 */
template< typename TOut, typename TIn >
class TypedEndpoint final
{
    static_assert( std::is_trivially_copyable_v< TOut > && std::is_trivially_copyable_v< TIn >,
                   "TypedEndpoint requires trivially copyable (POD) types for high-performance zero-copy." );

public:
    explicit TypedEndpoint( std::unique_ptr< ITransport > transport )
    :   transport_( std::move( transport ) )
    {
        // One empty line after constructor definition as per Rule 00
    }

    /**
     * @brief Sends a typed payload by converting it to a byte span.
     * @param payload View of the objects to send.
     */
    void Send( std::span< const TOut > payload )
    {
        if( !transport_ )
        {
            return;
        }

        // Convert typed span to byte span for the transport layer
        std::span< const uint8_t > byte_view(
            reinterpret_cast< const uint8_t * >( payload.data() ),
            payload.size_bytes() );
            
        transport_->SendBytes( byte_view );
    }

    /**
     * @brief Receives typed data into a provided buffer.
     * @param out_buffer Output buffer that must preserve capacity.
     * @return true if data was received, false otherwise.
     */
    bool Receive( std::vector< TIn > & out_buffer )
    {
        if( !transport_ )
        {
            return false;
        }

        // Thread-local temporary buffer to avoid repeated allocations across calls
        static thread_local std::vector< uint8_t > temp_buf;

        if( transport_->ReceiveBytes( temp_buf ) )
        {
            const size_t num_elements = temp_buf.size() / sizeof( TIn );
            
            // Manage capacity of the provided output buffer
            if( out_buffer.capacity() < num_elements )
            {
                out_buffer.reserve( num_elements );
            }
            
            out_buffer.resize( num_elements );
            
            // High-speed copy designed for AVX/L1 cache optimization
            std::memcpy( out_buffer.data(), temp_buf.data(), temp_buf.size() );
            
            return true;
        }

        return false;
    }

private:
    std::unique_ptr< ITransport > transport_;
};

} // namespace net
} // namespace common
} // namespace traffic
