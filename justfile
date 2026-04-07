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

@set-version version:
    just _set-version-files {{version}}
    git add .
    git commit -m "set version to {{version}}"
    echo "Version set to {{version}} and committed"

_set-version-files version:
    #!.venv/bin/python
    import re
    # Update version in pyproject.toml
    with open('pyproject.toml') as f:
        content = f.read()
    content = re.sub(r'(?m)^version = ".*"$', 'version = "{{version}}"', content)
    with open('pyproject.toml', 'w') as f:
        f.write(content)
    # Update image tag in docker-compose.yml
    with open('docker-compose.yml') as f:
        content = f.read()
    content = re.sub(r'(ghcr\.io/freeshardbase/freeshard:)[\w.\-]+', r'\g<1>{{version}}', content)
    with open('docker-compose.yml', 'w') as f:
        f.write(content)

run-dev:
    PYTHONUNBUFFERED=1 CONFIG=config.yml,local_config.yml ./.venv/bin/fastapi dev --port 8080 shard_core/app.py

run-dev-for-freeshard-controller:
    PYTHONUNBUFFERED=1 CONFIG=config.yml,local_config.yml UVICORN_PORT=8001 FREESHARD_FREESHARD_CONTROLLER_BASE_URL=http://127.0.0.1:8080 ./.venv/bin/fastapi dev --port 8081 shard_core/app.py
