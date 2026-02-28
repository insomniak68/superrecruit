"""Configurable LLM provider registry and router.

Supports Anthropic and OpenAI-compatible providers (OpenAI, Azure, Ollama, vLLM, local).
Config loaded from config/llm.yaml with env var overrides and backward-compatible fallback.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# ── Data classes ──

@dataclass
class ProviderConfig:
    name: str
    type: str  # "anthropic" or "openai_compatible"
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""


@dataclass
class RoleConfig:
    provider: str
    model: str = ""
    fallback: list[str] = field(default_factory=list)  # fallback provider names


@dataclass
class LLMConfig:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    roles: dict[str, RoleConfig] = field(default_factory=dict)
    default_provider: str = ""
    default_model: str = ""


# ── Unified client ──

class LLMClient:
    """Unified LLM client with .complete() that works across providers."""

    def __init__(self, provider: ProviderConfig, model: str):
        self.provider = provider
        self.model = model

    def complete(self, messages: list[dict], max_tokens: int = 4096, system: str | None = None) -> str:
        if self.provider.type == "anthropic":
            return self._complete_anthropic(messages, max_tokens, system)
        else:
            return self._complete_openai(messages, max_tokens, system)

    def _complete_anthropic(self, messages: list[dict], max_tokens: int, system: str | None) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.provider.api_key)
        kwargs = dict(model=self.model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return response.content[0].text

    def _complete_openai(self, messages: list[dict], max_tokens: int, system: str | None) -> str:
        base_url = self.provider.base_url.rstrip("/")
        url = f"{base_url}/v1/chat/completions"
        # If base_url already ends with /v1, don't double it
        if base_url.endswith("/v1"):
            url = f"{base_url}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.provider.api_key:
            headers["Authorization"] = f"Bearer {self.provider.api_key}"

        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": all_messages,
        }

        resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def __repr__(self) -> str:
        return f"LLMClient(provider={self.provider.name!r}, model={self.model!r})"


# ── Config loading ──

_config: Optional[LLMConfig] = None

ROLES = ["skill_extraction", "workspace_chat", "bulk_processing", "confidence_reasoning"]


def _find_config_path() -> Optional[Path]:
    """Look for config/llm.yaml relative to project root."""
    # Try relative to this file's parent (src/) -> project root
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / "config" / "llm.yaml",
        Path("config/llm.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_from_yaml(path: Path) -> LLMConfig:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    config = LLMConfig()
    config.default_provider = raw.get("default_provider", "")
    config.default_model = raw.get("default_model", "")

    for name, pdata in raw.get("providers", {}).items():
        api_key = pdata.get("api_key", "")
        # Support env var references like ${ANTHROPIC_API_KEY}
        if api_key.startswith("${") and api_key.endswith("}"):
            env_name = api_key[2:-1]
            api_key = os.environ.get(env_name, "")
        config.providers[name] = ProviderConfig(
            name=name,
            type=pdata.get("type", "openai_compatible"),
            api_key=api_key,
            base_url=pdata.get("base_url", ""),
            default_model=pdata.get("default_model", ""),
        )

    for role_name, rdata in raw.get("roles", {}).items():
        if isinstance(rdata, str):
            config.roles[role_name] = RoleConfig(provider=rdata)
        else:
            config.roles[role_name] = RoleConfig(
                provider=rdata.get("provider", ""),
                model=rdata.get("model", ""),
                fallback=rdata.get("fallback", []),
            )

    return config


def _load_from_env() -> LLMConfig:
    """Backward-compatible: build config from env vars only."""
    config = LLMConfig()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    if api_key:
        config.providers["anthropic"] = ProviderConfig(
            name="anthropic",
            type="anthropic",
            api_key=api_key,
            default_model=model,
        )
        config.default_provider = "anthropic"
        config.default_model = model

    return config


def _apply_env_overrides(config: LLMConfig) -> None:
    """Apply SR_LLM_* env var overrides."""
    if v := os.environ.get("SR_LLM_DEFAULT_PROVIDER"):
        config.default_provider = v
    if v := os.environ.get("SR_LLM_DEFAULT_MODEL"):
        config.default_model = v

    # Per-role model overrides: SR_LLM_SKILL_EXTRACTION_MODEL, etc.
    for role in ROLES:
        env_key = f"SR_LLM_{role.upper()}_MODEL"
        if v := os.environ.get(env_key):
            if role in config.roles:
                config.roles[role].model = v
            else:
                config.roles[role] = RoleConfig(
                    provider=config.default_provider, model=v
                )

        env_key = f"SR_LLM_{role.upper()}_PROVIDER"
        if v := os.environ.get(env_key):
            if role in config.roles:
                config.roles[role].provider = v
            else:
                config.roles[role] = RoleConfig(provider=v)


def load_config(force: bool = False) -> LLMConfig:
    """Load and cache LLM config."""
    global _config
    if _config is not None and not force:
        return _config

    path = _find_config_path()
    if path:
        logger.info(f"Loading LLM config from {path}")
        _config = _load_from_yaml(path)
    else:
        logger.info("No config/llm.yaml found, falling back to env vars")
        _config = _load_from_env()

    _apply_env_overrides(_config)

    # Log resolved config
    for role in ROLES:
        client = _resolve_client_for_role(role, _config)
        if client:
            logger.info(f"LLM role '{role}' → {client.provider.name}/{client.model}")

    return _config


def _resolve_client_for_role(role: str, config: LLMConfig) -> Optional[LLMClient]:
    """Resolve a client for a role without fallback attempts."""
    role_cfg = config.roles.get(role)
    provider_name = (role_cfg.provider if role_cfg else None) or config.default_provider
    if not provider_name or provider_name not in config.providers:
        return None

    provider = config.providers[provider_name]
    model = (role_cfg.model if role_cfg else None) or config.default_model or provider.default_model
    if not model:
        return None

    return LLMClient(provider=provider, model=model)


def get_client(role: str) -> LLMClient:
    """Get a unified LLM client for a given role, with fallback chain support.

    Usage:
        client = get_client("skill_extraction")
        result = client.complete(messages=[{"role": "user", "content": "..."}], max_tokens=4096)
    """
    config = load_config()
    role_cfg = config.roles.get(role)

    # Build provider chain: primary + fallbacks
    chain = []
    primary = (role_cfg.provider if role_cfg else None) or config.default_provider
    if primary:
        chain.append(primary)
    if role_cfg and role_cfg.fallback:
        chain.extend(role_cfg.fallback)

    if not chain:
        raise ValueError(
            f"No LLM provider configured for role '{role}'. "
            "Set ANTHROPIC_API_KEY or create config/llm.yaml"
        )

    # Try to find a valid provider
    for provider_name in chain:
        if provider_name not in config.providers:
            logger.warning(f"Provider '{provider_name}' not found in config, skipping")
            continue
        provider = config.providers[provider_name]
        model = (role_cfg.model if role_cfg else None) or config.default_model or provider.default_model
        if not model:
            logger.warning(f"No model for provider '{provider_name}', skipping")
            continue
        return _FallbackLLMClient(
            primary=LLMClient(provider=provider, model=model),
            fallback_chain=chain,
            role=role,
            config=config,
            role_cfg=role_cfg,
        )

    raise ValueError(f"No valid provider found for role '{role}' (tried: {chain})")


class _FallbackLLMClient(LLMClient):
    """LLM client wrapper that tries fallback providers on failure."""

    def __init__(self, primary: LLMClient, fallback_chain: list[str],
                 role: str, config: LLMConfig, role_cfg: Optional[RoleConfig]):
        self.provider = primary.provider
        self.model = primary.model
        self._primary = primary
        self._fallback_chain = fallback_chain
        self._role = role
        self._config = config
        self._role_cfg = role_cfg

    def complete(self, messages: list[dict], max_tokens: int = 4096, system: str | None = None) -> str:
        errors = []
        for provider_name in self._fallback_chain:
            if provider_name not in self._config.providers:
                continue
            provider = self._config.providers[provider_name]
            model = (
                (self._role_cfg.model if self._role_cfg else None)
                or self._config.default_model
                or provider.default_model
            )
            if not model:
                continue
            client = LLMClient(provider=provider, model=model)
            try:
                result = client.complete(messages, max_tokens, system)
                if provider_name != self._fallback_chain[0]:
                    logger.warning(
                        f"Role '{self._role}': primary failed, succeeded with fallback '{provider_name}'"
                    )
                return result
            except Exception as e:
                errors.append((provider_name, e))
                logger.warning(f"Provider '{provider_name}' failed for role '{self._role}': {e}")

        raise RuntimeError(
            f"All providers failed for role '{self._role}': "
            + "; ".join(f"{n}: {e}" for n, e in errors)
        )
