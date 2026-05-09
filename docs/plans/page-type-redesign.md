# 页面类型分类体系 v3 — 基于真实 APP 聚类

## 0. 聚类结果

对 10 个 APP 按核心 UX 流程聚类为 **6 个类别**：

| 类别 ID | 名称 | APP | 特征 UX 链路 |
|---------|------|-----|-------------|
| `travel` | 出行预订 | 12306、携程、去哪儿旅行 | 搜索→列表→详情→预订→支付→订单 |
| `video` | 长视频 | 腾讯视频 | 首页→搜索→详情→选集→下载→播放 |
| `music` | 音乐音频 | QQ音乐 | 首页→搜索→歌单/专辑→播放器→下载→个人 |
| `sports` | 体育直播 | 直播吧 | 赛事列表→直播页→数据详情→社区 |
| `social` | 内容社区 | 小红书 | 信息流→笔记详情→发布→购物→个人 |
| `delivery` | 即时配送 | 美团、饿了么、京东外卖 | 首页→商家列表→菜单→规格配置→下单→支付→配送跟踪 |

---

## 1. 出行预订 `travel`

**APP**：12306、携程、去哪儿旅行

**UX 链路**：首页 → 搜索（出发地/目的地/日期）→ 路线列表（航班/车次）→ 班次详情 → 预订下单（乘客/保险/增值）→ 支付确认 → 订单管理

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `travel_home` | 出行首页 | 搜索入口、功能 icon、活动 banner | 弹窗广告、权限弹窗 |
| `travel_search` | 搜索筛选 | 城市选择、日期日历、舱位/座型、乘客数 | 查询按钮置灰 |
| `travel_route_list` | 路线结果 | 航班/车次卡片、价格、时间、余票 | **价格异常**、无票状态 |
| `travel_detail` | 班次详情 | 经停信息、舱位详情、退改规则 | 系统提示弹窗 |
| `travel_booking` | 预订下单 | 乘客信息、保险勾选、增值服务、联系人 | **增值服务总价异常** |
| `travel_payment` | 支付确认 | 支付方式、金额汇总、倒计时 | 支付超时、支付失败弹窗 |
| `travel_order` | 订单管理 | 订单列表、出票状态、退改入口 | 订单状态错误 |
| `travel_member` | 会员/个人 | 里程、优惠券、常用乘客 | 登录弹窗 |
| `travel_loading` | 加载等待 | 搜索等待、提交等待 | 加载超时 |

---

## 2. 长视频 `video`

**APP**：腾讯视频

**UX 链路**：首页推荐 → 搜索 → 内容详情（封面/简介/演职员）→ 选集面板 → 下载管理 → 播放器（进度条/弹幕/清晰度）→ 个人中心

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `video_home` | 视频首页 | 推荐流、分类 tab、热播 banner | 弹窗广告 |
| `video_search` | 搜索页 | 搜索框、搜索历史、分类标签 | 搜索无结果 |
| `video_content_detail` | 内容详情 | 封面大图、简介、演职员、相关推荐 | **内容名篡改**、权限限制弹窗 |
| `video_episode_select` | 选集面板 | 剧集列表、选集勾选框、清晰度选择 | **选集重复/混乱**、**选集置灰** |
| `video_download` | 下载管理 | 下载列表、缓存进度、存储管理 | **下载按钮遮挡** |
| `video_player` | 播放器 | 播放画面、进度条、弹幕、清晰度切换 | 响应延迟（卡顿假死） |
| `video_profile` | 个人中心 | 观看历史、收藏、追剧、会员 | 会员弹窗 |
| `video_loading` | 加载等待 | 视频缓冲、列表加载 | 加载超时 |

---

## 3. 音乐音频 `music`

**APP**：QQ音乐

**UX 链路**：首页推荐 → 搜索 → 专辑/歌单详情 → 播放器（封面/歌词/进度）→ 下载管理 → 个人/我的

