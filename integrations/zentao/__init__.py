"""integrations/zentao — 禅道集成单包（M06，T-053）。

禅道所有出入动作的唯一通道：只读（story get/search、bug get）与
写（story create/update、bug create）同包维护，杜绝第二套禅道链接。

协议与 devops skill zentao_client 同源：
- v1: {base}/api.php/v1/*（Token 大写 header）
- v2: {base}/api.php/v2/*（token 小写 header）
凭据只经环境变量（SG_ZENTAO_TOKEN / SG_ZENTAO_BASE_URL）或调用方显式传入，
永不进 argv、不落日志。
"""

from integrations.zentao.api import (
    ZenTaoClient,
    ZenTaoAPIError,
    DEFAULT_BASE_URL,
)

__all__ = ["ZenTaoClient", "ZenTaoAPIError", "DEFAULT_BASE_URL"]
