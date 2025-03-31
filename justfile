default:
    just --list

run-from-backup backup-file:
    rm -rf run
    unzip "{{backup-file}}" -d run

DIRECTORY := "../portal_controller/portal_controller_backend/portal_controller/types"
get-types:
    if [ ! -d {{DIRECTORY}} ]; then \
      echo "{{DIRECTORY}} does not exist. You need to clone portal_controller first."; exit 1; \
    fi
    rm -rf shard_core/model/backend
    mkdir -p shard_core/model/backend
    touch shard_core/model/backend/__init__.py
    cp -r {{DIRECTORY}}/* shard_core/model/backend
    sed -i '1s/^/# DO NOT MODIFY - copied from portal_controller\n\n/' $(find shard_core/model/backend/ -type f)

run-dev:
    CONFIG=config.yml,local_config.yml fastapi dev --port 8080 shard_core/app.py
