# Stitch 原始 screen 资源清单

项目 ID：`9598285378004174921`
获取方式：对每个指定 screen 单独调用 Stitch `get_screen`，然后使用 `curl.exe -L` 下载返回的 hosted URL。
Stitch 画布均为移动端：宽度 `780px`；下表中的截图尺寸与 MIME 是 hosted URL 实际返回值，HTML 文件为 UTF-8 原始页面代码。

## 统一视觉令牌（来自原始 HTML/CSS）

- 字体：`Inter`，正文与标题使用 400/500/600；图标字体为 `Material Symbols Outlined`。
- 主色：`#54643F`；主色容器 `#BDCFA2`；页面背景/Surface `#FBF9F8`；低层 Surface `#F5F3F3`；高层 Surface `#EAE8E7`；边框/轮廓 `#75786E`；错误色 `#BA1A1A`，错误容器 `#FFDAD6`；辅助色 `#78582D`。
- 圆角：默认 `4px`、`8px`、`12px`、全圆；卡片令牌 `24px`。
- 间距：基础 `4px`，紧凑堆叠 `8px`，中等堆叠 `16px`，大堆叠 `32px`，页面边距 `24px`，卡片内侧/栅格 gutter 常用 `16px`。
- 字号：`body-md 14/20`、`body-lg 16/24`、`label-md 12/16`（字距 `0.5px`）、`title-md 18/24`、`headline-lg-mobile 24/30`、`headline-lg 28/34`、金额展示 `40/48`；标题/金额权重 600，正文 400，标签 500。

## 页面资源

### 加入活动 (业务修正版)

- Screen ID：`da90a521bdcf4040a81a19ec745919f0`
- Stitch 尺寸：`780 × 1768`；设备：`MOBILE`
- HTML：[`join-activity.html`](./join-activity.html)
- Screenshot：[`join-activity.png`](./join-activity.png)，实际文件尺寸 `226 × 512`
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTc3ZjY3ODM4YWQwOTEwNGY0ZTNlMGI1YWExEgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1XWmLaAObCzRTSFGnLsytUt6w37kYafdC5I8b1XEShO9QCh3D8-XLXhF0fXB78JN-ne-oIBZa5kxOiR6YpWv5ChpiTGWqwYAiDyvdcp6q-hKRGRzVXg4KtypjkNiSduM35O1HDnxWJ47R8GsOUVeSMTwggeuholXANFv4hp1hFdt4orDBXQLPLrOVDUTZYUBlVgoa8p2vg3lcx29F3sutN25rko7fqekF6k0tPYmJ7jvkOOIR8fyiOoITc`
- 结构：固定顶部返回栏；8 位邀请码输入（4+4 分组）；“查找活动”主按钮；错误/已删除/已加入提示状态；活动摘要卡；参与人列表（已认领、本人、可选）；底部固定“确认加入”操作栏。
- 关键规格：页面边距 `24px`；顶部栏高 `64px`；输入格使用 `aspect-[3/4]`、`rounded-xl`，主按钮高 `56px`、全圆；主内容底部预留 `128px` 避开底部操作栏。

### 活动管理 (规范化版)

- Screen ID：`f11ea9f9ceec4f179852e8dfa4fd3e94`
- Stitch 尺寸：`780 × 3672`；设备：`MOBILE`
- HTML：[`activity-management.html`](./activity-management.html)
- Screenshot：[`activity-management.png`](./activity-management.png)，实际文件尺寸 `109 × 512`
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTc3ZjY0NTA4NTgwMGRiNDgwODc2MzJhYTk1EgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1WzjvrFGlboglF63PATYb8Zs51rNJJZeRTPC8HcI3Qwl66nrY0N4ERocMdEN1nBhoXsypGNnyJauBZ1EK_2lz1sP1qAXnCRMv-zQzciF2mjTGt0bq-b0-qsrMVi5lFdUbUrv_8eirw_XdlGIAW_npYn-XGyPFxUrvw0K6qkV4_A86W7OoN4nC6Lsm-GWlCoYHYz6OkRDfW8L_ZXpHqkdegI2nX8Bqm1yCTMtfTi4Py_MWAGHLxw4s81cg`
- 结构：顶部应用栏；页面标题与说明；基本信息卡（名称、类型、币种、多币种、加入码、锁定状态）；参与人管理卡；活动成员卡；活动状态卡；危险区域/删除或归档操作。原始注释明确隐藏全局底部导航。
- 关键规格：内容最大宽度 `480px`；页面边距 `24px`；主区垂直间距 `32px`；卡片 `rounded-xl`、内边距 `24px`；卡片内部网格/行间距约 `16px`；顶部栏左右 `24px`、上下 `16px`。

### 登录 / 注册 (UI优化版)

