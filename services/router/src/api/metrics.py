import time
import functools
from fastapi import HTTPException
from prometheus_client import Histogram, Gauge, Counter, Summary

# Метрики мониторинга
ROUTING_DURATION = Histogram(
    'routing_search_duration_seconds', 
    'Time spent finding routes',
    ['k', 'status']
)
ROUTING_EFFICIENCY = Summary(
    'routing_search_efficiency',
    'Duration per edge found (seconds/edge)',
    ['k']
)
ROUTING_DIVERSITY = Gauge(
    'routing_diversity_actual',
    'Diversity score of the returned routes'
)
ROUTING_RESULT_COUNT = Counter(
    'routing_result_count',
    'Number of routes found vs requested',
    ['requested_k', 'found_count']
)
ROUTING_COMPLEXITY = Histogram(
    'routing_edges_count',
    'Number of edges in the found paths',
    ['k']
)

def observe_routing_metrics(func):
    """
    Декоратор для автоматического сбора метрик маршрутизации.
    Обертывает асинхронную функцию calculate_route.
    """
    @functools.wraps(func)
    async def wrapper(request, body, *args, **kwargs):
        start_time = time.time()
        status = "found"
        
        try:
            # Вызов оригинальной функции
            response = await func(request, body, *args, **kwargs)
            
            # Сбор метрик успешного выполнения
            if response and response.routes:
                
                # Efficiency & Complexity
                total_edges = sum(len(r.edge_ids) for r in response.routes)
                duration = time.time() - start_time
                
                if total_edges > 0:
                    ROUTING_EFFICIENCY.labels(k=body.k).observe(duration / total_edges)
                
                for r in response.routes:
                    ROUTING_COMPLEXITY.labels(k=body.k).observe(len(r.edge_ids))
                
                # Diversity (среднее)
                avg_diversity = sum(r.diversity_score for r in response.routes) / len(response.routes)
                ROUTING_DIVERSITY.set(avg_diversity)
                
                # Result Count
                ROUTING_RESULT_COUNT.labels(requested_k=body.k, found_count=len(response.routes)).inc()
            else:
                status = "not_found"

            return response

        except HTTPException as he:
            status = "not_found" if he.status_code == 404 else "error"
            raise he
        except Exception as e:
            status = "error"
            raise e
        finally:
            # Duration всегда пишем (даже при ошибках)
            duration = time.time() - start_time
            ROUTING_DURATION.labels(k=body.k, status=status).observe(duration)
            
    return wrapper
