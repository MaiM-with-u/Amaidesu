import asyncio

# import logging # 移除标准logging导入
import tomllib
import os
import time
import base64
from io import BytesIO
from typing import Any, Dict, Optional
from dataclasses import dataclass

# 导入全局logger - 在确认不再需要后移除
# from src.utils.logger import logger # 将在确认后移除

# --- 依赖检查 ---
try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    # 导入 openai 库
    import openai
    from openai import AsyncOpenAI  # 明确导入 AsyncOpenAI
except ImportError:
    openai = None
    AsyncOpenAI = None  # type: ignore

try:
    from PIL import Image
except ImportError:
    Image = None

from src.core.plugin_manager import BasePlugin
from src.core.amaidesu_core import AmaidesuCore
from maim_message import MessageBase, UserInfo, BaseMessageInfo, GroupInfo, FormatInfo, Seg, TemplateInfo
from src.utils.logger import get_logger


@dataclass
class ScreenMessage:
    """屏幕描述消息类"""
    
    description: str
    timestamp: int
    raw_data: Dict[str, Any]
    
    def __post_init__(self):
        """初始化后设置logger"""
        self.logger = get_logger(self.__class__.__name__)
    
    def _create_user_info(self, core, config: Dict[str, Any]) -> UserInfo:
        """创建用户信息对象"""
        return UserInfo(
            platform=core.platform,
            user_id=config.get("user_id", "screen_monitor"),
            user_nickname=config.get("user_nickname", "屏幕监控"),
            user_cardname=config.get("user_cardname", "Screen Monitor"),
        )
    
    def _generate_message_id(self) -> str:
        """生成消息ID"""
        return f"screen_{self.timestamp}_{hash(self.description) % 10000}"
    
    async def _create_base_message_info(
        self,
        core,
        config: Dict[str, Any],
        context_tags: Optional[list] = None,
        template_items: Optional[Dict[str, Any]] = None,
    ) -> BaseMessageInfo:
        """创建基础消息信息对象"""

        user_info = self._create_user_info(core, config)
        message_id = self._generate_message_id()
        monitor_id = "screen_monitor"  # 相当于bili的room_id

        # 群组信息（可选）
        group_info = None
        if config.get("enable_group_info", False):
            group_info = GroupInfo(
                platform=core.platform,
                group_id=config.get("group_id", str(monitor_id)),
                group_name=config.get("group_name", f"screen_{monitor_id}"),
            )

        # 格式信息
        format_info = FormatInfo(
            content_format=config.get("content_format", config.get("accept_format", ["text"])),
            accept_format=config.get("accept_format", config.get("content_format", ["text"])),
        )

        # 附加配置
        additional_config = config.get("additional_config", {}).copy()

        # 模板信息（可选）
        template_info = await self._create_template_info(core, config, context_tags, template_items, monitor_id)

        return BaseMessageInfo(
            platform=core.platform,
            message_id=message_id,
            time=self.timestamp,
            user_info=user_info,
            group_info=group_info,
            template_info=template_info,
            format_info=format_info,
            additional_config=additional_config,
        )
    
    async def _create_template_info(
        self,
        core,
        config: Dict[str, Any],
        context_tags: Optional[list] = None,
        template_items: Optional[Dict[str, Any]] = None,
        monitor_id: str = "",
    ) -> Optional[TemplateInfo]:
        """创建模板信息对象"""
        if not config.get("enable_template_info", False) or not template_items:
            return None

        # 获取并追加 Prompt 上下文
        modified_template_items = template_items.copy()

        if prompt_ctx_service := core.get_service("prompt_context"):
            try:
                additional_context = await prompt_ctx_service.get_formatted_context(tags=context_tags)
                if additional_context:
                    # 修改主 Prompt
                    main_prompt_key = "reasoning_prompt_main"
                    if main_prompt_key in modified_template_items:
                        original_prompt = modified_template_items[main_prompt_key]
                        modified_template_items[main_prompt_key] = original_prompt + "\n" + additional_context
            except Exception as e:
                self.logger.error(f"创建模板信息时发生错误: {e}", exc_info=True)

        return TemplateInfo(
            template_items=modified_template_items,
            template_name=config.get("template_name", f"screen_monitor_{monitor_id}"),
            template_default=False,
        )
    
    async def to_message_base(
        self,
        core,
        config: Dict[str, Any],
        context_tags: Optional[list] = None,
        template_items: Optional[Dict[str, Any]] = None,
    ) -> MessageBase:
        """构建MessageBase对象"""
        
        # 创建基础消息信息
        message_info = await self._create_base_message_info(core, config, context_tags, template_items)
        
        # 添加屏幕监控特有的附加配置
        message_info.additional_config["source"] = "screen_monitor"
        message_info.additional_config["image_data"] = self.raw_data.get("image_base64", "")
        message_info.additional_config["model_name"] = self.raw_data.get("model_name", "")
        message_info.additional_config["vl_prompt"] = self.raw_data.get("vl_prompt", "")

        # 构建消息段
        text = f"[屏幕描述更新] {self.description}"
        message_segment = Seg(type="text", data=text)

        return MessageBase(message_info=message_info, message_segment=message_segment, raw_message=text)


