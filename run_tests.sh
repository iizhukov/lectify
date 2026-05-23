#!/bin/bash

echo "🧪 Запуск интеграционных тестов Lectify..."
echo ""

# Проверка наличия pytest
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest не найден. Установите зависимости:"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Проверка PostgreSQL
echo "🔍 Проверка PostgreSQL..."
if ! docker exec lectify-postgres pg_isready -U lectify &> /dev/null; then
    echo "⚠️  PostgreSQL не запущен. Запустите docker-compose:"
    echo "   docker-compose up -d postgres"
    echo ""
fi

# Проверка MinIO
echo "🔍 Проверка MinIO..."
if ! curl -s http://localhost:9000/minio/health/live &> /dev/null; then
    echo "⚠️  MinIO не запущен. Запустите docker-compose:"
    echo "   docker-compose up -d minio"
    echo ""
fi

# Создание тестовой базы данных
echo "📦 Создание тестовой базы данных..."
docker exec lectify-postgres psql -U lectify -c "DROP DATABASE IF EXISTS lectify_test;" 2>/dev/null
docker exec lectify-postgres psql -U lectify -c "CREATE DATABASE lectify_test;" 2>/dev/null

echo ""
echo "▶️  Запуск тестов..."
echo ""

# Запуск тестов с опциями
pytest \
    -v \
    --tb=short \
    --cov=src \
    --cov-report=html \
    --cov-report=term-missing \
    --cov-branch \
    "$@"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Все тесты пройдены успешно!"
    echo ""
    echo "📊 Отчёт о покрытии: htmlcov/index.html"
    echo "   Откройте в браузере: open htmlcov/index.html"
else
    echo "❌ Некоторые тесты не прошли (код выхода: $EXIT_CODE)"
fi

echo ""
exit $EXIT_CODE
