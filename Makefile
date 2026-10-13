# Replication package for "Spec-Driven Development as Prescribed and as Practiced"
#
#   make data     unpack the dataset and build what is derived from it
#   make figures  redraw every figure the paper includes
#   make verify   recompute every manuscript claim and diff against the paper
#   make all      both
#
# Only `make dataset-from-mysql` needs the original MySQL server; nothing else
# does, and a replicator never has to run it.

PY ?= python3
DATA := data/specmine-sample.sqlite
HEADINGS := data/build/headings_all.csv
TIMELINE := data/build/timeline_census.json

.PHONY: all data figures verify clean dataset-from-mysql

all: data figures verify

data: $(HEADINGS) $(TIMELINE)

$(DATA): $(DATA).xz
	xz -dkf $(DATA).xz

# 155 MB of parsed headings. Built rather than shipped: three analyses and two
# figures read it, and it is derived entirely from the packaged database.
$(HEADINGS): $(DATA) analysis/extract_headings.py analysis/sample.py
	@mkdir -p data/build
	$(PY) analysis/extract_headings.py --kiro --out $(HEADINGS)

# Adoption series for the two timeline figures. No script for these existed
# while the paper was written; the series were built by hand.
$(TIMELINE): $(DATA) analysis/build_timeline.py analysis/sample.py
	@mkdir -p data/build
	$(PY) analysis/build_timeline.py --out data/build

# Writes into figures/out/ under the names the paper includes, so the output
# can be copied straight into the paper's figures/ directory.
figures: $(HEADINGS) $(TIMELINE)
	@for f in figures/fig_*.py; do echo "  $$f"; $(PY) $$f >/dev/null || exit 1; done
	@ls figures/out/*.pdf | sed 's/^/  wrote /'

verify: $(HEADINGS)
	$(PY) verify/claims.py

clean:
	rm -rf data/build $(DATA)

# Regenerates data/specmine-sample.sqlite from the original MySQL corpus.
# Needs credentials in a .env file; see build_dataset.py.
dataset-from-mysql:
	$(PY) build_dataset.py --out $(DATA)
	xz -9 -T0 -f -k $(DATA)
