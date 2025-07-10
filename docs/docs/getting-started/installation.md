# Installation Guide

This guide walks you through installing Graphite using pip.

## System Requirements

**Prerequisites:**

- Python >=3.10, < 3.13
- pip (Python package installer)

## Installation

Graphite can be installed with a single command using pip:

<!-- ```bash
pip install grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">pip</span> install grafi</code></pre></div>

That's it! Graphite will be installed along with all its dependencies.

## Verification

After installation, verify that Graphite is installed correctly:

<!-- ```bash
# Check if the installation was successful
python -c "import grafi; print('Graphite installed successfully')"
``` -->

<div class="bash"><pre>
<code><span style="color:#959077"># Check if the installation was successful</span>
<span style="color:#FF4689">python</span> -c <span style="color:#2fb170">"import grafi; print('Graphite installed successfully')"</span></code></pre></div>

## Virtual Environment (Recommended)

For better dependency management, it's recommended to install Graphite in a virtual environment:

<!-- ```bash
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
``` -->

<div class="bash"><pre>
<code><span style="color:#959077"># Create a virtual environment</span>
<span style="color:#FF4689">python</span> <span style="color:#AE81FF">-m</span> venv graphite-env

<span style="color:#959077"># Activate the virtual environment</span>
<span style="color:#959077"># On Linux/macOS</span>
<span style="color:#FF4689">source</span> graphite-env/bin/activate
<span style="color:#959077"># On Windows:</span>
graphite-env\Scripts\activate

<span style="color:#959077"># Install Graphite</span>
<span style="color:#FF4689">pip</span> install grafi

<span style="color:#959077"># When done, deactivate the virtual environment</span>
<span style="color:#FF4689">deactivate</span></code></pre></div>

## Upgrading

To upgrade to the latest version of Graphite:

<!-- ```bash
pip install --upgrade grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">pip</span> install <span style="color:#AE81FF">--upgrade</span> grafi</code></pre></div>

## Troubleshooting

### Common Issues

**Permission Errors:**
If you encounter permission errors, try installing with the `--user` flag:

<!-- ```bash
pip install --user grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">pip</span> install <span style="color:#AE81FF">--user</span> grafi</code></pre></div>

**Dependency Conflicts:**
If you have dependency conflicts, consider using a virtual environment or:

<!-- ```bash
pip install --force-reinstall grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">pip</span> install <span style="color:#AE81FF">--force-reinstall</span> grafi</code></pre></div>

**Python Version Issues:**
Ensure you're using a supported Python version:

<!-- ```bash
python --version
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">python</span> <span style="color:#AE81FF">--version</span></code></pre></div>

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

<!-- ```python
import grafi
# Your Graphite code here
``` -->
<div class="bash"><pre>
<code><span style="color:#FF4689">import</span> grafi</span>
<span style="color:#959077"># Your Graphite code here</span></code></pre></div>

Check the project documentation for usage examples and API reference.
