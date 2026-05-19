#!/bin/bash
set -e

# Опеределяем пути
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$DIR/.venv"

# Принудительная очистка старых версий в корне (если остались)
if [ -f "$DIR/../monitor_black_zones.sh" ]; then
    rm -f "$DIR/../monitor_black_zones.sh"
fi
if [ -f "$DIR/../monitor_black_zones.py" ]; then
    rm -f "$DIR/../monitor_black_zones.py"
fi

# Проверяем или создаем локальное виртуальное окружение
if [ ! -d "$VENV_DIR" ]; then
    echo "================================================================================"
    echo "Создание выделенного виртуального окружения для диагностических скриптов..."
    echo "Путь: $VENV_DIR"
    echo "================================================================================"
    python3 -m venv "$VENV_DIR"
    
    echo "Обновление pip и установка зависимостей из scripts/requirements.txt..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$DIR/requirements.txt"
    echo "Инициализация окружения успешно завершена!"
    echo "================================================================================"
fi

# Запуск основного диагностического скрипта
exec "$VENV_DIR/bin/python" "$DIR/monitor_black_zones.py" "$@"
