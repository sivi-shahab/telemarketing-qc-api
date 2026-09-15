#!/usr/bin/env bash
# E2E telemarketing QC — satu perintah dari nol sampai Allure report.
#
#   ./jalankan.sh            jalankan penuh (bangun stack, test, report)
#   ./jalankan.sh test       hanya test + report (stack dianggap sudah jalan)
#   ./jalankan.sh bersih     hentikan stack dan buang volume-nya
#
# Seluruhnya TERISOLASI: postgres, redis, minio, dan LLM stub lokal.
# Tidak satu nilai pun di .env.e2e menunjuk produksi.
set -euo pipefail
cd "$(dirname "$0")"

TRANSKRIP="${E2E_TRANSKRIP:-/data/scorecard_v2/data_transcripts/raw/sources/returned/060257HO0l}"
DIST="${E2E_DIST_DIR:-/data/scorecard_v2/telemarketing-qc-dashboard/dist}"
COMPOSE="docker compose -f docker-compose.e2e.yml"

bersih() { $COMPOSE down -v; }
[ "${1:-penuh}" = "bersih" ] && { bersih; exit 0; }

if [ "${1:-penuh}" = "penuh" ]; then
  echo "── membangun & menyalakan stack terisolasi"
  $COMPOSE up -d --build
  echo "── menunggu API sehat"
  until [ "$(docker inspect -f '{{.State.Health.Status}}' e2e-api 2>/dev/null)" = "healthy" ]; do sleep 2; done
fi

echo "── memastikan bundle dashboard ada"
[ -d "$DIST/assets" ] || { echo "dist kosong — jalankan 'npm run build' di telemarketing-qc-dashboard"; exit 1; }

echo "── menjalankan test"
docker build -q -t qc-e2e/tests:latest tests/ >/dev/null
rm -rf artefak/allure-results && mkdir -p artefak/allure-results
cp tests/environment.properties tests/categories.json artefak/allure-results/ 2>/dev/null || true
set +e
docker run --rm --network qc-e2e-net \
  -v "$PWD/tests:/tests:ro" \
  -v "$TRANSKRIP:/transkrip:ro" \
  -v "$DIST:/dist:ro" \
  -v "$PWD/artefak/allure-results:/allure-results" \
  qc-e2e/tests:latest \
  python -m pytest /tests -v --alluredir=/allure-results -p no:cacheprovider
HASIL=$?
set -e

echo "── merender Allure report"
docker build -q -t qc-e2e/allure:latest allure-cli/ >/dev/null
docker run --rm -v "$PWD/artefak:/work" qc-e2e/allure:latest \
  allure generate /work/allure-results -o /work/allure-report --clean

echo "── report: $PWD/artefak/allure-report/index.html"
exit $HASIL
