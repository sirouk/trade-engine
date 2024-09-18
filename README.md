# trade-engine

## Installation

First, get python ready!

```bash
sudo apt install -y python3.11 python3.11-venv
```

Then clone the repository:

```bash
cd ~/
git clone https://github.com/sirouk/trade-engine
cd ./trade-engine
```

Make a python virtual environment and install the dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install .
```

You should now have all required dependencies from the `pyproject.toml`.

If you need to cleanup and reinstall packages:

```bash
cd ~/trading-engine
deactivate;
rm -rf .venv
```
