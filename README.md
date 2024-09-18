# trade-engine

### Installation

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
pip install -e .
```

You should now have all required dependencies from the `pyproject.toml`.

If you need to cleanup and reinstall packages:

```bash
cd ~/trading-engine
deactivate;
rm -rf .venv
```

## Adding Credentials

Before running the trade engine, you will need to provide your credentials for Bittensor or any other services. The credentials are stored in a JSON file (`signal_processors/credentials.json`).

To set up the credentials, run the following command, which will prompt you to enter your API key(s):

```bash
python3 signal_processors/credentials.py
```

You will be prompted to enter the required API key for Bittensor SN8:

```bash
Enter your API key for Bittensor SN8: <your-api-key>
```

Once you provide the necessary credentials, they will be saved in `signal_processors/credentials.json`.

If you need to update the credentials later, simply rerun the same command and re-enter the credentials as needed.
