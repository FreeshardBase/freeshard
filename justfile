default:
    just --list

run-from-backup backup-file:
    rm -rf run
    unzip "{{backup-file}}" -d run