区别于 `video`：
- 无选集面板，有**专辑/歌单详情页**（曲目列表）
- **播放器**以封面+歌词为核心，非全屏视频
- **下载**为音频文件，UI 轻量
- 无弹幕，有**歌词页面**

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `music_home` | 音乐首页 | 推荐、热门歌单、新歌速递、banner | 弹窗广告 |
| `music_search` | 搜索页 | 搜索框、热搜、分类 | 搜索无结果 |
| `music_album_detail` | 专辑/歌单 | 封面、曲目列表、播放全部、收藏 | 曲目重复、下载按钮遮挡 |
| `music_player` | 播放器 | 专辑封面、歌词、进度条、播放控制 | 响应延迟（播放卡顿）、歌词不同步 |
| `music_lyrics` | 歌词页 | 全屏歌词、逐行高亮 | 歌词错位/重叠 |
| `music_download` | 下载管理 | 已下载列表、下载中、音质选择 | 下载按钮遮挡 |
| `music_profile` | 个人中心 | 我喜欢、最近播放、创建歌单 | 登录弹窗 |
| `music_loading` | 加载等待 | 歌曲缓冲、列表加载 | 加载超时 |

---

## 4. 体育直播 `sports`

**APP**：直播吧

**UX 链路**：赛事列表（按日期/联赛）→ 直播页面（视频+实时数据）→ 数据统计详情 → 社区讨论 → 个人

区别于 `video`：
- 以**赛事日程**为核心导航，非内容推荐流
- 直播页有**实时数据面板**（比分/技术统计/阵容）
- 有独立的**数据统计页**
- 有**社区讨论**（赛后评论/球迷互动），类似论坛

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `sports_home` | 赛事首页 | 今日赛事、热门联赛、比分速览 | 弹窗广告 |
| `sports_schedule` | 赛事日程 | 按日期/联赛排列的赛事列表 | 列表重复、比分延迟 |
| `sports_live` | 直播页面 | 视频流、实时比分、事件时间轴 | **响应延迟**（直播卡顿） |
| `sports_data` | 数据统计 | 技术统计、阵容、历史交锋 | 数据加载失败 |
| `sports_community` | 社区讨论 | 帖子列表、评论区、发帖 | 评论加载失败、内容重复 |
| `sports_profile` | 个人中心 | 关注球队、预约提醒、设置 | 登录弹窗 |
| `sports_loading` | 加载等待 | 直播加载、数据刷新 | 加载超时 |

---

## 5. 内容社区 `social`

**APP**：小红书

**UX 链路**：信息流（推荐/关注）→ 笔记详情（图文/视频）→ 发布编辑 → 商城/购物 → 个人主页

区别于其他类：
- 以 **UGC 内容流**为核心，算法推荐
- 有**发布/编辑页**（图文混排、标签、位置）
- 内嵌**商城/购物**（不同于 retail 的外部电商，是平台内的内容驱动消费）
- **笔记详情**是图文+评论的综合体

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `social_feed` | 内容流 | 双列/单列笔记、推荐/关注切换 | 内容重复、图片加载失败 |
| `social_note_detail` | 笔记详情 | 图文/视频、标签、评论区 | 正文文字被遮挡、评论区加载失败 |
| `social_post_create` | 发布编辑 | 图片选择、文字编辑、话题标签、位置 | 发布按钮置灰 |
| `social_search` | 搜索发现 | 搜索框、热门话题、分类 | 搜索无结果 |
| `social_shop` | 商城 | 商品列表、商品详情、购物车 | 价格异常、下单按钮遮挡 |
| `social_message` | 消息/聊天 | 私信列表、对话 | 消息发送失败 |
| `social_profile` | 个人主页 | 头像、笔记列表、收藏、关注 | 登录弹窗 |
| `social_loading` | 加载等待 | 内容刷新、图片加载 | 加载超时 |

---

## 6. 即时配送 `delivery`

**APP**：美团、饿了么、京东外卖

**UX 链路**：首页 → 商家列表（评分/配送时间/距离）→ 菜单/商品列表（分类、价格）→ 规格配置（温度/甜度/配料/份量）→ 下单确认（优惠、合计）→ 支付 → 配送跟踪（实时地图、骑手位置）

区别于其他类：
- **规格配置页**独有的"多选一/多选多"交互（温度、甜度、配料），其他类无此形态
- **配送跟踪页**含实时地图+骑手位置+预计送达倒计时，travel 类无此实时性
- **商家列表**以评分/距离/配送费排序，不同于 travel 的航班价格排序
- 全链路有时间敏感性（配送倒计时、超时赔付）
- "商品"可以是食物、药品、生鲜、日用品——覆盖所有即时配送品类

