"""通用依赖。"""
from typing import Any


def get_current_user() -> dict[str, Any]:
    """认证插槽（基线 B4）。

    认证已砍除，当前无条件返回固定系统用户；路由层统一挂载本依赖。
    未来若恢复登录（JWT），只需替换本函数实现并按用户校验，
    所有业务接口零改动。
    """
    return {"id": None, "username": "system", "role": "admin"}
