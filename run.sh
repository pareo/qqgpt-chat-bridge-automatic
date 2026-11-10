#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  echo '需要安装 Docker Engine 和 Docker Compose v2+。' >&2
  exit 1
fi
docker compose version >/dev/null
docker info >/dev/null
if [ "$(docker info --format '{{.OSType}}')" != linux ]; then
  echo '需要切换到 Linux 容器引擎。' >&2
  exit 1
fi
action=${1:-help}
shift "$(( $# > 0 ? 1 : 0 ))"
tool() { docker run --rm -i --add-host host.docker.internal:host-gateway --mount "type=bind,source=$(pwd),target=/project" --entrypoint python sengokucola/maibot@sha256:ada1d38593fe4756cc1b8af100ec62136d0e011416cd2cfd7908cdb1422443eb /project/scripts/project.py "$@"; }
case "$action" in
  help) echo '命令: init | configure | setup | start | stop | restart | status | logs | api-check | test | webui | napcat-webui';;
  init) tool init;;
  configure|api-check) tool "$action" "$@";;
  doctor) tool check;;
  setup) docker compose --env-file config/generated/deployment.env up -d --build core;;
  start) tool check; docker compose --env-file config/generated/deployment.env up -d --build;;
  stop) docker compose --env-file config/generated/deployment.env stop;;
  restart) docker compose --env-file config/generated/deployment.env restart;;
  status) docker compose --env-file config/generated/deployment.env ps -a; docker compose --env-file config/generated/deployment.env exec -T core python -m src.cli.tool host status -d /MaiMBot; docker compose --env-file config/generated/deployment.env exec -T core python /project/scripts/runtime_status.py; docker compose --env-file config/generated/deployment.env exec -T core python /project/scripts/api_smoke.py qq-status;;
  logs) docker compose --env-file config/generated/deployment.env logs --tail 120 -f "$@";;
  test) docker compose --env-file config/generated/deployment.env run --rm --no-deps --entrypoint python core -m unittest discover -s /project/tests -v;;
  webui) docker compose --env-file config/generated/deployment.env exec -T core python -m src.cli.tool host open-webui -d /MaiMBot | tool map-webui-url;;
  napcat-webui) tool napcat-url;;
  *) echo '未知命令，请运行 ./run.sh help' >&2; exit 2;;
esac
