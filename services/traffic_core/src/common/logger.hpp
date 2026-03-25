#pragma once

#include "quill/Backend.h"
#include "quill/Frontend.h"
#include "quill/LogMacros.h"
#include "quill/Logger.h"
#include "quill/sinks/ConsoleSink.h"

#include <cstdint>
#include <string>

namespace traffic::core::logging {

// Инициализация логгера (Zero-cost compiled out in Release for TRACE/DEBUG)
inline void init_logger(uint16_t backend_thread_core_id = 1) {
    quill::BackendOptions backend_options;
    
    // Explicit Thread Affinity: привязываем фоновый поток Quill к изолированному CPU ядру.
    // Это предотвращает попадание потока логгера на рабочие ядра пула потоков Роутера (L1/L2 cache pollution).
    backend_options.cpu_affinity = backend_thread_core_id;
    
    quill::Backend::start(backend_options);

    auto console_sink = quill::Frontend::create_or_get_sink<quill::ConsoleSink>("console_sink_1");
    
    quill::Logger* logger = quill::Frontend::create_or_get_logger(
        "nav_core", 
        std::move(console_sink),
        quill::PatternFormatterOptions{
            "%(time) [%(thread_id)] %(log_level:<9) %(logger:<12) %(message)", 
            "%H:%M:%S.%Qns", 
            quill::Timezone::LocalTime
        }
    );

#if defined(NDEBUG) || defined(QUILL_ACTIVE_LOG_LEVEL) && QUILL_ACTIVE_LOG_LEVEL == QUILL_LOG_LEVEL_INFO
    logger->set_log_level(quill::LogLevel::Info);
#else
    logger->set_log_level(quill::LogLevel::TraceL3);
#endif
}

inline quill::Logger* get_logger() {
    return quill::Frontend::get_logger("nav_core");
}

} // namespace traffic::core::logging

// Обертки над макросами QUILL для Zero-Cost (вырезаются компилятором в релизе для TRACE и DEBUG)
#define LOG_TRACE(...) QUILL_LOG_TRACE_L3(traffic::core::logging::get_logger(), __VA_ARGS__)
#define LOG_DEBUG(...) QUILL_LOG_DEBUG(traffic::core::logging::get_logger(), __VA_ARGS__)
#define LOG_INFO(...)  QUILL_LOG_INFO(traffic::core::logging::get_logger(), __VA_ARGS__)
#define LOG_WARN(...)  QUILL_LOG_WARNING(traffic::core::logging::get_logger(), __VA_ARGS__)
#define LOG_ERROR(...) QUILL_LOG_ERROR(traffic::core::logging::get_logger(), __VA_ARGS__)
#define LOG_FATAL(...) QUILL_LOG_CRITICAL(traffic::core::logging::get_logger(), __VA_ARGS__)