# --- Helper Function ---
# 移除旧的配置加载函数
# def load_plugin_config() -> Dict[str, Any]:
#     config_path = os.path.join(os.path.dirname(__file__), "config.toml")
#     try:
#         with open(config_path, "rb") as f:
#             if hasattr(tomllib, "load"):
#                 return tomllib.load(f)
#             else:
#                 try:
#                     import toml
#
#                     with open(config_path, "r", encoding="utf-8") as rf:
#                         return toml.load(rf)
#                 except ImportError:
#                     logger.error("toml package needed for Python < 3.11.") # 此处的 logger 也需处理
#                     return {}
#                 except FileNotFoundError:
#                     logger.warning(f"Config file not found: {config_path}") # 此处的 logger 也需处理
#                     return {}
#     except Exception as e:
#         logger.error(f"Error loading config: {config_path}: {e}", exc_info=True) # 此处的 logger 也需处理
#         return {}


# --- Plugin Class ---
class ScreenMonitorPlugin(BasePlugin):
    """
    定期截屏，通过 OpenAI 兼容接口调用 VL 模型获取描述，
    并将最新描述注册为 Prompt 上下文。
    !!! 警告：存在隐私风险和 API 成本 !!!
    """

    _is_amaidesucore_plugin: bool = True

    def __init__(self, core: AmaidesuCore, plugin_config: Dict[str, Any]):
        super().__init__(core, plugin_config)
        
        # 初始化所有必要属性，防止属性不存在的错误
        self.openai_client: Optional[AsyncOpenAI] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.latest_description = "屏幕信息尚未获取。"
        self.description_lock = asyncio.Lock()
        self.initialization_successful = False  # 新增：跟踪初始化是否成功

        self.config = self.plugin_config  # 直接使用注入的 plugin_config

        # --- 检查核心依赖 ---
        if mss is None or openai is None or Image is None:
            missing = [lib for lib, name in [(mss, "mss"), (openai, "openai"), (Image, "Pillow")] if lib is None]
            self.logger.error(
                f"缺少必要的库: {', '.join(missing)}。请运行 `pip install mss openai Pillow`。ScreenMonitorPlugin 已禁用。"
            )
            return

        # --- 加载配置 (使用新配置项) ---
        self.interval = self.config.get("screenshot_interval_seconds", 10)
        self.api_key = self.config.get("api_key", None)  # 通用 API Key
        self.base_url = self.config.get("openai_compatible_base_url", None)  # OpenAI 兼容 URL
        self.model_name = self.config.get("model_name", "qwen-vl-plus")  # 模型名称
        self.vl_prompt = self.config.get("vl_prompt", "请用一句话简洁描述这张图片的主要内容和活动窗口标题。")
        self.timeout_seconds = self.config.get("request_timeout", 20)  # 请求超时
        self.context_provider_name = self.config.get("context_provider_name", "screen_content_latest")
        self.context_priority = self.config.get("context_priority", 20)

        # --- 消息发送相关配置 ---
        self.send_messages = self.config.get("send_messages", True)  # 是否发送消息到MaiCore
        self.message_config = self.config.get("message_config", {})  # 消息配置
        self.context_tags = self.config.get("context_tags", [])  # 上下文标签
        self.template_items = self.config.get("template_items", {})  # 模板项

        # --- 检查关键配置 ---
        if not self.api_key or "YOUR_API_KEY_HERE" in self.api_key:
            self.logger.error(
                "API Key 未在 config.toml 中配置！ScreenMonitorPlugin 已禁用。"
            )
            return
        if not self.base_url:
            self.logger.error(
                "OpenAI 兼容 Base URL (openai_compatible_base_url) 未在 config.toml 中配置！ScreenMonitorPlugin 已禁用。"
            )
            return

        # --- 初始化 OpenAI 客户端 ---
        try:
            self.openai_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                # 可以根据需要添加 max_retries 等参数
            )
            self.logger.info(
                f"AsyncOpenAI 客户端已为模型 '{self.model_name}' 初始化 (Base URL: {self.base_url})。"
            )
            # 只有在成功初始化 OpenAI 客户端后才标记为成功
            self.initialization_successful = True
        except Exception as e:
            self.logger.error(f"初始化 AsyncOpenAI 客户端失败: {e}", exc_info=True)
            return

        # self.logger.info(f"ScreenMonitorPlugin 初始化完成。截图间隔: {self.interval}s, 模型: {self.model_name}") # 此日志可移除，基类有通用初始化日志

    async def _context_provider_wrapper(self) -> str:
        """Async wrapper method to provide the latest description for context."""
        # This simply calls the existing method that gets the description safely
        return await self.get_latest_description()

    async def setup(self):
        await super().setup()

        # 检查初始化是否成功，如果失败则不启动监控
        if not self.initialization_successful:
            self.logger.warning("ScreenMonitorPlugin 初始化失败，跳过后续设置。")
            return

        # 注册 Prompt 上下文提供者
        prompt_ctx_service = self.core.get_service("prompt_context")
        if prompt_ctx_service:
            prompt_ctx_service.register_context_provider(
                provider_name=self.context_provider_name,
                context_info=self._context_provider_wrapper,
                priority=self.context_priority,
                tags=["screen", "context", "vision", "dynamic"],
            )
            self.logger.info(
                f"已向 PromptContext 注册动态屏幕上下文提供者 '{self.context_provider_name}' (优先级: {self.context_priority})。"
            )
        else:
            self.logger.warning("未找到 PromptContext 服务，无法注册屏幕上下文。")

        # 启动后台监控循环
        self.is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop(), name="ScreenMonitorLoop")
        self.logger.info("屏幕监控后台任务已启动。")

    async def cleanup(self):
        self.logger.info("正在清理 ScreenMonitorPlugin...")
        self.is_running = False  # 通知后台任务停止

        # 取消并等待后台任务
        if self._monitor_task and not self._monitor_task.done():
            self.logger.debug("正在取消屏幕监控任务...")
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=2.0)
            except asyncio.TimeoutError:
                self.logger.warning("屏幕监控任务未能及时取消。")
            except asyncio.CancelledError:
                pass  # 预期行为

        # --- 关闭 OpenAI 客户端 ---
        if self.openai_client:
            try:
                # 使用 openai 库的关闭方法 (如果存在且需要)
                # await self.openai_client.close() # 根据 openai v1.x+ 文档，似乎不需要显式 close
                pass
            except Exception as e:
                self.logger.warning(f"关闭 OpenAI 客户端时出错(通常不需要): {e}")
            self.openai_client = None
            self.logger.info("OpenAI 客户端引用已清除。")

        # 取消注册 Prompt 上下文（只有在成功初始化的情况下才尝试取消注册）
        if self.initialization_successful:
            prompt_ctx_service = self.core.get_service("prompt_context")
            if prompt_ctx_service:
                try:
                    prompt_ctx_service.unregister_context_provider(self.context_provider_name)
                    self.logger.info(f"已从 PromptContext 取消注册屏幕上下文 '{self.context_provider_name}'。")
                except Exception as e:
                    self.logger.warning(f"尝试取消注册 '{self.context_provider_name}' 时出错: {e}")

        await super().cleanup()
        self.logger.info("ScreenMonitorPlugin 清理完成。")

    async def get_latest_description(self) -> str:
        """(供 PromptContext 调用) 异步安全地获取最新屏幕描述。"""
        # 如果初始化失败，返回默认描述
        if not self.initialization_successful:
            return "屏幕监控插件初始化失败，无法获取屏幕信息。"
        
        async with self.description_lock:
            return self.latest_description

    async def _monitoring_loop(self):
        """后台任务：定期截图并调用 VL 模型更新描述。"""
        self.logger.info("屏幕监控循环启动。")
        while self.is_running:
            start_time = time.monotonic()
            try:
                await self._capture_and_process_screenshot()
            except Exception as e:
                # 捕获截图或处理中的意外错误
                self.logger.error(f"屏幕监控循环中发生错误: {e}", exc_info=True)

            # --- 计算等待时间 ---
            elapsed = time.monotonic() - start_time
            wait_time = max(0, self.interval - elapsed)
            self.logger.debug(f"本次屏幕处理耗时 {elapsed:.2f}s，将等待 {wait_time:.2f}s 进行下一次。")

            try:
                # 使用 asyncio.sleep 进行可中断的等待
                await asyncio.sleep(wait_time)
            except asyncio.CancelledError:
                self.logger.info("屏幕监控循环被取消。")
                break  # 退出循环
        self.logger.info("屏幕监控循环结束。")

    async def _capture_and_process_screenshot(self):
        """执行截图、编码和调用 VL 模型。"""
        # 检查初始化是否成功
        if not self.initialization_successful or not self.openai_client:
            self.logger.debug("初始化未完成或 OpenAI 客户端不可用，跳过截图处理。")
            return

        self.logger.debug("正在截取屏幕...")
        encoded_image: Optional[str] = None
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                img_bytes = buffer.getvalue()
                encoded_image = base64.b64encode(img_bytes).decode("utf-8")
                self.logger.debug(f"截图成功并编码为 Base64 (大小: {len(encoded_image)} bytes)")
        except Exception as e:
            self.logger.error(f"截图或编码失败: {e}", exc_info=True)
            return

        if not encoded_image:
            return

        # --- 调用 VL 模型 (使用新方法) ---
        self.logger.debug(f"准备调用 VL 模型: {self.model_name} (通过 OpenAI 兼容接口)")
        new_description = await self._query_vl_model(encoded_image)  # 调用重命名后的方法

        if new_description:
            # 更新上下文描述
            async with self.description_lock:
                self.latest_description = new_description
            self.logger.info(f"屏幕描述已更新: {new_description[:100]}...")
            
            # 发送消息到MaiCore（如果启用）
            if self.send_messages:
                await self._send_screen_message(new_description, encoded_image)
        else:
            self.logger.warning("未能从 VL 模型获取有效描述。")

    async def _query_vl_model(self, base64_image: str) -> Optional[str]:
        """通过 OpenAI 兼容接口调用 VL 模型获取图像描述。"""
        if not self.openai_client:
            return None

        # 构建符合 OpenAI Vision API 格式的 messages
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.vl_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            # 使用 Data URL 格式
                            "url": f"data:image/png;base64,{base64_image}"
                        },
                    },
                ],
            }
        ]

        try:
            self.logger.debug(f"向 {self.base_url} 发送 OpenAI 兼容请求 (模型: {self.model_name})...")
            completion = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=300,  # 可以根据需要调整 max_tokens
            )
            self.logger.debug(f"OpenAI 兼容 API 响应: {completion}")

            # 解析响应
            if completion.choices and completion.choices[0].message:
                content = completion.choices[0].message.content
                if content:
                    return content.strip()
                else:
                    self.logger.warning("VL API 响应的消息内容为空。")
                    return None
            else:
                self.logger.warning(f"VL API 响应格式不符合预期: {completion}")
                return None

        except openai.APITimeoutError:
            self.logger.error(f"OpenAI 兼容 API 请求超时 (超时设置: {self.timeout_seconds}s)。")
            return None
        except openai.APIConnectionError as e:
            self.logger.error(f"无法连接到 OpenAI 兼容 API ({self.base_url}): {e}")
            return None
        except openai.RateLimitError as e:
            self.logger.error(f"OpenAI 兼容 API 速率限制错误: {e}")
            return None
        except openai.APIStatusError as e:
            self.logger.error(f"OpenAI 兼容 API 返回错误状态码 {e.status_code}: {e.response}")
            return None
        except Exception as e:
            self.logger.error(f"调用 OpenAI 兼容 API 时发生意外错误: {e}", exc_info=True)
            return None

    async def _send_screen_message(self, description: str, image_base64: str):
        """构造并发送屏幕描述消息到MaiCore"""
        try:
            # 创建屏幕消息对象
            screen_message = ScreenMessage(
                description=description,
                timestamp=int(time.time()),
                raw_data={
                    "image_base64": image_base64,
                    "model_name": self.model_name,
                    "vl_prompt": self.vl_prompt,
                }
            )
            
            # 构造MessageBase
            message = await screen_message.to_message_base(
                core=self.core,
                config=self.message_config,
                context_tags=self.context_tags,
                template_items=self.template_items,
            )
            
            # 发送到MaiCore
            await self.core.send_to_maicore(message)
            self.logger.info(f"屏幕描述消息已发送到MaiCore: {description[:50]}...")
            
        except Exception as e:
            self.logger.error(f"发送屏幕描述消息时出错: {e}", exc_info=True)


# --- Plugin Entry Point ---
plugin_entrypoint = ScreenMonitorPlugin
