# Portal Core

Core software stack that manages all aspects of a Portal

[API-doc](https://ptl.gitlab.io/portal_core/) of the latest stable release.

## Development

Run development server with `venv/bin/uvicorn portal_core:create_app --reload --factory`

Then, access API-doc at [http://localhost:8000](http://localhost:8000)

### Running docker containers as dependency for unittests

Some unit tests require other services to run. These are automatically started via docker. This takes a while and makes running the tests slow. Manually start an instance and keep it running and the tests will use that instance instead.

```shell
docker run -p 15672:15672 -p 5672:5672 --name rabbitmq rabbitmq:3-management-alpine
```
