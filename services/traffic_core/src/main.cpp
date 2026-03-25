#include "common/logger.hpp"
#include <iostream>

int main() {
    // Инициализируем систему логгера, привязываем бекграунд-поток к ядру 1 (для избежания False Sharing)
    traffic::core::logging::init_logger(1);

    LOG_INFO("Traffic Core Root initialized. Awaiting modules configuration.");
    
    return 0;
}
