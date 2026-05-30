# thread-affinity.cmake
# ──────────────────────────────────────────────────────────────────────────────
# Автоматическое вычисление привязки потоков traffic-core к ядрам CPU.
#
# Предполагаемая топология (Hyper-Threading, BIOS-нумерация Intel/AMD):
#
#   Логический CPU │ Физическое ядро │ Назначение
#   ───────────────┼─────────────────┼──────────────────────────────────────────
#   0,  N/2        │ 0               │ ОС (зарезервировано, не трогаем)
#   1,  1 + N/2    │ 1               │ Симулятор (1) + Диспетчер (1 + N/2)
#   2 .. N/2-1     │ 2 .. N/2-1      │ Пул маршрутизатора (первые потоки)
#   2+N/2 .. N-1   │ 2 .. N/2-1      │ Пул маршрутизатора (HT-потоки)
#
# Пример: N=12 (6 физических ядер × HT)
#   half=6, SIM=1, DISPATCH=7
#   ROUTER_THREADS=8, ROUTER_CORES="2,8,3,9,4,10,5,11"
#
# Пример: N=16 (8 физических ядер × HT)
#   half=8, SIM=1, DISPATCH=9
#   ROUTER_THREADS=12, ROUTER_CORES="2,10,3,11,4,12,5,13,6,14,7,15"
#
# Переопределение: задайте -DTRAFFIC_TOTAL_LOGICAL_CPUS=<N> в cmake-командной
# строке чтобы отключить авто-определение (0 = авто).
# ──────────────────────────────────────────────────────────────────────────────
include_guard(GLOBAL)

# --- 1. Определение числа логических CPU ---
set(TRAFFIC_TOTAL_LOGICAL_CPUS "0" CACHE STRING
    "Всего логических CPU (0 = авто-определение)")

if(TRAFFIC_TOTAL_LOGICAL_CPUS EQUAL 0)
    cmake_host_system_information(RESULT _cpus QUERY NUMBER_OF_LOGICAL_CORES)
    message(STATUS "[thread-affinity] Авто-определение: ${_cpus} логических CPU")
else()
    set(_cpus ${TRAFFIC_TOTAL_LOGICAL_CPUS})
    message(STATUS "[thread-affinity] Ручная настройка: ${_cpus} логических CPU")
endif()

# --- 2. Производные величины ---
math(EXPR _half     "${_cpus} / 2")          # кол-во физических ядер (HT)
math(EXPR _dispatch "1 + ${_half}")          # HT-сиблинг ядра 1 → диспетчер
math(EXPR _rphys    "${_half} - 2")          # физических ядер под роутер (2..half-1)
math(EXPR _rthreads "${_rphys} * 2")         # логических потоков роутера

# --- 3. Строка ядер роутера: "2,2+half, 3,3+half, ..." ---
set(_router_cores "")
set(_i 2)
while(_i LESS _half)
    math(EXPR _sib "${_i} + ${_half}")
    if(_router_cores STREQUAL "")
        set(_router_cores "${_i},${_sib}")
    else()
        set(_router_cores "${_router_cores},${_i},${_sib}")
    endif()
    math(EXPR _i "${_i} + 1")
endwhile()

# --- 4. Экспорт переменных (FORCE перекрывает любые предыдущие значения) ---
set(TRAFFIC_ROUTER_THREADS    "${_rthreads}"   CACHE STRING "Number of threads for router pool"                    FORCE)
set(TRAFFIC_ROUTER_CORES      "${_router_cores}" CACHE STRING "Explicit logical CPUs for router pool"              FORCE)
set(TRAFFIC_SIM_AFFINITY      "1"              CACHE STRING "Core 1 (Thread 1) for Main Simulator + MPR"           FORCE)
set(TRAFFIC_DISPATCH_AFFINITY "${_dispatch}"   CACHE STRING "HT-sibling of Core 1 for Router Dispatcher"          FORCE)
set(TRAFFIC_AVOID_OS_CORES    "1"              CACHE STRING "Reserved Core 0 (Threads 0, N/2) for OS"             FORCE)

message(STATUS "[thread-affinity] N=${_cpus}  half=${_half}")
message(STATUS "[thread-affinity] SIM=1  DISPATCH=${_dispatch}")
message(STATUS "[thread-affinity] ROUTER_THREADS=${_rthreads}  CORES=[${_router_cores}]")
