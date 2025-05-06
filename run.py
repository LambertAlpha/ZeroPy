#!/usr/bin/env python
"""
带环境变量加载的启动脚本 - 用于加载.env文件并启动应用
"""
import os
import sys
import asyncio
from dotenv import load_dotenv

# 加载.env文件中的环境变量
load_dotenv()

# 将项目根目录添加到Python路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

# 导入应用并启动
from src.app import main

if __name__ == "__main__":
    asyncio.run(main())
