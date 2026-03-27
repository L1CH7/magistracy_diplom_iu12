import socket
import random
import time
import subprocess
import os

def get_node_ids():
    """Попытка достать реальные ID из базы через psql"""
    try:
        # Пытаемся подключиться к базе для получения реальных ID
        cmd = ["psql", "-t", "-A", "-c", "SELECT id FROM graphs.eb_nodes LIMIT 500", 
               "postgresql://postgres:postgres@localhost/nav_mas"]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().splitlines()
        ids = [line.strip() for line in output if line.strip()]
        return ids
    except Exception:
        # Если psql нет, используем диапазон
        return [str(i) for i in range(1, 1001)]

def run_test(host='localhost', port=5555, count=100):
    nodes = get_node_ids()
    if not nodes:
        print("No nodes found!")
        return

    print(f"--- Starting Detailed Load Test: {count} queries ---")
    print(f"{'#':<4} | {'Query':<15} | {'Latency':<10} | {'Response'}")
    print("-" * 60)
    
    latencies = []
    
    for i in range(1, count + 1):
        start_node = random.choice(nodes)
        target_node = random.choice(nodes)
        query_str = f"{start_node} {target_node}"
        
        start_t = time.perf_counter()
        response = "ERROR"
        try:
            with socket.create_connection((host, port), timeout=1) as s:
                s.sendall((query_str + "\n").encode())
                response = s.recv(1024).decode().strip()
                success = True
        except Exception as e:
            response = f"FAIL: {e}"
            success = False
            
        end_t = time.perf_counter()
        dur_ms = (end_t - start_t) * 1000
        
        if success:
            latencies.append(dur_ms)
            print(f"{i:<4} | {query_str:<15} | {dur_ms:7.3f} ms | {response}")
        else:
            print(f"{i:<4} | {query_str:<15} | {'--':>10} | {response}")

    if latencies:
        avg = sum(latencies) / len(latencies)
        max_l = max(latencies)
        min_l = min(latencies)
        # 95th percentile
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        
        print("\n" + "="*40)
        print(f"OVERALL STATISTICS:")
        print(f"  Success Rate:  {len(latencies)}/{count}")
        print(f"  Min Latency:   {min_l:7.3f} ms")
        print(f"  Avg Latency:   {avg:7.3f} ms")
        print(f"  95th Perc:     {p95:7.3f} ms")
        print(f"  Max Latency:   {max_l:7.3f} ms")
        print("="*40)

if __name__ == "__main__":
    run_test()
