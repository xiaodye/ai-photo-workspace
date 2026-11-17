from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai import ChatOpenAI

from app.providers import current_credentials
from app.tools import SPECS, ToolSpec

# 图像模型必须走 DashScope 原生接口，纯文本的规划模型可用 OpenAI 兼容模式
_COMPATIBLE_PATH = "/compatible-mode/v1"


class PlannerUnavailable(Exception):
    """规划模型未配置或不可用。"""


def _schema_of(spec: ToolSpec) -> dict:
    function = convert_to_openai_function(spec.params)
    function["name"] = spec.name
    function["description"] = spec.description

    parameters = function.get("parameters", {})
    for hidden in spec.agent_hidden:
        parameters.get("properties", {}).pop(hidden, None)
    parameters["required"] = [
        name for name in parameters.get("required", []) if name not in spec.agent_hidden
    ]
    return {"type": "function", "function": function}


def planner() -> ChatOpenAI:
    """按当前账号的 Key 构建规划模型，工具增减无需改动此处。"""
    credentials = current_credentials()
    model = ChatOpenAI(
        model=credentials.planner_model,
        api_key=credentials.api_key,
        base_url=f"{credentials.base_url}{_COMPATIBLE_PATH}",
        temperature=0,
        max_retries=0,
        timeout=60,
    )
    return model.bind_tools([_schema_of(spec) for spec in SPECS])
