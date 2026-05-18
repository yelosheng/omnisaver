# Camoufox 反复消失问题 — 完整记录与终极解决方案

## 问题现象

WeChat 文章保存失败，报错：

```
FileNotFoundError: Camoufox browser not installed at /home/huang/.cache/camoufox.
Run: venv/bin/python -m camoufox fetch
```

该问题自 2026 年 4 月起反复出现，每次重装后几天又会复现。

---

## 根本原因分析

### camoufox 的设计缺陷

`camoufox.pkgman.CamoufoxFetcher.install()` 的逻辑：

```python
def install(self) -> None:
    self.cleanup()       # 第一步：直接删除 ~/.cache/camoufox（shutil.rmtree）
    # 第二步：从 GitHub 下载新版本
    # 如果下载失败：
    except:
        self.cleanup()   # 再次删除，确保"干净"
```

**先删后下，下载失败则两手空空。** 这个逻辑在网络不稳定时会必然触发问题。

### 触发路径

有两条路径都会触发 `install()`，从而导致删除：

1. **服务内部自动触发**：`camoufox_path()` 检测到安装版本不在支持范围内（`CONSTRAINTS`），自动调用 `install()`。
2. **手动执行 `camoufox fetch`**：该命令会检查 GitHub 最新版本，若版本不同则调用 `install()`。网络断开 → 删除成功，下载失败 → 目录消失。

### 历次事故时间线

| 时间 | 事件 |
|------|------|
| 2026-04-28 | 服务内部触发自动更新（3次），每次删目录后下载失败 |
| 2026-04-29 | 修复1：替换 `camoufox_path()` 为不触发更新的版本 |
| 2026-05-05 | 用户重装 camoufox，服务恢复 |
| 2026-05-13 | 目录再次消失（原因不明，推测为手动执行 `camoufox fetch` 触发版本更新） |
| 2026-05-18 | 修复2：增加 `CamoufoxFetcher.cleanup` no-op 补丁 + `chattr +i` 锁定目录 |

---

## 最终解决方案（三层防护）

### 第一层：代码补丁（`services/wechat_service.py`）

在服务进程内，通过猴子补丁禁用两个关键函数：

```python
# 替换 camoufox_path()：目录存在就返回，不做版本检查，不触发下载
def _camoufox_path_no_autoupdate(download_if_missing=True):
    if _CF_INSTALL_DIR.exists() and any(_CF_INSTALL_DIR.iterdir()):
        return _CF_INSTALL_DIR
    raise FileNotFoundError(
        f'Camoufox browser not installed at {_CF_INSTALL_DIR}. '
        'Run: venv/bin/python -m camoufox fetch'
    )

# 替换 CamoufoxFetcher.cleanup()：变为空操作，永远不删目录
def _camoufox_cleanup_noop():
    return False

_cfpkgman.camoufox_path = _camoufox_path_no_autoupdate
_cfpkgman.CamoufoxFetcher.cleanup = staticmethod(_camoufox_cleanup_noop)
```

**保护范围**：服务运行期间，所有内部调用路径均被拦截。

### 第二层：chattr +i 不可变标志（终极保护）

```bash
sudo chattr -R +i /home/huang/.cache/camoufox
```

将目录及所有文件设为不可变（immutable），效果：
- `shutil.rmtree` 失败
- `rm -rf` 失败
- 即使 root 也无法删除
- 对读取和执行无任何影响

验证命令：
```bash
lsattr -d /home/huang/.cache/camoufox
# 输出应包含 'i' 标志：----i---------e------- /home/huang/.cache/camoufox
```

### 第三层：服务补丁已随服务重启生效

补丁通过 `wechat_service.py` 模块级代码在服务启动时自动应用，无需额外操作。

---

## 日常操作指南

### 服务正常使用
无需任何操作，`chattr +i` 和代码补丁共同保护。

### 手动执行 `camoufox fetch` 时（⚠️ 危险操作）
```bash
# 第一步：解除不可变保护
sudo chattr -R -i /home/huang/.cache/camoufox

# 第二步：执行更新（确保网络稳定！）
venv/bin/python -m camoufox fetch

# 第三步：重新锁定
sudo chattr -R +i /home/huang/.cache/camoufox
```

**警告**：第二步如果网络中断，目录会被删空。务必在网络稳定时操作。

### camoufox 目录再次消失时的恢复步骤

```bash
# 1. 解锁（如果之前加了锁）
sudo chattr -R -i /home/huang/.cache/camoufox 2>/dev/null || true

# 2. 重装
venv/bin/python -m camoufox fetch

# 3. 重新锁定
sudo chattr -R +i /home/huang/.cache/camoufox

# 4. 重启服务
echo '^GVPQ!K73cVfY^' | sudo -S systemctl restart uds_twitter_saver
```

---

## 为什么之前的修复不够彻底

| 修复版本 | 措施 | 缺陷 |
|----------|------|------|
| 修复1（4月29日） | 替换 `camoufox_path()` | 只阻止了服务内部的版本检查路径，`CamoufoxFetcher.cleanup()` 本身未被拦截，手动 `camoufox fetch` 仍可触发删除 |
| 修复2（5月18日） | 增加 `cleanup` no-op + `chattr +i` | 代码层面彻底封堵所有路径；`chattr +i` 提供系统级兜底保护，即使代码层补丁失效也无法删除 |
