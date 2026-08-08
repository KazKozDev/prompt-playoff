.PHONY: install install-all test lint format validate serve demo benchmark optimize promptfoo papers

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
	prompt-selector validate-registry --strict

serve:
	prompt-selector serve

demo:
	prompt-selector recommend "Extract entities into strict JSON using a local model" --model qwen3:14b --capabilities structured_output,system_messages

benchmark:
	prompt-selector benchmark --model llama3.2:3b --model-class small --dataset entity-extraction --repeats 3

optimize:
	prompt-selector optimize --model llama3.2:3b --model-class small --dataset entity-extraction --technique structured.schema-first

promptfoo:
	prompt-selector export-promptfoo --techniques structured.schema-first,direct.explicit-constraints --models llama3.2:3b --model-class small --dataset entity-extraction --output promptfoo

papers:
	bash scripts/fetch_papers.sh
