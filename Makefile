.PHONY: install install-all test lint format validate audit audit-links build-release serve demo benchmark optimize promptfoo papers

install:
	python3 -m pip install -e '.[dev]'

install-all:
	python3 -m pip install -e '.[dev,dspy,tracing]'

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

validate:
	prompt-playoff validate-registry --strict

audit:
	python3 scripts/audit_publication.py

audit-links:
	python3 scripts/audit_publication.py --check-links

build-release:
	python3 -m build
	python3 scripts/audit_publication.py --artifact "$$(find dist -maxdepth 1 -name '*.whl' -print -quit)"

serve:
	prompt-playoff serve

demo:
	prompt-playoff recommend "Extract entities into strict JSON using a local model" --model qwen3:14b --capabilities structured_output,system_messages

benchmark:
	prompt-playoff benchmark --model llama3.2:3b --model-class small --dataset entity-extraction --repeats 3

optimize:
	prompt-playoff optimize --model llama3.2:3b --model-class small --dataset entity-extraction --technique structured.schema-first

promptfoo:
	prompt-playoff export-promptfoo --techniques structured.schema-first,direct.explicit-constraints --models llama3.2:3b --model-class small --dataset entity-extraction --output promptfoo

papers:
	bash scripts/fetch_papers.sh
