# Twitter Content Saver API Documentation

本文档提供Twitter内容保存工具的RESTful API接口说明，支持通过编程方式提交推文保存任务。

## 支持的Twitter URL格式

API支持以下Twitter URL格式：

- `https://twitter.com/username/status/1234567890`
- `https://x.com/username/status/1234567890`
- `https://www.twitter.com/username/status/1234567890`
- `https://www.x.com/username/status/1234567890`
- `https://mobile.twitter.com/username/status/1234567890`
- `https://m.twitter.com/username/status/1234567890`
- `https://fxtwitter.com/username/status/1234567890`
- `https://fixupx.com/username/status/1234567890`

所有URL格式都支持HTTP和HTTPS协议，系统会自动提取推文ID进行处理。

## API Endpoints

### POST /api/submit

**提交推文URL进行下载**

**支持的请求格式:**

#### 1. JSON格式 (推荐)
```bash
curl -X POST http://localhost:6201/api/submit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://twitter.com/user/status/123456789"}'
```

#### 2. Form格式
```bash
curl -X POST http://localhost:6201/api/submit \
  -d "url=https://twitter.com/user/status/123456789"
```

#### 3. 纯文本格式
```bash
curl -X POST http://localhost:6201/api/submit \
  -H "Content-Type: text/plain" \
  -d "https://twitter.com/user/status/123456789"
```

#### 4. URL参数格式
```bash
curl -X POST "http://localhost:6201/api/submit?url=https://twitter.com/user/status/123456789"
```

**响应格式:**

- **成功 (201)**: 新任务创建
```json
{
  "success": true,
  "message": "任务已添加到队列",
  "task_id": 123,
  "url": "https://twitter.com/user/status/123456789",
  "status": "pending",
  "queue_size": 1
}
```

- **成功 (200)**: 任务已存在
```json
{
  "success": true,
  "message": "任务已存在 (状态: completed)",
  "task_id": 123,
  "url": "https://twitter.com/user/status/123456789",
  "status": "completed",
  "duplicate": true
}
```

- **错误 (400)**: 无效请求
```json
{
  "success": false,
  "error": "Invalid Twitter URL",
  "message": "无效的Twitter URL: invalid-url",
  "url": "invalid-url"
}
```

### GET /api/status/{task_id}

**获取任务状态**

```bash
curl http://localhost:6201/api/status/123
```

**响应格式:**
```json
{
  "success": true,
  "task": {
    "id": 123,
    "url": "https://twitter.com/user/status/123456789",
    "status": "completed",
    "tweet_id": "123456789",
    "author_username": "user",
    "author_name": "User Name",
    "save_path": "saved_tweets/2025-07-26_123456789",
    "is_thread": false,
    "tweet_count": 1,
    "media_count": 2,
    "retry_count": 0,
    "created_at": "2025-07-26 10:30:00",
    "processed_at": "2025-07-26 10:31:15",
    "error_message": null
  }
}
```

### GET /api/tasks

**获取任务列表**

```bash
# 获取所有任务
curl http://localhost:6201/api/tasks

# 按状态筛选
curl "http://localhost:6201/api/tasks?status=completed&page=1&per_page=20"
```

**支持的查询参数:**
- `status`: 任务状态筛选 (`pending`, `processing`, `completed`, `failed`)
- `page`: 页码 (默认: 1)
- `per_page`: 每页条目数 (默认: 20)

### GET /api/saved

**获取已保存推文列表**

```bash
# 获取已保存推文
curl http://localhost:6201/api/saved

# 搜索推文
curl "http://localhost:6201/api/saved?search=关键词&page=1&per_page=12"
```

**支持的查询参数:**
- `search`: 搜索关键词 (搜索推文内容和作者)
- `page`: 页码 (默认: 1)
- `per_page`: 每页条目数 (默认: 12)

### GET /api/retry-tasks

**获取重试任务列表**

```bash
curl http://localhost:6201/api/retry-tasks
```

