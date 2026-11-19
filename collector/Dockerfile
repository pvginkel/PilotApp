# The pilot-collector image: the collector's walk and its readings, one process,
# `python -m pilot_collector`. Its build context is the repository's root, not
# collector/: the packages the collector takes by path lie in backend/packages,
# and the root's .dockerignore keeps the context to what this file copies.

# The build and runtime images the backend's image is built on (DockerImages,
# modern-app-backend-build and modern-app-backend): one Python in both, uv, and
# tini.
FROM registry:5000/modern-app-backend-build AS build

# The environment is built where the runtime image holds it: its scripts name
# their interpreter by that path.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src/collector

# The lock names both packages by path, so `uv sync --locked` reads each one's
# pyproject.toml: pilot-collection's, which it installs, and pilot-scenario's,
# the dev group's, which it does not.
COPY backend/packages/pilot-collection /src/backend/packages/pilot-collection
COPY backend/packages/pilot-scenario/pyproject.toml /src/backend/packages/pilot-scenario/pyproject.toml
COPY collector/pyproject.toml collector/uv.lock /src/collector/

RUN uv sync --locked --no-dev --no-install-project

COPY collector/src /src/collector/src

# --no-editable: the collector and pilot-collection are installed whole into the
# environment, where an editable install links back into /src, which the
# runtime image does not hold.
RUN uv sync --locked --no-dev --no-editable

FROM registry:5000/modern-app-backend

# The readings' port, COLLECTOR_PORT's default.
EXPOSE 3503

WORKDIR /app

COPY --from=build /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}"

# The fleet's home is its environments' user's, uid 1000, and a transcript there
# is that user's alone to read (mode 600).
USER 1000:1000

# Fails the build where the image, as that user, cannot load the process: a
# package left out of the environment, or linked into the build stage's tree.
RUN python -c "import pilot_collector.__main__"

ENTRYPOINT ["tini", "--"]

CMD ["python", "-m", "pilot_collector"]
