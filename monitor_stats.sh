#!/bin/bash

# Скрипт для мониторинга симуляции Traffic Core
# Опрашивает API Gateway каждые 5 секунд и выводит данные.

URL="http://localhost:8000/api/v1/sim/stats"

echo "=== Traffic Core Diagnostics Monitor ==="
echo "Опрашиваем: $URL каждые 5 сек."
echo "Нажмите Ctrl+C для выхода."
echo "--------------------------------------------------------"

while true; do
    echo -e "\n[$(date +'%H:%M:%S')] Запрос метрик..."
    
    # Делаем запрос и парсим через jq, если он установлен
    RESPONSE=$(curl -s -m 2 $URL)
    
    if [ -z "$RESPONSE" ]; then
        echo -e "\e[31mОшибка: Gateway недоступен или не отвечает!\e[0m"
    else
        if command -v jq &> /dev/null; then
            # Красивый вывод с помощью jq
            STATUS=$(echo $RESPONSE | jq -r '.status')
            if [ "$STATUS" == "success" ]; then
                echo $RESPONSE | jq -r '.data | "
  Время симуляции : \(.sim_time | round) сек.
  Текущее ускорение: \(.current_accel)x
  Активных агентов: \(.active_agents) / \(.configured_agents) (ASF: \(.asf))
  
  -- Метрики поездок --
  Новых спавнов : \(.total_spawns)
  Рероутов MPR  : \(.reroutes)
  Завершено     : \(.routes_completed) (Неудачно: \(.routes_failed))
  TTI (Global)  : \(.tti_global | (.*100|round/100)) (Выборка: \(.tti_samples))
                "'
            else
                echo -e "\e[31mОшибка ответа API:\e[0m"
                echo $RESPONSE | jq .
            fi
        else
            # Резервный вывод без jq
            echo $RESPONSE
            echo -e "\e[33m(Установите 'jq' для красивого форматирования: sudo apt install jq)\e[0m"
        fi
    fi
    
    sleep 5
done
