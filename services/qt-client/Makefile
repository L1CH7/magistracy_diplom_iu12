# ==============================================================================
# Makefile for Qt Client Service
# ==============================================================================

# --- Variables ----------------------------------------------------------------
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
PYTHON   := $(VENV_BIN)/python
PIP      := $(VENV_BIN)/pip
PYLUPDATE := $(VENV_BIN)/pylupdate5

# Source Files
UI_SOURCES := $(shell find ui -name "*.py")

TS_FILES := $(shell find translations -name "*.ts")

# --- Targets ------------------------------------------------------------------

.PHONY: all setup install translate compile clean run

# Default target
all: install compile

# 1. Environment Setup
$(VENV_DIR):
	@echo ">>> Creating virtual environment..."
	python3.14 -m venv $(VENV_DIR)

install: $(VENV_DIR)
	@echo ">>> Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ">>> Environment ready."

# 2. Translation Workflow
# NOTE: Run this MANUALLY only when you add new strings to Python code.
update-ts: install
	@echo ">>> Generating/Updating translation files (.ts)..."
	@# Updates .ts files based on UI sources
	$(PYLUPDATE) $(UI_SOURCES) -ts $(TS_FILES)
	@echo "✅ .ts files updated. Now edit them manually."

compile: install
	@echo ">>> Compiling binary translations (.qm)..."
	@# Find lrelease dynamically - it can be deep in site-packages/qt5_applications/...
	$(eval LRELEASE := $(shell find $(VENV_DIR) -type f -name lrelease | head -n 1))
	@if [ -z "$(LRELEASE)" ]; then \
		echo "❌ Error: 'lrelease' not found in $(VENV_DIR)."; \
		find $(VENV_DIR) -name lrelease; \
		exit 1; \
	fi; \
	echo "🔧 Using lrelease at: $(LRELEASE)"; \
	$(LRELEASE) translations/*.ts
	@echo "✅ .qm files compiled successfully."

# 3. Helpers
clean:
	@echo ">>> Cleaning up..."
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f translations/*.qm

run: 
	@echo ">>> Starting Application..."
	$(PYTHON) main.py