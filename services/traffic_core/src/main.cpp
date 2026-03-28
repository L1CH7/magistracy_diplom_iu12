#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <cstring>
#include <csignal>
#include <atomic>
#include <poll.h>
#include <sstream>
#include <expected>
#include <sys/wait.h>
#include <iomanip>
#include "common/logger.hpp"
#include "router/control/router_manager.hpp"
#include "common/graph_types.hpp"

using namespace traffic;

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

    traffic::core::logging::init_logger();
    LOG_INFO("=== Traffic Core Supervisor Server starting (C++26) ===");

    std::signal(SIGINT,  signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::string data_dir = argv[1];
    
    try {
        traffic::router::control::RouterManager manager;
        LOG_INFO("Supervisor: Loading graphs from directory: {}", data_dir);
        
        auto load_status = manager.LoadGraphs(data_dir);
        if (!load_status) {
            LOG_FATAL("SUPERVISOR: CRITICAL GRAPH LOAD FAILURE: {}", load_status.error());
            return 1;
        }
        LOG_INFO("Supervisor: Graphs loaded. Nodes: {}, Edges: {}", manager.num_nodes(), manager.num_edges());

        int server_fd = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd == -1) {
            LOG_FATAL("SUPERVISOR: Failed to create socket: {}", strerror(errno));
            return 1;
        }

        int opt = 1;
        setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = INADDR_ANY;
        address.sin_port = htons(5555);

        if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
            LOG_FATAL("SUPERVISOR: Bind failed on port 5555. Address already in use?");
            close(server_fd);
            return 1;
        }
        
        if (listen(server_fd, 100) < 0) {
            LOG_FATAL("SUPERVISOR: Listen failed: {}", strerror(errno));
            close(server_fd);
            return 1;
        }

        LOG_INFO("Supervisor: TCP Server is listening on 0.0.0.0:5555");
        std::cout << "Ожидание запросов..." << std::endl;

        struct pollfd fds_poll[1];
        fds_poll[0].fd = server_fd;
        fds_poll[0].events = POLLIN;

        while (keep_running) {
            int poll_ret = poll(fds_poll, 1, 500);
            if (poll_ret < 0) {
                if (errno == EINTR) continue;
                LOG_ERROR("SUPERVISOR: Poll error: {}", strerror(errno));
                break;
            }
            if (poll_ret == 0) continue;

            int client_fd = accept(server_fd, nullptr, nullptr);
            if (client_fd < 0) {
                LOG_WARN("SUPERVISOR: Failed to accept connection: {}", strerror(errno));
                continue;
            }

            char read_buf[8192] = {0}; 
            ssize_t n_read = read(client_fd, read_buf, sizeof(read_buf) - 1);
            
            if (n_read > 0) {
                std::string input_query(read_buf);
                LOG_DEBUG("SUPERVISOR: Incoming request detected ({} bytes)", n_read);

                pid_t worker_pid = fork();
                
                if (worker_pid == 0) {
                    // --- CHILD PROCESS (Worker) ---
                    std::signal(SIGINT, SIG_DFL);
                    
                    // Restart Quill Backend in the child process because threads are not inherited
                    quill::BackendOptions backend_options;
                    quill::Backend::start(backend_options);

                    std::stringstream ss_query(input_query);
                    std::string command;
                    ss_query >> command;

                    auto start_time = std::chrono::high_resolution_clock::now();
                    std::expected<traffic::RouteResponse, std::string> route_result = std::unexpected("Unknown command");

                    try {
                        if (command == "ll") {
                            int n_pts = 0;
                            if (ss_query >> n_pts && n_pts >= 2) {
                                std::vector<std::pair<float, float>> coords;
                                coords.reserve(n_pts);
                                for (int i = 0; i < n_pts; ++i) {
                                    float x, y;
                                    if (ss_query >> x >> y) {
                                        coords.push_back({x, y});
                                    }
                                }
                                if (coords.size() >= 2) {
                                    LOG_INFO("Worker {}: Routing ll with {} points", getpid(), coords.size());
                                    route_result = manager.RouteMultipointByCoords(coords);
                                } else {
                                    route_result = std::unexpected("Insufficient valid coordinates");
                                }
                            }
                        } else if (command == "id") {
                            int n_ids = 0;
                            if (ss_query >> n_ids && n_ids >= 2) {
                                std::vector<traffic::RoutePoint> wps;
                                wps.reserve(n_ids);
                                for (int i = 0; i < n_ids; ++i) {
                                    traffic::NodeID id;
                                    float off;
                                    if (ss_query >> id >> off) {
                                        wps.push_back({id, off});
                                    }
                                }
                                if (wps.size() >= 2) {
                                    LOG_INFO("Worker {}: Routing id with {} points", getpid(), wps.size());
                                    route_result = manager.RouteMultipoint(wps);
                                } else {
                                    route_result = std::unexpected("Insufficient valid waypoints");
                                }
                            }
                        } else {
                            // Legacy or single-pair support
                            std::stringstream ss_legacy(input_query);
                            float x1, y1, x2, y2;
                            if (ss_legacy >> x1 >> y1 >> x2 >> y2) {
                                route_result = manager.RouteByCoords(x1, y1, x2, y2);
                            }
                        }
                    } catch (const std::exception& e) {
                        LOG_ERROR("Worker CRASH: {}", e.what());
                        _exit(1);
                    }

                    auto end_time = std::chrono::high_resolution_clock::now();
                    float ms = std::chrono::duration<float, std::milli>(end_time - start_time).count();

                    std::stringstream ss_resp;
                    if (route_result) {
                        LOG_DEBUG("Worker: SUCCESS. Time: {}s, Latency: {:.3f}ms", route_result->total_time, ms);
                        ss_resp << "SUCCESS | Time: " << route_result->total_time << "s | "
                                << "Distance: " << std::fixed << std::setprecision(1) << route_result->total_length_m << "m | "
                                << "Latency: " << std::fixed << std::setprecision(3) << ms << "ms | "
                                << "Segments: " << route_result->path.size() << "\n";
                    } else {
                        LOG_ERROR("Worker: FAILED. Error: {}", route_result.error());
                        ss_resp << "ERROR | " << route_result.error() << " | Latency: " << std::fixed << std::setprecision(3) << ms << "ms\n";
                    }
                    
                    std::string final_msg = ss_resp.str();
                    send(client_fd, final_msg.c_str(), (int)final_msg.size(), 0);

                    close(client_fd);
                    _exit(0); 
                    
                } else if (worker_pid > 0) {
                    // --- PARENT PROCESS (Supervisor) ---
                    close(client_fd);
                    int w_status;
                    waitpid(worker_pid, &w_status, 0);
                    
                    if (WIFSIGNALED(w_status)) {
                        int w_sig = WTERMSIG(w_status);
                        LOG_FATAL("SUPERVISOR ALERT: Worker process CRASHED! Signal: {} ({}). Query: {}", 
                                 w_sig, (w_sig == 11 ? "SIGSEGV" : "ABNORMAL"), 
                                 input_query.substr(0, 60));
                    } else if (WIFEXITED(w_status) && WEXITSTATUS(w_status) != 0) {
                        LOG_ERROR("SUPERVISOR ERROR: Worker exited with failure code {}. Query: {}", 
                                  WEXITSTATUS(w_status), input_query.substr(0, 60));
                    } else {
                        LOG_TRACE("SUPERVISOR: Worker {} finished successfully", worker_pid);
                    }
                } else {
                    LOG_FATAL("SUPERVISOR: System error: fork() failed!");
                    close(client_fd);
                }
            } else {
                close(client_fd);
            }
        }

        close(server_fd);
        LOG_INFO("=== Traffic Core Supervisor Server shutting down cleanly ===");

    } catch (const std::exception& e) {
        LOG_FATAL("SUPERVISOR FATAL: System Exception: {}", e.what());
        return 1;
    }

    return 0;
}
