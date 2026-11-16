PYTHON ?= test_env/bin/python

.PHONY: build clean

# Remove build artifacts (wheel/sdist, temp build dir, package metadata)
clean:
	rm -rf build dist src/*.egg-info

# Clean, then produce a fresh production wheel + sdist in dist/
build: clean
	$(PYTHON) -m build