- Screen ID：`698b7d6c324f408aa9e813fd48b522d4`
- Stitch 尺寸：`780 × 1768`；设备：`MOBILE`
- HTML：[`login-register.html`](./login-register.html)
- Screenshot：[`login-register.jpg`](./login-register.jpg)，实际文件尺寸 `325 × 512`；hosted URL 实际返回 `image/jpeg`
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTc3ZmNmZGNkN2EwNjM5NzEyYWRlMWQ0ZTY3EgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1UXWqa_z3ycQqc7pKRleLSa2wvPS8szVMnPIwuzWiDGJqW9qu_mg2KmhKaIcpeGwowKIYdQMgLrpstiynQVBxpQWqceM7dVYVogLdl4kn15i_9QucvfomKrSaX2wpTBBIphnmJ5OQLVWdbSQErHPrg0bSJTGDZzuKtwTRaXDro1ERzgwLhd1ufNIYjrf6pYkbS04fYw5QChHkffspEtiuvjJBgmPpPD8mFMrcmTEjrlbLJYSUpim8T9wA`
- 结构：居中主容器；品牌标题与副标题；登录/注册分段控件；登录表单（邮箱、密码、忘记密码、登录）；注册表单（昵称、邮箱、密码、确认密码、注册）；密码显示切换与错误提示。
- 关键规格：主容器最大宽度 `480px`、内边距 `24px`，外层 padding `16px`；模块大间距 `32px`、标题组间距 `8px`；输入框 `px-6 py-4`、圆角 `12px`；分段控件内边距 `4px`、全圆；按钮 `py-4`、全圆。

### 资金记录详情 (状态补全版)

- Screen ID：`ff68a422309f42f4b51978d4bd77c870`
- Stitch 尺寸：`780 × 2348`；设备：`MOBILE`
- HTML：[`fund-record-detail.html`](./fund-record-detail.html)
- Screenshot：[`fund-record-detail.png`](./fund-record-detail.png)，实际文件尺寸 `170 × 512`
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTc3ZjVmYmRjMGYwMzgzOTM5OTk1MzhkMmU1EgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1UW9QXhLVBPLjfYxDr6TwphZWMzpQ9_1yvWsuULr6p9KJCbg7cnGRVJGa5sYhsI1eMy6hBHC5OdbL9IDLMgUt5tXCNGgdOxFoHpXSsUJvIq6lxNT_RgpHIIoewhwhfKm8Rn52lB63xKXDh5gH83EA1yKKPOn8VJPYi1sHLwE4oTB544mOLpwyTQ4R_xdO3-5CoiKvuOPs0_QM8G-ckU-5jcMiD6B9FK3CnVZeG7uO2XRM_5Vs7Jl37zS0o`
- 结构：顶部栏；争议提示卡（取消争议/有效状态）；核心资金卡（状态标签、付款人与收款人、箭头、金额、时间）；资金构成卡（偿还已有欠款、新增预存）；记录详情卡；底部固定取消争议操作。
- 关键规格：内容最大宽度 `480px`、页面边距 `24px`；主区顶部 margin `16px`、区块大间距 `32px`；核心卡 `rounded-[24px] p-6`、内部 gap `24px`；金额使用 `40/48`、权重 600；资金构成卡内边距 `20px`。

### 统一资金记录 (全新设计)