| page_type | 名称 | 界面特征 | 典型异常 |
|-----------|------|---------|---------|
| `delivery_home` | 配送首页 | 推荐商家、分类入口、活动 banner | 弹窗广告、优惠券弹窗 |
| `delivery_shop_list` | 商家列表 | 按评分/距离排序的商家卡片 | 列表重复、商家信息遮挡 |
| `delivery_menu` | 菜单/商品 | 分类 tab、商品列表、价格、月售 | **价格异常**、售罄标识 |
| `delivery_item_config` | 规格配置 | 温度/甜度/配料/份量选择 | 必选项缺失、规格冲突 |
| `delivery_cart` | 下单确认 | 已选商品、优惠券、配送费、合计 | **价格计算错误**、优惠失效 |
| `delivery_payment` | 支付确认 | 支付方式、倒计时 | 支付超时弹窗 |
| `delivery_tracking` | 配送跟踪 | 实时地图、骑手位置、预计送达 | 配送状态卡死、位置不更新 |
| `delivery_profile` | 个人中心 | 地址管理、收藏、订单历史 | 登录弹窗 |
| `delivery_loading` | 加载等待 | 商家加载、支付等待 | 加载超时 |

---

## 7. 类别对比总览

| 维度 | travel | video | music | sports | social | delivery |
|------|--------|-------|-------|--------|--------|----------|
| 核心导航 | 搜索→预订 | 推荐→播放 | 推荐→播放 | 赛事→直播 | 推荐→浏览 | 首页→商家→菜单→下单→配送 |
| 独有页面 | 路线列表、预订下单、支付确认 | 选集面板、下载管理 | 专辑/歌单、歌词页 | 赛事日程、数据统计、社区 | 发布编辑、笔记详情、商城 | 规格配置、配送跟踪 |
| 关键异常 | 价格异常、增值服务 | 内容篡改、选集置灰、下载遮挡 | 曲目重复、歌词错位 | 直播卡顿、比分延迟 | 内容重复、图片加载失败 | 价格异常、配送卡死、规格冲突 |
| anomaly_mode 侧重 | modify_text, dialog | modify_text_ai, text_overlay, content_duplicate | content_duplicate, text_overlay, response_delay | response_delay, area_loading | content_duplicate, text_overlay | modify_text, dialog, response_delay |

---

## 8. 完整规则表

### 8.1 出行预订 `travel` — 9 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| travel_home_ad | travel_home | dialog | 弹窗广告 | 85 |
| travel_home_permission | travel_home | dialog | 权限请求弹窗 | 70 |
| travel_search_btn_disabled | travel_search | modify_text_ai | 查询按钮置灰 | 80 |
| travel_route_price_error | travel_route_list | modify_text | 价格逻辑错误 | 90 |
| travel_route_no_ticket | travel_route_list | modify_text | 无票状态提示 | 85 |
| travel_detail_prompt | travel_detail | dialog | 系统提示弹窗 | 70 |
| travel_booking_price | travel_booking | modify_text | 增值服务总价异常 | 80 |
| travel_payment_timeout | travel_payment | dialog | 支付超时弹窗 | 90 |
| travel_loading_timeout | travel_loading | area_loading | 加载超时 | 85 |

### 8.2 长视频 `video` — 9 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| video_home_ad | video_home | dialog | 弹窗广告 | 85 |
| video_content_name_tamper | video_content_detail | modify_text_ai | 内容名篡改 | 90 |
| video_content_permission | video_content_detail | dialog | 权限限制弹窗 | 75 |
| video_episode_duplicate | video_episode_select | content_duplicate | 选集重复/混乱 | 85 |
| video_episode_disabled | video_episode_select | modify_text_ai | 选集置灰 | 80 |
| video_download_blocked | video_download | text_overlay | 下载按钮遮挡 | 95 |
| video_player_delay | video_player | response_delay | 播放响应延迟 | 80 |
| video_profile_member | video_profile | dialog | 会员弹窗 | 65 |
| video_loading_timeout | video_loading | area_loading | 加载超时 | 70 |

