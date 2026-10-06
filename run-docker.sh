#!/bin/sh
# One-command launcher for Docker engines that do not include Compose.
# Docker Desktop users can use `docker compose up --build` directly.
set -eu
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then
  exec docker compose up --build
fi
command -v docker >/dev/null || { echo 'Install and start a Docker engine first.' >&2; exit 1; }
case "$(uname -s)" in Darwin) platform=darwin;; Linux) platform=linux;; *) echo 'Use Docker Desktop with Compose on this platform.' >&2; exit 1;; esac
case "$(uname -m)" in arm64|aarch64) arch=aarch64;; x86_64) arch=x86_64;; *) echo 'Unsupported CPU architecture.' >&2; exit 1;; esac
mkdir -p .tools/plugins .tools/config
if [ ! -x .tools/plugins/docker-compose ]; then
  base="https://github.com/docker/compose/releases/download/v2.39.4/docker-compose-$platform-$arch"
  curl -fL "$base" -o .tools/plugins/docker-compose.download
  curl -fL "$base.sha256" -o .tools/compose.sha256
  expected=$(cut -d ' ' -f 1 .tools/compose.sha256)
  actual=$(shasum -a 256 .tools/plugins/docker-compose.download | cut -d ' ' -f 1)
  [ "$expected" = "$actual" ] || { echo 'Compose checksum validation failed.' >&2; exit 1; }
  mv .tools/plugins/docker-compose.download .tools/plugins/docker-compose
  chmod +x .tools/plugins/docker-compose
fi
# This script never edits the user's Docker configuration. JSON uses Python's encoder.
python3 -c 'import json, pathlib; p=pathlib.Path(".tools/plugins").resolve(); pathlib.Path(".tools/config/config.json").write_text(json.dumps({"cliPluginsExtraDirs":[str(p)]}))'
if [ -z "${DOCKER_HOST:-}" ]; then
  DOCKER_HOST=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
  export DOCKER_HOST
fi
# Compose can also build with Docker's classic builder if buildx is not installed.
if ! docker buildx version >/dev/null 2>&1; then export DOCKER_BUILDKIT=0; fi
exec docker --config "$PWD/.tools/config" compose up --build
