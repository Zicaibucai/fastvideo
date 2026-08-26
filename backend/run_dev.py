"""本地开发启动入口：视频文件连接不会无限期阻塞热重载。"""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        # 开发环境同时允许同一内网设备访问；生产环境请使用反向代理和访问控制。
        host=os.getenv("FASTVIDEO_DEV_HOST", "0.0.0.0"),
        port=8000,
        reload=True,
        timeout_graceful_shutdown=5,
    )
