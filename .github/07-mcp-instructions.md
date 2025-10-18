# MCP Серверы - Инструкция по использованию

## Обзор активных серверов

### 1. Memory Bank (`memory-bank`)
Долгосрочная память для сохранения контекста между сессиями. Использует граф сущностей (entities) с наблюдениями (observations) и связями (relations).

**Путь к данным:** `.vscode/memory.json`

### 2. Sequential Thinking (`sequential-thinking`)
Пошаговое рассуждение для сложных задач. Помогает структурировать мышление и решать многоэтапные проблемы.

---

## Memory Bank - Работа с памятью

### Архитектура
- **Entities** - сущности (проекты, задачи, технологии, люди)
- **Observations** - наблюдения/факты о сущности
- **Relations** - связи между сущностями

### ⚠️ КРИТИЧЕСКИ ВАЖНО: Последовательность операций

**ВСЕГДА сначала создавайте entity, потом добавляйте observations!**

### Инструменты (Tools)

#### 1. `create_entities` - Создание сущностей

**Использование:**
```json
{
  "entities": [
    {
      "name": "pdf_extraction_project",
      "entityType": "project",
      "observations": [
        "Проект по извлечению данных из PDF в SQLite",
        "Работаем с секциями 1.2, 3.4, 2.2.1-2.2.3",
        "Таблицы: regions, power_consumption, electrification_power, railway_notes, railways"
      ]
    }
  ]
}
```

**Параметры:**
- `name` (string, required) - уникальное имя сущности
- `entityType` (string, required) - тип: project, task, technology, person, concept
- `observations` (array, optional) - начальные наблюдения

#### 2. `add_observations` - Добавление наблюдений

**⚠️ Работает ТОЛЬКО с существующими entities!**

```json
{
  "observations": [
    {
      "entityName": "pdf_extraction_project",
      "contents": [
        "Используем библиотеку PyMuPDF для извлечения текста",
        "Отказались от OCR, работаем только с текстовым слоем"
      ]
    }
  ]
}
```

**Параметры:**
- `entityName` (string, required) - имя существующей сущности
- `contents` (array, required) - массив новых наблюдений

**❌ ОШИБКА "Entity not found":**
Возникает при попытке добавить observation к несуществующей entity. Решение: сначала вызовите `create_entities`.

#### 3. `create_relations` - Создание связей

```json
{
  "relations": [
    {
      "from": "pdf_extraction_project",
      "to": "pymupdf_library",
      "relationType": "uses"
    }
  ]
}
```

**Типы связей:**
- `uses` - использует
- `requires` - требует
- `depends_on` - зависит от
- `related_to` - связано с
- `part_of` - часть чего-то

#### 4. `search_entities` - Поиск по памяти

```json
{
  "query": "PDF extraction techniques"
}
```

Возвращает релевантные entities с их observations.

---

## Sequential Thinking - Пошаговое рассуждение

### Когда использовать
- Сложные многоэтапные задачи
- Требуется последовательный анализ
- Нужно документировать процесс принятия решений

### Инструменты

#### 1. `start_thinking` - Начать рассуждение

Запускает процесс структурированного мышления. Сервер автоматически разбивает задачу на шаги.

#### 2. `continue_thinking` - Продолжить

Переход к следующему шагу анализа.

#### 3. `conclude_thinking` - Завершить

Формулирует финальный вывод на основе всех шагов.

### Пример использования

**Задача:** "Спроектировать архитектуру для извлечения данных из PDF"

1. `start_thinking` → анализ требований
2. `continue_thinking` → выбор библиотек
3. `continue_thinking` → структура базы данных
4. `continue_thinking` → обработка ошибок
5. `conclude_thinking` → финальное решение

---

## Практические сценарии

### Сценарий 1: Начало нового проекта

```json
// Шаг 1: Создать entity проекта
{
  "tool": "create_entities",
  "entities": [{
    "name": "railway_data_extraction",
    "entityType": "project",
    "observations": [
      "Извлечение данных о железных дорогах из PDF документов",
      "Целевые таблицы: regions, power_consumption, electrification_power, railway_notes, railways",
      "Используем PyMuPDF, SQLite"
    ]
  }]
}

// Шаг 2: Создать связанные технологии
{
  "tool": "create_entities",
  "entities": [
    {
      "name": "pymupdf",
      "entityType": "technology",
      "observations": ["Библиотека для работы с PDF без OCR"]
    },
    {
      "name": "sqlite",
      "entityType": "technology",
      "observations": ["Локальная реляционная БД"]
    }
  ]
}

// Шаг 3: Связать технологии с проектом
{
  "tool": "create_relations",
  "relations": [
    {"from": "railway_data_extraction", "to": "pymupdf", "relationType": "uses"},
    {"from": "railway_data_extraction", "to": "sqlite", "relationType": "uses"}
  ]
}
```

