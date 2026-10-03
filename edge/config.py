import os
import json
from functools import lru_cache
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class Settings(BaseSettings):
    """
    Single source of runtime configuration. Every value can be overridden with an
    environment variable (or a .env file in the project root).
    """
    model_config = SettingsConfigDict(env_file=os.path.join(PROJECT_ROOT, ".env"), extra="ignore")

    node_id: str = Field("edge_device_alpha", alias="LIFELINE_NODE_ID")
    data_dir: str = Field(os.path.join(PROJECT_ROOT, "data"), alias="LIFELINE_DATA_DIR")
    # Where mutable runtime state (profile, incidents, sync log, media) lives.
    runtime_dir: Optional[str] = Field(None, alias="LIFELINE_RUNTIME_DIR")
    # Qdrant Edge shard directory.
    storage_path: Optional[str] = Field(None, alias="QDRANT_STORAGE_PATH")
    # Ephemeral storage (temp dir, wiped on exit). Used by tests.
    memory_mode: bool = Field(False, alias="QDRANT_MEMORY_MODE")
    # FastEmbed model cache. Kept inside the data dir so the model survives reboots
    # and the device keeps working offline (the FastEmbed default is the OS temp dir).
    model_cache_dir: Optional[str] = Field(None, alias="FASTEMBED_CACHE_PATH")

    # Optional local LLM. It may only rephrase the summary line, never the steps.
    ollama_url: str = Field("http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field("llama3.2:1b", alias="OLLAMA_MODEL")
    enable_llm_summary: bool = Field(False, alias="LIFELINE_ENABLE_LLM_SUMMARY")

    # Upstream hub for edge-to-server sync (another Lifeline API).
    server_url: Optional[str] = Field(None, alias="LIFELINE_SERVER_URL")
    server_api_key: Optional[str] = Field(None, alias="LIFELINE_SERVER_API_KEY")

    # Security
    api_key: Optional[str] = Field(None, alias="LIFELINE_API_KEY")
    admin_key: Optional[str] = Field(None, alias="LIFELINE_ADMIN_KEY")
    cors_origins: str = Field("http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
                              alias="LIFELINE_CORS_ORIGINS")
    max_upload_mb: int = Field(15, alias="LIFELINE_MAX_UPLOAD_MB")

    cloudinary_cloud_name: Optional[str] = Field(None, alias="CLOUDINARY_CLOUD_NAME")
    cloudinary_api_key: Optional[str] = Field(None, alias="CLOUDINARY_API_KEY")
    cloudinary_api_secret: Optional[str] = Field(None, alias="CLOUDINARY_API_SECRET")

    @property
    def runtime_path(self) -> str:
        return self.runtime_dir or os.path.join(self.data_dir, "runtime")

    @property
    def shard_path(self) -> str:
        return self.storage_path or os.path.join(self.data_dir, "edge_shards")

    @property
    def models_path(self) -> str:
        return self.model_cache_dir or os.path.join(self.data_dir, "models")

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_retrieval_config() -> dict:
    """
    Calibrated retrieval/gating constants shared by the backend and the mobile
    knowledge pack (data/retrieval_config.json). See tests/eval for the evaluation
    set these numbers were calibrated against.
    """
    path = os.path.join(PROJECT_ROOT, "data", "retrieval_config.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
