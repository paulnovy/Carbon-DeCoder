.PHONY: fmt lint up down logs test api-shell local-pipeline-smoke local-pipeline-smoke-live local-pipeline-smoke-strict browser-cdp-smoke real-wgs-validation-gate vendor-validation-e2e-dry vendor-validation-e2e-live vendor-validation-api-from-fastq-live deploy-remote deploy-remote-build remote-logs remote-down remote-status

REMOTE_HOST ?= remote
REMOTE_DIR ?= /opt/wgs-cockpit

fmt:
	@echo "No auto-formatter is configured yet; run targeted formatters manually when introduced."

lint:
	git diff --check
	python3 -m compileall apps/api/app scripts pipelines/nextflow/scripts
	find scripts pipelines/nextflow/scripts -name '*.sh' -print0 | xargs -0 -r bash -n

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	./scripts/run_tests.sh

api-shell:
	docker compose exec api /bin/sh

local-pipeline-smoke:
	OUTDIR="$${OUTDIR:-results/local-pipeline-smoke}" RUN_ID="$${RUN_ID:-run_local_smoke}" STRICT=false ./scripts/run_local_pipeline_smoke.sh

local-pipeline-smoke-live:
	OUTDIR="$${OUTDIR:-results/local-pipeline-smoke-live}" RUN_ID="$${RUN_ID:-run_local_smoke_live}" STRICT=false LIVE_API=true API_BASE_URL="$${API_BASE_URL:-http://localhost:8000}" ./scripts/run_local_pipeline_smoke.sh

local-pipeline-smoke-strict:
	OUTDIR="$${OUTDIR:-results/local-pipeline-smoke-strict}" RUN_ID="$${RUN_ID:-run_local_smoke_strict}" STRICT=true ./scripts/run_local_pipeline_smoke.sh

browser-cdp-smoke:
	python3 scripts/browser_cdp_smoke.py --frontend "$${FRONTEND_URL:-http://localhost:3000}"

real-wgs-validation-gate:
	@test -n "$(RUN_ID)" || (echo "Missing RUN_ID=run_x" && exit 1)
	python3 scripts/real_wgs_validation_gate.py \
		--api "$${API_BASE_URL:-http://localhost:8000}" \
		$$(if [ -n "$${FRONTEND_URL:-}" ]; then echo --frontend "$${FRONTEND_URL}"; fi) \
		--run-id "$(RUN_ID)" \
		$$(if [ "$${REQUIRE_WORKER_QUEUE:-false}" = "true" ]; then echo --require-worker-queue; fi) \
		--out "$${OUT:-results/real-wgs-validation-$$(date +%Y%m%d-%H%M%S).json}"

vendor-validation-e2e-dry:
	@test -n "$(VENDOR)" || (echo "Missing VENDOR=/path/to/vendor.fa" && exit 1)
	@test -n "$(PIPELINE)" || (echo "Missing PIPELINE=/path/to/pipeline.fa" && exit 1)
	@test -n "$(RUN_ID)" || (echo "Missing RUN_ID=run_x" && exit 1)
	@test -n "$(OUTDIR)" || (echo "Missing OUTDIR=./results/vendor-e2e" && exit 1)
	python3 pipelines/nextflow/scripts/vendor_validation_e2e.py \
		--vendor "$(VENDOR)" \
		--pipeline "$(PIPELINE)" \
		--run-id "$(RUN_ID)" \
		--api-base-url "$${API_BASE_URL:-http://api:8000}" \
		--method "$${METHOD:-proxy}" \
		--kmer-size "$${KMER_SIZE:-21}" \
		--pass-threshold "$${PASS_THRESHOLD:-0.98}" \
		--outdir "$(OUTDIR)" \
		--dry-run

vendor-validation-e2e-live:
	@test -n "$(VENDOR)" || (echo "Missing VENDOR=/path/to/vendor.fa" && exit 1)
	@if [ -z "$(PIPELINE)" ] && { [ -z "$(R1)" ] || [ -z "$(R2)" ]; }; then \
		echo "Provide PIPELINE=/path/to/pipeline.fa OR both R1=/path/to/R1.fastq.gz R2=/path/to/R2.fastq.gz"; \
		exit 1; \
	fi
	@test -n "$(OUTDIR)" || (echo "Missing OUTDIR=./results/vendor-e2e-live" && exit 1)
	python3 pipelines/nextflow/scripts/vendor_validation_live_e2e.py \
		--api-base-url "$${API_BASE_URL:-http://localhost:8000}" \
		--vendor "$(VENDOR)" \
		$$(if [ -n "$(PIPELINE)" ]; then echo --pipeline "$(PIPELINE)"; else echo --r1 "$(R1)" --r2 "$(R2)"; fi) \
		--project-name "$${PROJECT_NAME:-Vendor Validation Live E2E}" \
		--sample-id "$${SAMPLE_ID:-S_vendor_e2e_live}" \
		--reference-id "$${REFERENCE_ID:-GRCh38_standard}" \
		--method "$${METHOD:-proxy}" \
		--kmer-size "$${KMER_SIZE:-21}" \
		--pass-threshold "$${PASS_THRESHOLD:-0.98}" \
		--outdir "$(OUTDIR)"

vendor-validation-api-from-fastq-live:
	@test -n "$(VENDOR)" || (echo "Missing VENDOR=/path/to/vendor.fa" && exit 1)
	@test -n "$(R1)" || (echo "Missing R1=/path/to/R1.fastq.gz" && exit 1)
	@test -n "$(R2)" || (echo "Missing R2=/path/to/R2.fastq.gz" && exit 1)
	@test -n "$(OUTDIR)" || (echo "Missing OUTDIR=./results/vendor-api-fastq-live" && exit 1)
	python3 pipelines/nextflow/scripts/vendor_validation_api_from_fastq_e2e.py \
		--api-base-url "$${API_BASE_URL:-http://localhost:8000}" \
		--vendor "$(VENDOR)" \
		--r1 "$(R1)" \
		--r2 "$(R2)" \
		--project-name "$${PROJECT_NAME:-Vendor Validation API FASTQ E2E}" \
		--sample-id "$${SAMPLE_ID:-S_vendor_api_fastq_e2e}" \
		--reference-id "$${REFERENCE_ID:-GRCh38_standard}" \
		--method "$${METHOD:-proxy}" \
		--kmer-size "$${KMER_SIZE:-21}" \
		--pass-threshold "$${PASS_THRESHOLD:-0.98}" \
		--max-reads "$${MAX_READS:-2000}" \
		--outdir "$(OUTDIR)"

deploy-remote:
	./scripts/deploy-remote.sh

deploy-remote-build:
	./scripts/deploy-remote.sh --build

remote-logs:
	ssh "$(REMOTE_HOST)" 'cd "$(REMOTE_DIR)" && docker compose logs -f --tail=50'

remote-down:
	ssh "$(REMOTE_HOST)" 'cd "$(REMOTE_DIR)" && docker compose down'

remote-status:
	ssh "$(REMOTE_HOST)" 'cd "$(REMOTE_DIR)" && docker compose ps'
