# The build image (DockerImages, modern-app-backend-build) carries Python 3.13,
# uv, the -dev packages wheels compile against, and uv's settings: the image's
# own Python, never a downloaded one, and copy mode.
FROM registry:5000/modern-app-backend-build AS build

WORKDIR /app

# --- Reproduce the environment ---
COPY pyproject.toml uv.lock /app/

# Install project deps into .venv
RUN uv sync --locked --no-dev --no-install-project

# copy your source (no re-resolution needed)
COPY *.py /app/
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY app /app/app

# The runtime image (DockerImages, modern-app-backend) carries tini, netcat and
# the shared libraries: libmagic, the image codecs and libpq.
FROM registry:5000/modern-app-backend

EXPOSE 3501

WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY --from=build /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    DATA_PATH=/app/data \
    FLASK_ENV=production

ENTRYPOINT ["tini", "--"]

CMD ["python","run.py"]
