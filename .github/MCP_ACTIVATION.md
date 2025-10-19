# 🚀 MCP СЕРВЕРЫ АКТИВИРОВАНЫ И ГОТОВЫ

## ✅ Что подключено

### 1. Memory Bank (`memory-bank`)
**Статус:** ✅ Активен и заполнен

**Сущности в памяти (8 объектов):**
- `diplom_navigation_mas` (project) - главный проект
- `navigation_client_gui` (task) - клиент с MapLibre
- `navigation_server_api` (task) - FastAPI сервер
- `technology_maplibre_gl` (technology)
- `technology_pyqt5_qwebengine` (technology)
- `technology_fastapi` (technology)
- `architecture_server_as_truth` (concept)
- `architecture_event_driven` (concept)

**Как пользоваться:**
```python
# Поиск в памяти
search_entities(query="что-то нужное")

# Добавить наблюдение к существующей сущности
add_observations(observations=[{
  "entityName": "navigation_client_gui",
  "contents": ["новое наблюдение 1", "новое наблюдение 2"]
}])

# Создать новую сущность
create_entities(entities=[{
  "name": "new_entity_name",
  "entityType": "task|technology|concept|project",
  "observations": ["obs1", "obs2"]
}])
```

### 2. Sequential Thinking (`sequential-thinking`)
**Статус:** ✅ Активен

**Когда использовать:**
- Сложные архитектурные решения (выбор между вариантами)
- Отладка многоэтапных проблем
- Планирование сложных задач

**Пример использования:**
```
User: "Как лучше реализовать маршрутизацию - Dijkstra vs Valhalla?"
Agent: sequential-thinking с анализом trade-off'ов
Result: Структурированный анализ с выводом
```

---

## 📋 ТЕКУЩИЙ СТАТУС (R-D-1, Итерация 1 ЗАВЕРШЕНА)

### ✅ Завершено
- MapLibre маркеры (From/To/Via) работают безошибочно
- Zoom slider двусторонняя синхронизация через HTTP API
- Контекстное меню для выбора маршрутных точек
- Selected Points panel с управлением
- Асинхронная инициализация MapLibre исправлена

### 📋 Следующие шаги (Итерация 2)
1. **Overpass API integration** - загрузка реальных OSM дорог
2. **OSM → NetworkX граф** - построение графа с атрибутами
3. **Dijkstra маршрутизация** - REST API /route
4. **Визуализация маршрута** - LineString на карте
5. **Симуляция движения агента** - плавная анимация

### 📁 Где смотреть
- Детальный статус: `.github/CURRENT_STATUS.md`
- Планы: `.github/05-navigation-mas-project.md`
- Архитектура: `.github/02-architecture-and-design.md`
- MCP помощь: `.github/07-mcp-instructions.md`

---

## 🔧 КАК НАЧАТЬ СЕССИЮ

1. **Изучить память:**
   ```
   search_entities(query="текущий статус маркеров")
   ```

2. **Просмотреть графы:**
   ```
   read_graph()  # весь граф сущностей и связей
   ```

3. **Если нужно сложное рассуждение:**
   ```
   sequential-thinking: "Как оптимально реализовать Overpass интеграцию?"
   ```

4. **При завершении задачи:**
   ```
   add_observations(...)  # обновить статус в памяти
   create_relations(...)   # связать новые entities если нужны
   ```

---

## 📚 БЫСТРАЯ ШПАРГАЛКА

### Memory Bank операции

| Операция | Параметры | Когда использовать |
|----------|-----------|-------------------|
| `create_entities` | entities[] | Новая сущность (project/task/tech/concept) |
| `add_observations` | observations[] | Обновить статус существующей сущности |
| `create_relations` | relations[] | Связать две сущности (uses, part_of, etc) |
| `search_entities` | query: string | Поиск по памяти |
| `read_graph` | - | Просмотреть весь граф |
| `open_nodes` | names[] | Получить детали конкретных сущностей |

### Типы relations

- `uses` - использует (client uses MapLibre)
- `requires` - требует
- `depends_on` - зависит от
- `part_of` - часть чего-то (task part of project)
- `related_to` - связано с

### Entity types

- `project` - проекты верхнего уровня
- `task` - конкретные задачи
- `technology` - технологии/библиотеки
- `concept` - архитектурные концепции
- `person` - люди (если нужны)

---

## 💾 ФАЙЛ ПАМЯТИ

Путь: `.vscode/memory.json`

Структура:
```json
{
  "entities": [
    {
      "name": "entity_name",
      "entityType": "project",
      "observations": ["obs1", "obs2", ...]
    }
  ],
  "relations": [
    {
      "from": "entity1",
      "to": "entity2",
      "relationType": "uses"
    }
  ]
}
```

**⚠️ ВАЖНО:** Файл управляется автоматически MCP сервером. Не редактируй вручную!

---

## 🎯 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ

### Пример 1: Проверить статус маркеров
```
User: "Какой статус маркеров на карте?"
Agent: search_entities(query="маркеры MapLibre статус")
Result: navigation_client_gui с наблюдениями о маркерах
```

### Пример 2: Обновить прогресс Overpass
```
Agent: add_observations({
  entityName: "navigation_server_api",
  contents: ["Реализована загрузка OSM через Overpass для bbox Москвы"]
})
```

### Пример 3: Архитектурное решение Dijkstra vs Valhalla
```
Agent: sequential-thinking
Problem: "Выбрать между Dijkstra (R-D-1) и Valhalla (R-D-2)"
Steps:
  1. Анализ требований R-D-1
  2. Сложность реализации
  3. Performance
  4. Миграция на R-D-2
Result: Dijkstra для R-D-1, потом миграция на Valhalla
```

---

## 🚨 РЕШЕНИЕ ПРОБЛЕМ

### Ошибка: "Entity not found"
**Причина:** Попытка `add_observations` к несуществующей сущности  
**Решение:** Сначала `create_entities`, потом `add_observations`

### Ошибка: "Permission denied на memory.json"
**Решение:** `chmod 644 .vscode/memory.json`

### Qdrant недоступен
**Нормально!** Это опциональный вектор-сторе. Memory-bank работает без него.

---

## 📞 КОНТАКТЫ В ПАМЯТИ

Все основные документы:
- `.github/05-navigation-mas-project.md` - полный план
- `.github/02-architecture-and-design.md` - архитектурные паттерны  
- `.github/01-senior-dev-principles.md` - подходы разработки
- `.github/CURRENT_STATUS.md` - текущий статус (обновляется)

---

**Обновлено:** 2025-10-19  
**Память в:** `.vscode/memory.json`  
**Status:** ✅ MCP готов к работе
