# Системная архитектура (краткая)

Этот файл агрегирует ключевые архитектурные решения с ссылками на подробности.

- Сравнение вариантов и консенсус: см. `.github/ARCHITECTURE_OPTIONS.md`.
- Принципы, контракты, паттерны: см. `.github/02-architecture-and-design.md`.
- Формулировка задачи и план R-D: см. `.github/05-navigation-mas-project.md`.
- Роутинг/симуляция, realtime: см. `.github/ROUTING_SIMULATION.md`.

Диаграммы (будут добавлены):
- Контейнерная схема (client/server/db/redis/valhalla/sumo)
- Диаграмма потоков событий (телеметрия → скорости → tiles → пере-роутинг)
- Слои клиентского приложения (PyQt ↔ JS MapLibre)
