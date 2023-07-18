# Build
FROM python:3.11 as build

RUN python3 -m venv /venv
COPY . /project
RUN /venv/bin/pip install /project

# Production
FROM python:3.11 as production

RUN apt-get update && apt-get install -y docker docker-compose

COPY --from=build /venv /venv
COPY config.yml .
COPY data/ /data/
RUN mkdir /core

HEALTHCHECK --start-period=5s CMD curl -f localhost/public/health || exit 1
ENV FLASK_APP=portal_core
EXPOSE 80
CMD [ "venv/bin/uvicorn", "portal_core:create_app", "--factory", "--host", "0.0.0.0", "--port", "80", "--no-access-log" ]
