"""
App_Test_Agent 项目配置

集中管理所有项目路径配置，消除各模块中的硬编码路径。
参考 injection/config.py 的模式，扩展为覆盖整个 app 模块。

使用方式：
    from app.core.config import config, init_app_paths
    
    # 初始化路径（建议在程序启动时调用一次）
    init_app_paths()
    
    # 使用配置
    gt_dir = config.GT_TEMPLATES_DIR
    scripts_dir = config.SCRIPTS_DIR
"""

import os
import sys
from pathlib import Path
from typing import Optional


class AppConfig:
    """
    App_Test_Agent 项目配置类
    
    集中管理所有项目相关的路径配置，包括：
    - 项目目录结构
    - 数据目录
    - 第三方库路径
    - 环境配置加载
    - sys.path 管理
    """

    def __init__(self):
        """初始化配置，自动检测项目结构"""
        # ========== 基础路径检测 ==========
        # config.py 位于 app/core/config.py
        # app/ 目录
        self._app_dir = Path(__file__).resolve().parent.parent
        # ui_semantic_patch/ 目录
        self._ui_semantic_dir = self._app_dir.parent
        # App_Test_Agent/ 目录（项目根目录）
        self._project_root = self._ui_semantic_dir.parent
        
        # ========== 项目结构路径 ==========
        self.PROJECT_ROOT: Path = self._project_root  # App_Test_Agent/
        self.UI_SEMANTIC_PATH: Path = self._ui_semantic_dir  # ui_semantic_patch/
        self.APP_PATH: Path = self._app_dir  # ui_semantic_patch/app/
        
        # ========== 数据目录 ==========
        self.DATA_DIR: Path = self._project_root / "data"
        
        # GT 模板目录（异常类型参考图）
        self.GT_TEMPLATES_DIR: Path = (
            self._project_root 
            / "data" 
            / "gt-category"
        )
        
        # ========== 脚本目录 ==========
        self.SCRIPTS_DIR: Path = self._ui_semantic_dir / "scripts"
        self.INJECTION_SCRIPTS_DIR: Path = self.SCRIPTS_DIR / "injection"
        
        # run_pipeline.py 脚本路径
        self.PIPELINE_SCRIPT: Path = self.SCRIPTS_DIR / "run_pipeline.py"
        
        # ========== 第三方库路径 ==========
        self.THIRD_PARTY_DIR: Path = self._ui_semantic_dir / "third_party"
        self.OMNIPARSER_PATH: Path = self.THIRD_PARTY_DIR / "OmniParser"
        
        # PaddleOCR 模型路径
        self.PADDLEOCR_MODEL_DIR: Path = (
            self.OMNIPARSER_PATH 
            / "weights" 
            / "ocr" 
            / "paddle"
        )
        
        # ========== app 子模块路径 ==========
        self.INJECTION_DIR: Path = self._app_dir / "injection"
        self.UTILS_DIR: Path = self._app_dir / "utils"
        self.STAGES_DIR: Path = self._app_dir / "stages"
        self.GENERATORS_DIR: Path = self._app_dir / "generators"
        self.RENDERERS_DIR: Path = self._app_dir / "renderers"
        self.CLI_DIR: Path = self._app_dir / "cli"
        self.CORE_DIR: Path = self._app_dir / "core"
        
        # ========== 字体目录 ==========
        self._detect_fonts_dir()
        
        # ========== 环境配置 ==========
        self._env_path: Optional[Path] = self._find_env_file()
        self.VLM_API_URL: str = self._load_vlm_api_url()
        
        # ========== 验证关键路径 ==========
        self._validate_critical_paths()

    def _detect_fonts_dir(self) -> None:
        """检测系统字体目录"""
        if sys.platform == "win32":
            self.FONTS_DIR = Path("C:/Windows/Fonts")
        elif sys.platform == "darwin":
            self.FONTS_DIR = Path("/System/Library/Fonts")
        else:
            self.FONTS_DIR = Path("/usr/share/fonts")
    
    def _find_env_file(self) -> Optional[Path]:
        """
        向上搜索 .env 文件
        
        搜索路径（按优先级）：
        1. PROJECT_ROOT / .env
        2. UI_SEMANTIC_PATH / .env
        3. 祖父目录 / .env (activate/)
        4. 曾祖父目录 / .env (projects/)
        """
        search_paths = [
            self._project_root / ".env",
            self._ui_semantic_dir / ".env",
            self._project_root.parent / ".env",
            self._project_root.parent.parent / ".env",
        ]
        
        for env_path in search_paths:
            if env_path.exists():
                return env_path
        
        return None

    def _load_vlm_api_url(self) -> str:
        """加载 VLM API URL"""
        # 优先从环境变量读取
        if os.environ.get("VLM_API_URL"):
            return os.environ["VLM_API_URL"]
        
        # 其次从 .env 文件读取
        if self._env_path:
            try:
                with open(self._env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            if key.strip() == "VLM_API_URL":
                                return value.strip()
            except Exception:
                pass
        
        # 默认值
        return "https://api.openai-next.com/v1/chat/completions"

    def _validate_critical_paths(self) -> None:
        """验证关键路径是否存在"""
        # 检查 run_pipeline.py
        if not self.PIPELINE_SCRIPT.exists():
            print(
                f"⚠ 警告: run_pipeline.py 不存在: {self.PIPELINE_SCRIPT}",
                file=sys.stderr,
            )
        
        # 检查 GT 模板目录（可选）
        if not self.GT_TEMPLATES_DIR.exists():
            print(
                f"⚠ 警告: GT 模板目录不存在: {self.GT_TEMPLATES_DIR}",
                file=sys.stderr,
            )
    
    def add_to_sys_path(self, include_utils: bool = True) -> None:
        """
        将项目根目录和其他必要目录添加到 sys.path
        
        Args:
            include_utils: 是否添加 utils 目录
        
        建议在程序启动时调用一次。
        """
        project_root_str = str(self._project_root)
        ui_semantic_str = str(self._ui_semantic_dir)
        
        # 避免重复添加
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        
        if ui_semantic_str not in sys.path:
            sys.path.insert(0, ui_semantic_str)
        
        if include_utils:
            utils_dir_str = str(self.UTILS_DIR)
            if utils_dir_str not in sys.path:
                sys.path.insert(0, utils_dir_str)

    def __repr__(self) -> str:
        return (
            f"AppConfig(project_root={self.PROJECT_ROOT}, "
            f"gt_templates={self.GT_TEMPLATES_DIR.name})"
        )


# ========== 全局配置实例 ==========

_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置实例（延迟初始化）"""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def init_app_paths(include_utils: bool = True) -> AppConfig:
    """
    初始化应用路径配置
    
    这是推荐的初始化方式，调用后：
    1. 创建全局配置实例
    2. 将必要目录添加到 sys.path
    3. 验证关键路径
    
    Args:
        include_utils: 是否将 utils 目录添加到 sys.path
    
    Returns:
        AppConfig: 全局配置实例
    
    Example:
        from app.core.config import init_app_paths
        
        config = init_app_paths()
        print(config.GT_TEMPLATES_DIR)
    """
    config = get_config()
    config.add_to_sys_path(include_utils=include_utils)
    return config


def __getattr__(name: str):
    """延迟初始化全局 config 实例"""
    global _config
    if name == "config":
        if _config is None:
            _config = AppConfig()
        return _config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
