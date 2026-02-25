# Warframe Market 查价接口（供 Apipost 调试）

**官方文档（v2）**：[WFM Api v2 Documentation](https://42bytes.notion.site/WFM-Api-v2-Documentation-5d987e4aa2f74b55a80db1a09932459d)

程序中已切换为 **v2** 接口，请求如下，可直接在 Apipost 中新建请求进行调试。

---

## 1. 查单个物品订单（程序实际使用）

**用途**：根据物品的 `url_name` 获取该物品的买卖单，程序里用其统计「在游戏内且卖单」的前 10 条价格。

| 项目 | 内容 |
|------|------|
| **方法** | `GET` |
| **URL** | `https://api.warframe.market/v2/orders/item/{url_name}` |
| **路径参数** | `url_name`：物品英文标识，如 `lex_prime_receiver`、`forma`、`mirage_prime_systems` |

### 请求头（程序中使用）

| Header 名 | 值 | 说明 |
|-----------|-----|------|
| `Accept` | `application/json` | 必填，程序里只用了这一项 |

### 可选请求头（文档支持，程序未用）

| Header 名 | 值示例 | 说明 |
|-----------|--------|------|
| `Language` | `en` / `zh-hans` | 返回内容语言，默认 `en` |
| `Platform` | `pc` / `ps4` / `xbox` / `switch` | 平台，默认 `pc` |

### 示例 URL（可直接在 Apipost 中请求）

- 雷克斯 Prime 枪机：  
  `https://api.warframe.market/v2/orders/item/lex_prime_receiver`
- Forma 蓝图：  
  `https://api.warframe.market/v2/orders/item/forma`
- Ivara Prime 机体蓝图：  
  `https://api.warframe.market/v2/orders/item/ivara_prime_systems`

### 成功响应结构（200，v2 实际返回）

```json
{
  "apiVersion": "0.22.7",
  "data": [
    {
      "id": "...",
      "type": "sell",
      "platinum": 5,
      "quantity": 1,
      "user": {
        "ingameName": "xxx",
        "status": "offline"
      }
    }
  ]
}
```

说明：v2 使用 **`data`** 数组（不是 `payload.orders`），订单类型字段为 **`type`**（不是 `order_type`）。  
程序逻辑：只取 `type == "sell"` 且 `user.status == "ingame"` 的订单，按 `platinum` 升序取前 5 条做价格展示。

---

## 2. 获取全部物品列表（数据对照表更新，update_wfm_items.py）

**用途**：拉取所有可交易物品，用于更新 `wfm_item_names_en_zh.csv`。文档：GET /v2/items。

| 项目 | 内容 |
|------|------|
| **方法** | `GET` |
| **URL** | `https://api.warframe.market/v2/items` |

### 请求头

| Header 名 | 值 | 说明 |
|-----------|-----|------|
| `Accept` | `application/json` | 必填 |
| `Language` | `zh-hans` 或 `en` | 可选，决定返回的 `item_name` 语言 |

### v2 响应结构（与 v1 不同）

```json
{
  "apiVersion": "x.x.x",
  "data": [ { "url_name": "mirage_prime_systems", "item_name": "Mirage Prime Systems", ... }, ... ],
  "error": null
}
```

注意：v2 使用 **`data`** 数组直接为物品列表，不是 v1 的 `payload.items`。`update_wfm_items.py` 已按此解析。

### 示例 URL

`https://api.warframe.market/v2/items`

---

## Apipost 快速填写

- **查价（程序用，v2）**  
  - 方法：GET  
  - URL：`https://api.warframe.market/v2/orders/item/lex_prime_receiver`  
  - Headers：`Accept: application/json`

- **物品列表（v2）**  
  - 方法：GET  
  - URL：`https://api.warframe.market/v2/items`  
  - Headers：`Accept: application/json`，可选 `Language: zh-hans`

以上均为公开接口，无需登录或 API Key。
