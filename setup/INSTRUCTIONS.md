# Environment setup

## Install the tools

Install VS Code and Git. Check that Git is available:

```sh
git --version
```

Install Python 3.12 or later and uv. On a Mac, install uv with:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell, install uv with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart the terminal, then check:

```sh
python --version
uv --version
git --version
```

## Create the project environment

From the `Retail_Profit_Stack` folder, run:

```sh
uv sync
```

This creates `.venv`, installs the project packages, and writes or updates `uv.lock`.

Copy `.env.example` to `.env` and add your OpenRouter key:

```text
OPENROUTER_API_KEY=your-key-here
MODEL_NAME=openrouter/free
```

Never commit `.env`. It is already listed in `.gitignore`.

## Configure VS Code notebooks

Install the Microsoft **Python** and **Jupyter** extensions. Open a notebook, select **Select Kernel**, choose **Python Environments**, then select `.venv` for this project.

## Run Python commands

Use `uv run` so commands use the project's environment:

```sh
uv run python --version
uv run jupyter --version
```

The initial environment is focused on Python, notebooks, local analytics, and AI experiments. Add web and dashboard tooling when that part of the project begins.
