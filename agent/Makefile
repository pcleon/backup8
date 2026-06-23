.PHONY: all clean build

all: build

build:
	@echo "Installing requirements..."
	pip install -r requirements.txt
	pip install pyinstaller
	@echo "Building single file binary..."
	pyinstaller --noconfirm --onefile --console --name backup-agent agent_main.py
	@echo "Build complete. Binary is at dist/backup-agent"

clean:
	rm -rf build/ dist/ *.spec
