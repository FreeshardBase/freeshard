<picture>
    <source media="(prefers-color-scheme: dark)" srcset="readme/Freeshard_logo_for_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="readme/Freeshard_logo_for_light.png">
    <img alt="Freeshard Logo" src="readme/Freeshard_logo_for_light.png">
</picture>

# Shard Core

Core software stack that manages all aspects of a Shard.

[API-doc](https://ptl.gitlab.io/portal_core/) of the latest stable release.

## Development

Run development server with `venv/bin/uvicorn shard_core:create_app --reload --factory`

Then, access API-doc at [http://localhost:8000/redoc](http://localhost:8000/redoc)

If you need to test features requiring the management backend, you can start a mock with
`venv/bin/uvicorn shard_core:create_app management_mock:app --port 8090`.
The development server is configured to use this mock.
