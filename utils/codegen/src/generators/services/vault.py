import importlib

from typing import Dict, Any, Optional

from pydantic import BaseModel

from generators.services.base import BaseGenerator


class VaultGenerator(BaseGenerator):        
    def generate(self) -> None:
        if not self.svc.vault or not self.svc.vault.enabled:
            return

        self._generate_init__vault_agent()
        self._generate_agent_config()

    def _generate_init__vault_agent(self) -> None:
        vault_vars = self._get_vault_vars()
        
        self.write(
            f"scripts/init-vault.sh",
            self.render(
                "services/vault/init-vault.sh.j2",
                vault_vars=vault_vars,
            )
        )
    
    def _generate_agent_config(self) -> None:
        vault_vars = self._get_vault_vars()
        static_vars = self._get_static_vars()
        
        self.write(
            f"vault/agent-{self.svc.name}.local.hcl",
            self.render(
                "services/vault/agent-config.hcl.j2",
                vault_vars=vault_vars,
                static_vars=static_vars,
                vault={
                    "addr": "localhost",
                    "port": 8200
                }
            )
        )

        self.write(
            f"vault/agent-{self.svc.name}.docker.hcl",
            self.render(
                "services/vault/agent-config.hcl.j2",
                vault_vars=vault_vars,
                static_vars=static_vars,
                vault={
                    "addr": "vault",
                    "port": 8200
                }
            )
        )

    def _import_settings(self) -> Optional[Any]:
        try:
            settings_module = importlib.import_module("generated.settings")
            return settings_module
        except ImportError as e:
            print(f"Warning: Could not import generated.settings: {e}")
            return None
        
    def _get_settings(self) -> BaseModel:
        settings_module = self._import_settings()
        
        if settings_module is None or not hasattr(settings_module, "get_settings"):
            raise ValueError("Could not import settings")
        
        return settings_module.get_settings()

    def _load_settings_vars(self, settings: BaseModel, env_prefix: str = "") -> Dict[str, Any]:
        try:
            vars_dict = {}
            
            for field_name in settings.__class__.model_fields.keys():
                value = getattr(settings, field_name)
                
                if hasattr(value, "model_fields"):
                    sub_prefix = ""
                    if hasattr(value, "model_config") and "env_prefix" in value.model_config:
                        sub_prefix = value.model_config["env_prefix"] or ""

                    vars_dict.update(self._load_settings_vars(value, sub_prefix))
                else:
                    env_name = field_name.upper()
                    vars_dict[env_prefix + env_name] = value
            
            return vars_dict
            
        except Exception as e:
            print(f"Warning: Could not load settings: {e}")
            return {}
    
    def _get_vault_vars(self) -> Dict[str, Any]:
        settings_vars = self._load_settings_vars(self._get_settings())
        vault_vars = {}

        for var_name in (self.svc.vault.vars or []):
            if var_name in settings_vars:
                vault_vars[var_name] = settings_vars[var_name]
            else:
                vault_vars[var_name] = ""

        return vault_vars
    
    def _get_static_vars(self) -> Dict[str, Any]:
        vault_var_names = set(self.svc.vault.vars or [])
        return {
            name: value 
            for name, value in self._load_settings_vars(self._get_settings()).items()
            if name not in vault_var_names
        }