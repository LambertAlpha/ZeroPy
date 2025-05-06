#!/bin/bash

# 检查.env文件是否存在
if [ ! -f .env ]; then
  echo ".env文件不存在，创建从.env.example复制"
  cp .env.example .env
  echo "请编辑.env文件，设置您的API密钥和其他配置"
  exit 1
fi

# 启动容器
echo "启动资金费率套利策略系统..."
docker-compose up -d

echo "启动完成！服务访问地址:"
echo "- Grafana: http://localhost:3000 (默认用户名/密码: admin/admin)"
echo "- Prometheus: http://localhost:9090"

echo "查看应用日志请使用: docker-compose logs -f app"
