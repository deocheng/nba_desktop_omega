# Node-Media-Server Docker & Kubernetes 部署指南

## 项目简介
Node-Media-Server 是基于 Node.js 的开源高性能实时流媒体服务器，支持 RTMP、RTMPS、HTTP/HTTPS‑FLV、WebSocket‑FLV 等协议。它提供完整的 REST API、JWT 认证、流录制、实时监控等功能，适合作为直播、点播、实时转码等场景的流媒体后端。

本仓库提供 **Docker** 与 **Kubernetes** 的一键部署方案，帮助你快速在本地或云端集群中启动 Node-Media-Server。

---

## 目录结构
```
├── Dockerfile                # 基础镜像构建文件
├── docker-compose.yml       # Docker Compose 部署文件
├── config
│   └── config.json          # 示例配置文件（可自行挂载覆盖）
└── k8s
    ├── configmap.yaml      # 将 config.json 注入 ConfigMap
    ├── deployment.yaml      # Deployment + Volume 挂载
    └── service.yaml         # Service（可选，示例）
```

---

## 1. 使用 Docker 部署
### 1.1 构建镜像
```bash
# 克隆仓库（或直接将本目录复制到本地）
git clone <your-repo-url>
cd <repo-dir>
# 构建镜像
docker build -t node-media-server:latest .
```
> 镜像基于 `node:18-alpine`，已预装 `ffmpeg`（需要时可自行移除）。

### 1.2 直接运行容器
```bash
docker run -d \
  --name nms \
  -p 1935:1935 -p 8000:8000 -p 8443:8443 \
  -v $(pwd)/config:/app/config \
  node-media-server:latest
```
- `-v $(pwd)/config:/app/config` 用于挂载自定义 `config.json`，如果不挂载则使用默认配置。
- 访问地址示例：
  - RTMP 推流：`rtmp://<host>:1935/live/<streamKey>`
  - HTTP‑FLV 播放：`http://<host>:8000/live/<streamKey>.flv`

### 1.3 使用 Docker Compose
```bash
docker-compose up -d
```
Compose 文件已声明了相同的端口映射和配置挂载，适合在本地开发环境快速启动。

---

## 2. 使用 Kubernetes 部署
> 适用于单节点或多节点集群（如 EKS、GKE、ACK）。以下示例基于 `kubectl` 操作。

### 2.1 创建 ConfigMap
```bash
kubectl apply -f k8s/configmap.yaml
```
这会把 `config/config.json` 注入名为 `node-media-server-config` 的 ConfigMap，Pods 启动时会挂载到 `/app/config`。

### 2.2 部署 Deployment
```bash
kubectl apply -f k8s/deployment.yaml
```
Deployment 会拉取本地构建的 `node-media-server:latest` 镜像（如果使用私有仓库，请在镜像地址前加上仓库前缀），并挂载 ConfigMap。

### 2.3 暴露服务（可选）
如果需要 ClusterIP/NodePort/LoadBalancer 形式的 Service，可自行创建 `k8s/service.yaml`（本仓库未提供示例，可参考以下最小化模板）：
```yaml
apiVersion: v1
kind: Service
metadata:
  name: node-media-server-service
spec:
  selector:
    app: node-media-server
  ports:
    - name: rtmp
      port: 1935
      targetPort: 1935
    - name: http-flv
      port: 8000
      targetPort: 8000
    - name: https-flv
      port: 8443
      targetPort: 8443
  type: LoadBalancer   # 根据需要可改为 NodePort
```
创建后，使用外部 IP 即可访问对应端口。

---

## 3. 常见操作示例
### 3.1 推流 / 播放
```bash
# 推流（使用 OBS 或 ffmpeg）
ffmpeg -re -i <input.mp4> -c copy -f flv rtmp://<host>:1935/live/stream

# 播放（使用浏览器或 VLC）
http://<host>:8000/live/stream.flv
```
### 3.2 使用 REST API
```bash
# 健康检查
curl http://<host>:8000/api/v1/health -H "Authorization: Bearer <jwt>"

# 查询活跃流列表
curl http://<host>:8000/api/v1/streams -H "Authorization: Bearer <jwt>"
```
> 详细 API 文档已写入 `README.md`，或参考项目自带的 Swagger UI（如有）。

---

## 4. 进阶配置
- **自定义 ffmpeg 参数**：在 `config/config.json` 的 `trans.ffmpeg.args` 中添加或覆盖。
- **开启 HTTPS**：在 `config.json` 中配置 `ssl`，并在容器挂载对应的证书文件。
- **高可用**：在 `k8s/deployment.yaml` 中将 `replicas` 调整为 >1，并使用 `StatefulSet` 搭配共享存储（如 NFS）实现录制文件的持久化。

---

## 5. 参考链接
- 项目主页：https://github.com/illuspas/Node-Media-Server
- Docker Hub（如已推送）：https://hub.docker.com/r/yourname/node-media-server
- 官方文档：https://node-media-server.com

---

## 6. 许可证
本部署示例遵循 Apache 2.0 许可证，详见项目根目录的 `LICENSE`。

---

如有疑问或需要二次定制（例如集成 RTMP‑to‑HLS、GPU 加速转码），欢迎在 GitHub Issues 中提出。
