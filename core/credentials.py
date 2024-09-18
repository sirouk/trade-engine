from dataclasses import dataclass

@dataclass
class BittensorCredentials:
    api_key: str
    endpoint: str

@dataclass
class Credentials:
    bittensor_sn8: BittensorCredentials