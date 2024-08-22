# Portal Core

Core software stack that manages all aspects of a Portal

[API-doc](https://ptl.gitlab.io/portal_core/) of the latest stable release.

## Development

Run development server with `venv/bin/uvicorn portal_core:create_app --reload --factory`

Then, access API-doc at [http://localhost:8000/redoc](http://localhost:8000/redoc)

If you need to test features requiring the management backend, you can start a mock with
`venv/bin/uvicorn portal_core:create_app management_mock:app --port 8090`.
The development server is configured to use this mock.

## Running as an existing Portal

You can create a real Portal and run portal_core locally with its data and identity.
This is useful for testing against the portal_controller_backend because then,
the Portal exists in the backend database, and
you can grant it the needed permissions to access the backend.

From the existing Portal download the backup using the legacy method:
`https://<id>.p.getportal.org/core/protected/backup/export`.

Use the `just` command to import the backup:
`just run-from-backup Backup\ of\ Portal\ j8gn2l\ -\ 2024-06-16\ 06-00.zip`.

