#!/bin/bash

# 如果指定了服务名，则查看特定服务的日志，否则查看app的日志
if [ -z "$1" ]; then
  echo "查看应用日志..."
  docker-compose logs -f app
else
  echo "查看 $1 服务的日志..."
  docker-compose logs -f "$1"
fi
