"""Shared Firebase Admin SDK / Firestore client initialization."""

from __future__ import annotations

import json

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client

_app: firebase_admin.App | None = None
_client: Client | None = None


def get_firestore_client(
    project_id: str,
    credentials_path: str | None = None,
    credentials_json: str | None = None,
) -> Client:
    """Return a process-wide Firestore client, initializing the Admin SDK once.

    Credentials come from either:
    - ``credentials_path``: filesystem path to a service-account JSON file, or
    - ``credentials_json``: raw service-account JSON content (for hosts where
      uploading a key file is inconvenient).
    """
    global _app, _client
    if _client is not None:
        return _client

    if credentials_json and credentials_json.strip():
        info = json.loads(credentials_json)
        if isinstance(info, dict) and "private_key" in info and isinstance(info["private_key"], str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(info)
    elif credentials_path:
        with open(credentials_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        if isinstance(info, dict) and "private_key" in info and isinstance(info["private_key"], str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(info)
    else:
        raise ValueError(
            "No Firebase credentials provided: set FIREBASE_CREDENTIALS_PATH "
            "or FIREBASE_CREDENTIALS_JSON."
        )

    _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    _client = firestore.client(_app)
    return _client