### POST /api/retry-now/{task_id}

**立即重试指定任务**

```bash
curl -X POST http://localhost:6201/api/retry-now/123
```

### POST /api/reset-retries/{task_id}

**重置任务重试计数**

```bash
curl -X POST http://localhost:6201/api/reset-retries/123
```

## API使用示例

### Python示例

```python
import requests
import json
import time

# 提交推文URL
url = "https://twitter.com/user/status/123456789"
response = requests.post(
    "http://localhost:6201/api/submit",
    json={"url": url},
    verify=False  # 如果使用自签名证书
)

if response.status_code in [200, 201]:
    result = response.json()
    task_id = result["task_id"]
    print(f"任务已提交，ID: {task_id}")
    
    # 轮询任务状态
    while True:
        status_response = requests.get(f"http://localhost:6201/api/status/{task_id}")
        status_data = status_response.json()
        
        if status_data["success"]:
            task_status = status_data["task"]["status"]
            print(f"任务状态: {task_status}")
            
            if task_status in ["completed", "failed"]:
                break
        
        time.sleep(5)  # 等待5秒后再次检查
```

### Shell脚本示例

```bash
#!/bin/bash

# 提交推文并获取任务ID
RESPONSE=$(curl -s -X POST http://localhost:6201/api/submit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://twitter.com/user/status/123456789"}')

TASK_ID=$(echo $RESPONSE | jq -r '.task_id')
echo "任务ID: $TASK_ID"

# 等待任务完成
while true; do
  STATUS=$(curl -s http://localhost:6201/api/status/$TASK_ID | jq -r '.task.status')
  echo "当前状态: $STATUS"
  
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    break
  fi
  
  sleep 5
done
```

### JavaScript示例

```javascript
async function submitTweet(url) {
    try {
        const response = await fetch('http://localhost:6201/api/submit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });
        
        const result = await response.json();
        
        if (result.success) {
            console.log(`任务已提交，ID: ${result.task_id}`);
            return result.task_id;
        } else {
            console.error('提交失败:', result.error);
        }
    } catch (error) {
        console.error('请求失败:', error);
    }
}

async function checkTaskStatus(taskId) {
    try {
        const response = await fetch(`http://localhost:6201/api/status/${taskId}`);
        const result = await response.json();
        
        if (result.success) {
            return result.task.status;
        }
    } catch (error) {
        console.error('获取状态失败:', error);
    }
}

// 使用示例
async function main() {
    const taskId = await submitTweet('https://twitter.com/user/status/123456789');
    
    if (taskId) {
        // 轮询状态
        while (true) {
            const status = await checkTaskStatus(taskId);
            console.log(`任务状态: ${status}`);
            
            if (status === 'completed' || status === 'failed') {
                break;
            }
            
            await new Promise(resolve => setTimeout(resolve, 5000)); // 等待5秒
        }
    }
}
```

## 任务状态说明

- `pending`: 任务已提交，等待处理
- `processing`: 任务正在处理中
- `completed`: 任务已完成
- `failed`: 任务处理失败

## 错误处理

API返回标准HTTP状态码：
- `200`: 成功 (资源已存在)
- `201`: 成功 (新资源已创建)
- `400`: 客户端错误 (无效的URL格式等)
- `404`: 资源不存在
- `500`: 服务器内部错误

所有错误响应都包含 `success: false` 和详细的错误信息。

## 注意事项

1. **HTTPS支持**: 如果服务器配置了SSL证书，API将自动启用HTTPS
2. **自签名证书**: 使用自签名证书时，客户端需要设置 `verify=False` (Python) 或相应的忽略证书验证选项
3. **URL验证**: 系统会自动验证提交的URL是否为有效的Twitter链接
4. **重复提交**: 重复提交相同URL会返回已存在任务的信息，不会创建新任务
5. **任务队列**: 系统使用后台队列处理任务，提交后需要轮询状态获取处理结果