# Installation Guide

This guide walks you through installing Graphite using pip.

## System Requirements

**Prerequisites:**
- Python 3.7+ 
- pip (Python package installer)

## Installation

Graphite can be installed with a single command using pip:

```bash
pip install grafi
```

That's it! Graphite will be installed along with all its dependencies.

## Verification

After installation, verify that Graphite is installed correctly:

```bash
# Check if the installation was successful
python -c "import grafi; print('Graphite installed successfully')"
```

## Virtual Environment (Recommended)

For better dependency management, it's recommended to install Graphite in a virtual environment:

```bash
# Create a virtual environment
python -m venv graphite-env

# Activate the virtual environment
# On Linux/macOS:
source graphite-env/bin/activate
# On Windows:
graphite-env\Scripts\activate

# Install Graphite
pip install grafi

# When done, deactivate the virtual environment
deactivate
```

## Upgrading

To upgrade to the latest version of Graphite:

```bash
pip install --upgrade grafi
```

## Troubleshooting

### Common Issues

**Permission Errors:**
If you encounter permission errors, try installing with the `--user` flag:
```bash
pip install --user grafi
```

**Dependency Conflicts:**
If you have dependency conflicts, consider using a virtual environment or:
```bash
pip install --force-reinstall grafi
```

**Python Version Issues:**
Ensure you're using a supported Python version:
```bash
python --version
```

### Getting Help

If you encounter installation issues:

1. Check the [GitHub repository](https://github.com/binome-dev/graphite) for current documentation
2. Look through [GitHub Issues](https://github.com/binome-dev/graphite/issues) for similar problems
3. Create a new issue with:
   - Your operating system and version
   - Python and pip versions
   - Complete error messages

## Next Steps

Once Graphite is installed, you can start using it in your Python projects:

```python
import grafi
# Your Graphite code here
```

Check the project documentation for usage examples and API reference.