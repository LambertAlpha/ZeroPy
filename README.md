# 资金费率套利策略系统 (Funding Rate Arbitrage System)

一个高效的量化交易系统，实现跨子账户的资金费率套利策略，自动化执行借贷、开平仓、资金划转等操作，以从交易所资金费率中获取稳定收益。

## 项目概述

### 核心策略逻辑
利用交易所统一账户提供的无息借贷额度，通过现货杠杆、U本位合约做空和币本位合约的组合操作，达到预设亏损目标后平仓并转向币本位做空来赚取资金费率。

### 关键技术指标
- 执行延迟：关键操作执行延迟 < 100ms
- 系统可用性：> 99.9%
- 并发支持：同时管理 20+ 子账户
- 风险控制：实时风险监控和自动干预

## 技术架构

采用**模块化单体架构**（Modular Monolith），优化内部模块通信效率，减少关键操作延迟。

### 核心技术栈
- **编程语言**：Python 3.9+
- **异步框架**：asyncio
- **数据处理**：pandas, numpy
- **API库**：ccxt
- **数据库**：TimescaleDB, Redis

## 快速开始

1. 克隆仓库
```bash
git clone https://github.com/your-organization/zeropy.git
cd zeropy
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境
```bash
cp config/default.example.yaml config/default.yaml
# 编辑配置文件，添加API密钥等信息
```

4. 启动系统
```bash
python -m src.app
```

## 项目结构

```
ZeroPy/
├── config/             # 配置文件
├── docs/               # 文档
├── logs/               # 日志
├── scripts/            # 工具脚本
├── src/                # 源代码
│   ├── app.py          # 应用入口
│   ├── modules/        # 核心模块
│   │   ├── market_data/ # 市场数据模块
│   │   ├── account/     # 账户管理模块
│   │   ├── execution/   # 交易执行模块
│   │   ├── strategy/    # 策略引擎模块
│   │   ├── risk/        # 风险监控模块
│   │   └── state/       # 状态管理模块
│   ├── models/         # 数据模型
│   ├── utils/          # 工具类
│   └── cli/            # 命令行接口
└── tests/              # 测试
    ├── unit/           # 单元测试
    └── integration/    # 集成测试
```

## 开发团队

- **后端工程师**: 核心逻辑和数据处理功能
- **DevOps工程师**: 部署和监控系统
- **量化分析师**: 策略参数优化和风险模型
- **测试工程师**: 自动化测试和质量保证
