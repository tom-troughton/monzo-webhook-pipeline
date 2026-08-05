"""Key Vault access shared by local scripts and the deployed Function App.
Uses DefaultAzureCredential, which resolves to the Function App's managed identity
when deployed and to the developer's `az login` session when run locally.
"""
import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


@lru_cache
def _client() -> SecretClient:
    return SecretClient(vault_url=os.environ["KEY_VAULT_URI"], credential=DefaultAzureCredential())


def get_secret(name: str) -> str:
    return _client().get_secret(name).value


def set_secret(name: str, value: str) -> None:
    _client().set_secret(name, value)
