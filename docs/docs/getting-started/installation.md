# Installation Guide

This guide walks you through installing Graphite using uv.

## System Requirements

**Prerequisites:**

- Python >=3.11
- [uv](https://docs.astral.sh/uv/#installation)

## Installation

Graphite can be installed with a single command using uv:

<!-- ```bash
uv add grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> add grafi</code></pre></div>

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
uv venv

# Activate the virtual environment
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
graphite-env\Scripts\activate

# Install Graphite
uv add grafi

# When done, deactivate the virtual environment
deactivate
``` -->

<div class="bash"><pre>
<code><span style="color:#959077"># Create a virtual environment</span>
<span style="color:#FF4689">uv</span> venv

<span style="color:#959077"># Activate the virtual environment</span>
<span style="color:#959077"># On Linux/macOS</span>
<span style="color:#FF4689">source</span> .venv/bin/activate
<span style="color:#959077"># On Windows:</span>
.venv\Scripts\activate

<span style="color:#959077"># Install Graphite</span>
<span style="color:#FF4689">uv </span> add grafi

<span style="color:#959077"># When done, deactivate the virtual environment</span>
<span style="color:#FF4689">deactivate</span></code></pre></div>

## Upgrading

To upgrade to the latest version of Graphite:

<!-- ```bash
uv add --upgrade grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> add <span style="color:#AE81FF">--upgrade</span> grafi</code></pre></div>

## Troubleshooting

### Common Issues


**Dependency Conflicts:**
If you have dependency conflicts, consider using a virtual environment or:

<!-- ```bash
uv add --force-reinstall grafi
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> add <span style="color:#AE81FF">--force-reinstall</span> grafi</code></pre></div>

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
   - Python and uv versions
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