### 8.3 音乐音频 `music` — 7 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| music_home_ad | music_home | dialog | 弹窗广告 | 85 |
| music_album_duplicate | music_album_detail | content_duplicate | 曲目列表重复 | 80 |
| music_album_download_blocked | music_album_detail | text_overlay | 下载按钮遮挡 | 85 |
| music_player_delay | music_player | response_delay | 播放响应延迟 | 80 |
| music_lyrics_error | music_lyrics | content_duplicate | 歌词错位/重叠 | 75 |
| music_profile_login | music_profile | dialog | 登录弹窗 | 65 |
| music_loading_timeout | music_loading | area_loading | 加载超时 | 70 |

### 8.4 体育直播 `sports` — 6 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| sports_home_ad | sports_home | dialog | 弹窗广告 | 85 |
| sports_schedule_duplicate | sports_schedule | content_duplicate | 赛事列表重复 | 75 |
| sports_live_delay | sports_live | response_delay | 直播卡顿延迟 | 90 |
| sports_data_fail | sports_data | area_loading | 数据加载失败 | 80 |
| sports_community_dup | sports_community | content_duplicate | 评论内容重复 | 70 |
| sports_loading_timeout | sports_loading | area_loading | 加载超时 | 75 |

### 8.5 内容社区 `social` — 6 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| social_feed_duplicate | social_feed | content_duplicate | 内容流重复 | 80 |
| social_note_text_blocked | social_note_detail | text_overlay | 正文被遮挡 | 75 |
| social_post_btn_disabled | social_post_create | modify_text_ai | 发布按钮置灰 | 85 |
| social_shop_price_error | social_shop | modify_text | 商品价格异常 | 80 |
| social_profile_login | social_profile | dialog | 登录弹窗 | 65 |
| social_loading_timeout | social_loading | area_loading | 加载超时 | 70 |

### 8.6 即时配送 `delivery` — 8 条

| 规则 ID | page_type | anomaly_mode | fault_mode | pri |
|---------|-----------|-------------|-----------|-----|
| delivery_home_ad | delivery_home | dialog | 弹窗广告 | 85 |
| delivery_home_coupon | delivery_home | dialog | 优惠券弹窗 | 75 |
| delivery_menu_price_error | delivery_menu | modify_text | 商品价格异常 | 85 |
| delivery_menu_sold_out | delivery_menu | dialog | 商品售罄弹窗 | 80 |
| delivery_config_conflict | delivery_item_config | content_duplicate | 规格选项冲突 | 70 |
| delivery_cart_price_error | delivery_cart | modify_text | 下单价格计算错误 | 90 |
| delivery_payment_timeout | delivery_payment | dialog | 支付超时弹窗 | 85 |
| delivery_tracking_stuck | delivery_tracking | response_delay | 配送状态卡死不更新 | 90 |

### 8.7 规则统计

| 类别 | APP | page_type 数 | 规则数 |
|------|-----|-------------|--------|
| travel | 12306、携程、去哪儿 | 9 | 9 |
| video | 腾讯视频 | 8 | 9 |
| music | QQ音乐 | 8 | 7 |
| sports | 直播吧 | 7 | 6 |
| social | 小红书 | 8 | 6 |
| delivery | 美团、饿了么、京东外卖 | 9 | 8 |
| **合计** | 10 个 APP | **49** | **45** |

---

## 9. 解耦验证

每一对类别的 page_type 交集为空：

| 对比 | 共享 page_type? |
|------|----------------|
| travel × video | ❌ travel 有 route_list/booking/payment，video 有 episode_select/download/player |
| travel × music | ❌ travel 无播放器/歌词，music 无预订/支付 |
| travel × delivery | ❌ travel 无规格配置/配送跟踪，delivery 无路线列表/预订 |
| video × delivery | ❌ video 有选集/下载/播放器，delivery 有商家/菜单/配送 |
| delivery × sports | ❌ delivery 有规格配置/配送跟踪，sports 有赛事/数据 |
| delivery × music | ❌ delivery 有配送跟踪，music 有歌词页 |

**新增第 7 个类别只需**：定义 7-9 个 page_type + 6-9 条规则，不动任何现有文件。

**新增第 6 个类别只需**：定义 6-8 个 page_type + 6-9 条规则，不动任何现有文件。
