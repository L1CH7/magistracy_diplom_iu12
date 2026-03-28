#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <format>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <cstring>
#include <csignal>
#include <atomic>
#include <poll.h>
#include "common/logger.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/control/graph_loader.hpp"
#include "common/mmap_region.hpp"

using namespace traffic;
using namespace traffic::router;

static std::atomic<bool> keep_running(true);

void signal_handler(int sig) {
    if (sig == SIGINT || sig == SIGTERM) {
        keep_running = false;
        std::cout << "\nПолучен сигнал завершения. Останавливаем сервер..." << std::endl;
    }
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <data_dir>" << std::endl;
        return 1;
    }

    std::signal(SIGINT,  signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::string data_dir = argv[1];
    
    // 1. Initialize MappedGraph
    control::MappedGraph mapped_graph;
    try {
        if (!mapped_graph.load(data_dir)) {
            throw std::runtime_error("Failed to load graph from " + data_dir);
        }
        
        const uint32_t* header = reinterpret_cast<const uint32_t*>(mapped_graph.csr_region->data());
        uint32_t num_nodes = header[0];

        TdAltRouter router(mapped_graph.view, num_nodes);

        // 2. Assign Landmarks (if loaded)
        if (mapped_graph.landmarks_region) {
            router.get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph.landmarks_region->data()));
        }

        // 3. TCP Server (Port 5555)
        int server_fd = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd == -1) throw std::runtime_error("Socket failed");

        int opt = 1;
        setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = INADDR_ANY;
        address.sin_port = htons(5555);

        if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
            close(server_fd);
            throw std::runtime_error("Bind failed. Port 5555 might be busy.");
        }
        
        if (listen(server_fd, 3) < 0) {
            close(server_fd);
            throw std::runtime_error("Listen failed");
        }

        std::cout << "Поднят сервер на порту 5555" << std::endl;
        std::cout << "Ожидание запросов (Ctrl+C для выхода)..." << std::endl;

        struct pollfd fds[1];
        fds[0].fd = server_fd;
        fds[0].events = POLLIN;

        while (keep_running) {
            // Ожидаем активности на сокете 500мс, чтобы не блокировать вечно и проверять keep_running
            int ret = poll(fds, 1, 500);
            
            if (ret < 0) {
                if (errno == EINTR) continue;
                break;
            }
            if (ret == 0) continue; // Timeout, check keep_running

            int client_fd = accept(server_fd, nullptr, nullptr);
            if (client_fd < 0) continue;

            char buffer[1024] = {0};
            int bytes_read = read(client_fd, buffer, 1024);
            if (bytes_read > 0) {
                NodeID start_node, target_node;
                if (sscanf(buffer, "%u %u", &start_node, &target_node) == 2) {
                    auto start_time = std::chrono::high_resolution_clock::now();
                    auto result = router.find_path(start_node, target_node);
                    auto end_time = std::chrono::high_resolution_clock::now();
                    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(end_time - start_time);

                    std::string response = std::format("Weight: {} | Time: {}us | Path size: {}\n", 
                                                    result.total_weight, duration.count(), result.path.size());
                    
                    send(client_fd, response.c_str(), response.size(), 0);
                } else {
                    const char* err = "Invalid format. Expected: <start_node> <target_node>\n";
                    send(client_fd, err, strlen(err), 0);
                }
            }
            close(client_fd);
        }

        close(server_fd);
        std::cout << "Сервер остановлен успешно." << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