### Сценарий 2: Обновление прогресса задачи

```json
// ✅ ПРАВИЛЬНО: entity уже существует
{
  "tool": "add_observations",
  "observations": [{
    "entityName": "railway_data_extraction",
    "contents": [
      "Завершена обработка секции 1.2 - извлечены данные о регионах",
      "Столкнулись с проблемой: таблицы в PDF имеют непостоянную структуру",
      "Решение: парсинг по ключевым словам вместо позиционного"
    ]
  }]
}
```

### Сценарий 3: Работа с ошибками

```json
// ❌ ОШИБКА
{
  "tool": "add_observations",
  "observations": [{
    "entityName": "new_task",  // entity не существует!
    "contents": ["Описание задачи"]
  }]
}
// Результат: "Entity with name new_task not found"

// ✅ ИСПРАВЛЕНИЕ
{
  "tool": "create_entities",
  "entities": [{
    "name": "new_task",
    "entityType": "task",
    "observations": ["Описание задачи"]
  }]
}
```

### Сценарий 4: Сложная задача с Sequential Thinking

```json
// Используем sequential-thinking для архитектурного решения
{
  "tool": "start_thinking",
  "problem": "Как оптимально извлечь данные из 500+ страничного PDF?"
}

// Сервер последовательно анализирует:
// - Объем данных и производительность
// - Распараллеливание обработки
// - Кеширование промежуточных результатов
// - Обработка ошибок и восстановление

// Результат рассуждений сохраняем в memory:
{
  "tool": "add_observations",
  "observations": [{
    "entityName": "railway_data_extraction",
    "contents": [
      "Архитектурное решение: параллельная обработка по 50 страниц",
      "Используем multiprocessing.Pool с 4 воркерами",
      "Кешируем извлеченные таблицы в промежуточные JSON файлы"
    ]
  }]
}
```

---

## Рекомендации по использованию

### Memory Bank

1. **Структурируйте entities по типам:**
   - `project` - проекты верхнего уровня
   - `task` - конкретные задачи
   - `technology` - используемые технологии/библиотеки
   - `concept` - архитектурные концепции/паттерны
   - `person` - люди (при необходимости)

2. **Регулярно обновляйте observations:**
   - После значимых изменений в коде
   - При принятии архитектурных решений
   - При обнаружении важных проблем/решений

3. **Используйте relations для контекста:**
   - Связывайте задачи с проектами
   - Связывайте технологии с задачами
   - Документируйте зависимости

4. **Именование entities:**
   - Используйте snake_case: `pdf_extraction_project`
   - Делайте имена описательными
   - Избегайте дубликатов

### Sequential Thinking

1. **Применяйте для:**
   - Архитектурных решений
   - Отладки сложных багов
   - Выбора между альтернативами
   - Планирования многоэтапных задач

2. **Не используйте для:**
   - Простых вопросов
   - Синтаксических проблем
   - Быстрых поисков информации

3. **После завершения thinking:**
   - Сохраните выводы в Memory Bank
   - Создайте relations к релевантным entities
   - Документируйте ключевые решения

---

## Проверка состояния

### Поиск в памяти

```json
{
  "tool": "search_entities",
  "query": "railway extraction"
}
```

### Просмотр файла памяти

Файл `.vscode/memory.json` содержит:
```json
{
  "entities": [
    {
      "name": "project_name",
      "entityType": "project",
      "observations": [...]
    }
  ],
  "relations": [...]
}
```

---

## Устранение проблем

### "Entity not found"
**Причина:** Попытка `add_observations` к несуществующей entity  
**Решение:** Сначала `create_entities`, потом `add_observations`

### "Permission denied"
**Причина:** Нет прав на запись в `.vscode/memory.json`  
**Решение:** `chmod 644 .vscode/memory.json` или проверьте `MEMORY_FILE_PATH`

### Память не сохраняется
**Причина:** Неверный путь в конфигурации  
**Решение:** Проверьте `${workspaceFolder}/.vscode/memory.json` существует

### Sequential thinking зависает
**Причина:** Слишком сложная/нечеткая задача  
**Решение:** Разбейте на подзадачи, сформулируйте конкретнее

---

## Шпаргалка команд

```bash
# Создать новый проект в памяти
create_entities → entities: [{name, entityType: "project", observations}]

# Добавить прогресс к существующей задаче
add_observations → observations: [{entityName, contents}]

# Связать задачу с технологией
create_relations → relations: [{from, to, relationType: "uses"}]

# Найти в памяти
search_entities → query: "ключевые слова"

# Начать пошаговый анализ
start_thinking → problem: "описание проблемы"

# Продолжить анализ
continue_thinking

# Завершить и получить вывод
conclude_thinking
```

---

**Версия:** 1.0  
**Дата:** 13 октября 2025  
**Путь к памяти:** `.vscode/memory.json`
