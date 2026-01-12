"""
配置加载模块

负责加载API配置和测试场景,支持环境变量替换
"""

import json
import os
import re
from typing import Dict, List, Any


class ConfigError(Exception):
    """配置错误异常"""
    pass


def resolve_env_vars(value: Any) -> Any:
    """
    递归解析配置中的环境变量

    Args:
        value: 配置值(可能是字符串、字典、列表等)

    Returns:
        解析后的值
    """
    if isinstance(value, str):
        # 匹配 ${VAR_NAME} 格式
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, value)
        for var_name in matches:
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ConfigError(f"Environment variable '{var_name}' not set")
            value = value.replace(f"${{{var_name}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_env_vars(item) for item in value]
    else:
        return value


def load_api_config(config_path: str = "config/api_config.json") -> Dict[str, Any]:
    """
    加载API配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        解析后的配置字典

    Raises:
        ConfigError: 配置文件不存在或格式错误
    """
    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config file: {e}")

    # 解析环境变量
    try:
        config = resolve_env_vars(config)
    except ConfigError as e:
        # 如果环境变量未设置,给出友好提示
        raise ConfigError(
            f"{e}\n"
            f"Please set the environment variable or create a .env file.\n"
            f"Example: export {e.args[0].split(\"'\")[1]}='your_api_key'"
        )

    # 验证必填字段
    validate_api_config(config)

    return config


def validate_api_config(config: Dict[str, Any]) -> None:
    """
    验证API配置的完整性

    Args:
        config: 配置字典

    Raises:
        ConfigError: 配置缺少必填字段
    """
    # 验证顶层字段
    required_fields = ["active_provider", "providers"]
    for field in required_fields:
        if field not in config:
            raise ConfigError(f"Missing required field in config: {field}")

    # 验证active_provider存在
    active = config["active_provider"]
    if active not in config["providers"]:
        raise ConfigError(f"Active provider '{active}' not found in providers")

    # 验证每个provider配置
    for provider_name, provider_config in config["providers"].items():
        required_provider_fields = ["api_key", "api_url", "model"]
        for field in required_provider_fields:
            if field not in provider_config:
                raise ConfigError(
                    f"Missing required field '{field}' in provider '{provider_name}'"
                )


def load_test_scenarios(scenarios_path: str = "config/test_scenarios.json") -> List[Dict[str, Any]]:
    """
    加载测试场景配置

    Args:
        scenarios_path: 场景配置文件路径

    Returns:
        场景列表

    Raises:
        ConfigError: 配置文件不存在或格式错误
    """
    if not os.path.exists(scenarios_path):
        raise ConfigError(f"Scenarios file not found: {scenarios_path}")

    try:
        with open(scenarios_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in scenarios file: {e}")

    if "scenarios" not in data:
        raise ConfigError("Missing 'scenarios' field in scenarios file")

    scenarios = data["scenarios"]

    # 验证每个场景的必填字段
    for i, scenario in enumerate(scenarios):
        required_fields = ["id", "prompt"]
        for field in required_fields:
            if field not in scenario:
                raise ConfigError(
                    f"Missing required field '{field}' in scenario {i}"
                )

    return scenarios


def get_provider_config(config: Dict[str, Any], provider_name: str = None) -> Dict[str, Any]:
    """
    获取指定provider的配置

    Args:
        config: 完整配置字典
        provider_name: provider名称(可选,默认使用active_provider)

    Returns:
        provider配置字典

    Raises:
        ConfigError: provider不存在
    """
    if provider_name is None:
        provider_name = config["active_provider"]

    if provider_name not in config["providers"]:
        available = ", ".join(config["providers"].keys())
        raise ConfigError(
            f"Provider '{provider_name}' not found. "
            f"Available providers: {available}"
        )

    return config["providers"][provider_name]
