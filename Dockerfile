# 梅家坞茶园微气候智能体 · 云端部署镜像(Railway 等平台直接使用)
FROM python:3.12-slim

# 系统依赖(云端 Linux 精简镜像必需):
#   libexpat1     — rasterio/GDAL 运行时依赖(缺失则 ImportError: libexpat.so.1)
#   libgomp1      — LightGBM/OpenMP 运行时依赖
#   libstdc++6    — 多数科学计算 wheel 的 C++ 运行时
#   ca-certificates — requests 访问 Open-Meteo HTTPS
#   fonts-wqy-zenhei — 地图叠加层 PNG 的中文标题渲染(替代 Windows 的微软雅黑)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 libgomp1 libstdc++6 ca-certificates fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖, 利用构建缓存(requirements 不变时跳过重装)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
