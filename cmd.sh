SAS_URL='<your SAS URL>'
PASSPHRASE='<your passphrase'
CONTAINER='<your backup container>'

rclone \
--azureblob-sas-url $SAS_URL \
--crypt-password $(rclone obscure "$PASSPHRASE") \
--crypt-remote ":azureblob:$CONTAINER" \
--stats 3s --stats-log-level NOTICE \
--progress --progress-terminal-title \
sync ":crypt:$CONTAINER" "./$CONTAINER"