- Screen ID：`e5040aa018fb4b06ae39f486416d04a5`
- Stitch 尺寸：`780 × 1768`；设备：`MOBILE`
- HTML：[`unified-fund-records.html`](./unified-fund-records.html)，实际下载方法：PowerShell `Invoke-WebRequest` fallback（curl 失败）
- Screenshot：未落盘（curl 与单次 `Invoke-WebRequest` fallback 均失败，未创建占位图片）
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTdkNWQ4ZTM3NGQwOTI1ZDQ5ZTgwMTFlNDVlEgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1UonDqzYkty1T6zSRjQAiF38cBExnQQ_pOupXPDAj5TLz_laWQooIG2FyYhJzB1CFWWTia2VzC6fZEulznaDGLj5VaWv1WNz7kwpj65qEwDA-rrXHFMoKLu0b1UE07nJXTkFlKFGRSYaumkyYd0uh0r8LJNYjnB_ZxYY0on_xDgnMxEYdablA524bPgukBhZw0f_pFUrcOTe5wN26tZcyZf-vfp3u-ZL2pU5ViwLQw9Ll4ZccPUwQF1Uw`
- 下载状态：HTML 的 `curl.exe` 最终错误为 exit code `1`、`(28) Connection timed out after 20004 milliseconds`；单次 `Invoke-WebRequest` 成功。截图的 curl 最终 exit code `1`（`(28) Connection timed out after 20008 milliseconds`、`(35) schannel: failed to receive handshake, SSL/TLS connection failed`），fallback 返回 HTTP `400 (Bad Request)`。

### 账单详情 (业务对齐版)

- Screen ID：`b630d9184cf644a29dddefa09bbb7d1c`
- Stitch 尺寸：`780 × 2640`；设备：`MOBILE`
- HTML：[`bill-detail.html`](./bill-detail.html)
- Screenshot：[`bill-detail.png`](./bill-detail.png)，实际文件尺寸 `132 × 512`
- 原始 HTML URL：`https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1YTc3ZjY2NTgzNzQwMmE5YjM0ZWRjMGM5YmUzEgsSBxC23pbAnh8YAZIBIwoKcHJvamVjdF9pZBIVQhM5NTk4Mjg1Mzc4MDA0MTc0OTIx&filename=&opi=89354086`
- 原始 Screenshot URL：`https://lh3.googleusercontent.com/aida/AEtjO1XQuq-Ti-7SWnqlhrfDOeRUdLl_C0sJBfRl65UDV-2m93hMc-FnsRtIO73EBMjicHBXv8dvkIWhcgNLyDu4aS86CBZvwpElVy4UAwbRaGKS9kzy5x_bOruIX_6VSZwrdvvZri6deQIf-r_VNZuesAwmIfdb-BS928P8eCvkztnq9UBlLx_YrkHI3MVbgSMebe_cZccX0cLcDjY5yEpeS34_i14K2aw0o3Z9ophnqrR4D-G_zYSeaJ8Edoc`
- 结构：顶部栏；“此账单已删除”状态横幅；账单主卡（类别、商户、金额、基础币/原币、时间、备注）；付款信息卡；AA 平摊明细卡（Bob/Carol/Alice 状态与净垫付）；消费凭证图片区；恢复账单与更多操作底部区域；底部操作抽屉含添加退款/永久删除。
- 关键规格：内容最大宽度 `480px`、页面边距 `24px`；主区顶部 padding `16px`、区块间距 `32px`；主卡 `rounded-xl p-6`；信息卡 `rounded-xl p-4`；金额展示使用 `40/48`；删除横幅使用 `error-container`、内边距 `12px`。

## 下载完整性校验

校验算法：SHA-256。所有 10 个 hosted 资源均为非零文件；HTML 含 1 个 `html`、1 个 `body`，截图均可由 PNG 解码。

| 文件 | 字节数 | 实际尺寸/类型 | SHA-256 |
|---|---:|---|---|
| `join-activity.html` | 18670 | text/html | `1d43af502595fec4d2b870cae24dec45f22725a795717f328fa37d96c781d681` |
| `join-activity.png` | 12388 | 226 × 512, image/png | `75acd7ea2669ee90041b71467cf287967628116442adef7666424894d222c368` |
| `activity-management.html` | 17432 | text/html | `7ccc94a874bd9e25f1e369b622ab26c8e2971353b5bfd3fe982ac8968615f77b` |
| `activity-management.png` | 21747 | 109 × 512, image/png | `9180598e8b44d870bd58714fefb345962af8ecde382ac2547f051cd2e61eeb93` |
| `login-register.html` | 14492 | text/html | `b6308d659933141059e78b5bc9b29bbf7994b10d2a991ba038013d1cb629c995` |
| `login-register.jpg` | 15801 | 325 × 512, image/jpeg | `c0ecb21afafbd2607487d852c1c594dfb0f5bd366d601b7504ee57511346f686` |
| `fund-record-detail.html` | 14950 | text/html | `e4f414d839ed2a50ba479a2847a67954cbf7f3b78092c0f97602884fd55c9664` |
| `fund-record-detail.png` | 28828 | 170 × 512, image/png | `a4964278abb1d3d89edde3e9134cc6ceb318279a7c94b9779671cb7837f3b34a` |
| `bill-detail.html` | 15662 | text/html | `4b8c23300c79421019cfe0bd1071f92e5bbfa0d5582bae889bf867bcb5a92956` |
| `bill-detail.png` | 28176 | 132 × 512, image/png | `021bbba9efd6623d75b7b812420bdab8de1d757de4a581d4012997aaccc9cbfd` |

> 本次目标资源中，`fund-record-detail.html/.png` 已存在且已用最新 `get_screen` 元数据复核；统一页 HTML 已通过单次 PowerShell fallback 落盘，截图因 hosted 失败未生成。

| `unified-fund-records.html` | 13396 | text/html；1 html / 1 body | `edbe205f739cf30f0ba7a6daba75e38c96ed0ae9bea648b876a9dec0969088c6` |

> `unified-fund-records.png` 未生成：Stitch 响应未返回 base64，且 hosted screenshot URL 的 curl 与单次 PowerShell fallback 均失败。
