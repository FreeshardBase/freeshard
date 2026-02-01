default:
    just --list

cleanup:
    .venv/bin/ruff check . --fix
    .venv/bin/black shard_core
    .venv/bin/black tests

run-from-backup backup-file:
    rm -rf run
    unzip "{{backup-file}}" -d run

SOURCE_DIR := "../freeshard-controller/freeshard-controller-backend/freeshard_controller/data_model"
TARGET_DIR := "shard_core/data_model/backend"
get-types:
    if [ ! -d {{SOURCE_DIR}} ]; then \
      echo "{{SOURCE_DIR}} does not exist. You need to clone freeshard-controller first."; exit 1; \
    fi
    rm -rf {{TARGET_DIR}}
    mkdir -p {{TARGET_DIR}}
    touch {{TARGET_DIR}}/__init__.py
    cp -r {{SOURCE_DIR}}/* {{TARGET_DIR}}
    sed -i '1s/^/# DO NOT MODIFY - copied from freeshard-controller\n\n/' $(find {{TARGET_DIR}}/ -type f)

run-dev:
    PYTHONUNBUFFERED=1 CONFIG=config.yml,local_config.yml ./.venv/bin/fastapi dev --port 8080 shard_core/app.py

run-dev-for-freeshard-controller:
    PYTHONUNBUFFERED=1 CONFIG=config.yml,local_config.yml UVICORN_PORT=8001 FREESHARD_FREESHARD_CONTROLLER_BASE_URL=http://127.0.0.1:8080 ./.venv/bin/fastapi dev --port 8081 shard_core/app.py

postgres-start:
    docker compose -f tests/docker-compose.yml up

postgres-reset:
    docker compose -f tests/docker-compose.yml rm -f

postgres-connect:
    docker exec -it test_postgres psql -U test_user -d test_db
