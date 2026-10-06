# Common tasks. Needs Python 3.12. Run `make help`.
PY := .venv/bin/python
DATA ?= $(or $(DAJS_DATA_DIR),data)

.PHONY: help venv test safety demo all report clean

help:
	@echo "make venv     create .venv and install requirements.txt"
	@echo "make test     run the unit tests (no downloads)"
	@echo "make safety   run the privacy and licence guard"
	@echo "make demo     run the pipeline on the synthetic demo data"
	@echo "make all      full run on real data: build, extract, compare, themes, US check"
	@echo "make report   rebuild report/index.html from results/"

venv:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test:
	$(PY) -m unittest discover -s tests

safety:
	$(PY) tools/public_safety_check.py

demo:
	$(PY) tools/run_demo.py

all:
	sh run_all.sh $(DATA) results

report:
	$(PY) scripts/build_report.py

clean:
	rm -rf out .pytest_cache
