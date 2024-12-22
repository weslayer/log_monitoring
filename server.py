import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from collections import deque
from typing import Dict, Set
import docker
from pathlib import Path
import uvicorn

client = docker.from_env()
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
active_connections: Dict[str, Set[WebSocket]] = {}
log_buffers: Dict[str, deque] = {}
BUFFER_SIZE = 400

@app.get("/", response_class=HTMLResponse)
async def get_root():
    return Path('static/index.html').read_text()

@app.get("/api/containers")
async def get_containers():
    running_containers = client.containers.list(filters={"status": "running"})
    containers_info = []
    for container in running_containers:
        containers_info.append({
            "id": container.id,
            "name": container.name,
            "image": container.image.tags,
            "status": container.status
        })
    return containers_info

async def stream_logs(container_id: str):
    container = client.containers.get(container_id)
    try:
        for line in container.logs(stream=True, follow=True):
            log_line = line.decode('utf-8').strip()
            log_buffers[container_id].append(log_line)
            # Send log to all active WebSocket connections
            dead_connections = set()
            for conn in active_connections.get(container_id, set()):
                try:
                    await conn.send_text(log_line)
                except:
                    dead_connections.add(conn)
            active_connections[container_id] -= dead_connections
            await asyncio.sleep(0.1)
    except docker.errors.NotFound:
        pass  # Container might have been stopped
    except Exception as e:
        print(f"Error streaming logs for {container_id}: {e}")

@app.websocket("/ws/{container_id}")
async def websocket_endpoint(websocket: WebSocket, container_id: str):
    await websocket.accept()

    if container_id not in active_connections:
        active_connections[container_id] = set()
        log_buffers[container_id] = deque(maxlen=BUFFER_SIZE)
        # Start streaming logs in the background
        asyncio.create_task(stream_logs(container_id))

    active_connections[container_id].add(websocket)

    # Send existing logs from buffer
    for log in log_buffers[container_id]:
        await websocket.send_text(log)

    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections[container_id].remove(websocket)
    except Exception as e:
        active_connections[container_id].remove(websocket)
        print(f"WebSocket error: {e}")
            
    except docker.errors.NotFound:
        await websocket.close(code=1000, reason="Container not found")
    except Exception as e:
        await websocket.close(code=1000, reason=str(e))
    finally:
        if container_id in active_connections:
            active_connections[container_id].discard(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3100)
