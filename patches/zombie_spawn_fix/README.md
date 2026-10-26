### 说明
* [修补寻位函数以及玩家特感灵魂状态检测函数以使其放宽过滤条件或跳过某些条件限制](https://forums.alliedmods.net/showthread.php?t=333351)

### 安装（重要）
1. 放入 `gamedata/zombie_spawn_fix.txt`
2. 编译 `zombie_spawn_fix.sp` → `plugins/zombie_spawn_fix.smx`
3. **不要**再通过 `sourcescramble_manager` 加载同一批补丁  
   - 删除或禁用 `configs/sourcescramble/zombie_spawn_fix.txt`  
   - 否则 manager 会先改内存，本插件 `Validate()` 必然报 `Failed to verify patch`

> HarryPotter 也说明过：使用本插件时 **不需要** `configs/sourcescramble/zombie_spawn_fix.txt`。

### 与以下插件一同使用，效果更佳
* [l4d_unrestrict_panic_battlefield](https://forums.alliedmods.net/showpost.php?p=2815688&postcount=1024)

### Changelog
* **1.0.10**
  - 明确禁止与 `sourcescramble_manager` 配置双重打补丁；校验失败时给出提示
  - Windows gamedata 在 L4D2 `PatchVersion=2.2.4.3`（`server.dll`）上复核：签名与 verify 字节仍匹配
* **1.0.9** (28-Apr-2022) — 原作者最后发布版
