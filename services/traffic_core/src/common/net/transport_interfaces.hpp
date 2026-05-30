#pragma once

#include <vector>
#include <span>
#include <cstdint>

namespace traffic
{
namespace common
{
namespace net
{

/**
 * @brief Abstract transport interface for byte-oriented communication.
 * Supporting both In-Process and Network interaction with Zero-Allocation focus.
 */
class ITransport
{
public:
    virtual ~ITransport() = default;

    /**
     * @brief Sends byte data through the transport.
     * @param data View of the byte sequence to be sent.
     */
    virtual void SendBytes( std::span< const uint8_t > data ) = 0;

    /**
     * @brief Receives byte data from the transport.
     * @param out_buffer Buffer to store received data. Should reuse capacity to avoid allocation.
     * @return true if data was received, false otherwise.
     */
    virtual bool ReceiveBytes( std::vector< uint8_t > & out_buffer ) = 0;

    /**
     * @brief Checks if the transport is network-based or local.
     */
    virtual bool IsNetwork() const noexcept = 0;

    /**
     * @brief Clears any pending data in the transport's queues.
     */
    virtual void Clear() {}
};

} // namespace net
} // namespace common
} // namespace traffic
