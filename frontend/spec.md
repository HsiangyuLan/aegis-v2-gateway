# ⚡️ Supreme Vibe-Coding UI/UX Architecture Spec

## 1. 核心真理 (Brand Tokens)

嚴禁使用任何近似色，必須 100% 鎖定以下 HEX 代碼與字體映射。

| 屬性                    | 規格與變數                     | 戰略意義                                     |
| :---------------------- | :----------------------------- | :------------------------------------------- |
| **Primary Brand Color** | `#FF0000`                      | 絕對純紅。嚴禁任何 Alpha 透明度或漸層。      |
| **Absolute White**      | `#FFFFFF`                      | 充當無盡的背景虛無。                         |
| **Pitch Black**         | `#000000`                      | 用於內文與商品邊界。                         |
| **Header Font**         | `Futura-Heavy` / `Futura-Bold` | 標題與 Logo 專屬，無情且幾何的現代主義宣告。 |
| **Body Font**           | `Inter-Bold`                   | 內文專用，強烈且具現代工業感的閱讀骨架。     |

## 2. 佈局幾何 (Layout Metrics)

所有數值基於 `1440px` Viewport 推導，採用 Vibe Coding 最小可行性產品 (MVP) 第一階段規格。

- **Global Container**:
  - `max-width: 1440px; margin: 0 auto; background-color: #FFFFFF;`
- **Header (Logo & Datetime)**:
  - **Logo Box**: `width: 130px; height: 40px; background-color: #FF0000;`
  - **Logo Text**: `color: #FFFFFF; font-family: Futura-Heavy; font-style: italic;` (文字需水平垂直置中)。
  - **Timestamp**: `margin-top: 16px; font-family: Inter-Bold; font-size: 12px; letter-spacing: 0.05em; color: #000000; text-align: center;`
- **Navigation (Left Sidebar)**:
  - `width: 180px; position: absolute; left: 0;`
  - `text-align: right;` (核心特徵：文字必須貼齊右側邊界)。
  - `font-family: Inter-Bold; font-size: 13px; line-height: 1.8;`
- **Product Grid (Main Content)**:
  - `margin-left: 200px; padding-right: 40px;` (讓出導覽列空間)。
  - `display: grid; grid-template-columns: repeat(5, 1fr); gap: 20px;`

## 3. 圖片比例與拼接 (Aspect Ratios)

- **Shop/Preview Grid (截圖 1 & 3)**:
  - 圖片容器強制鎖定 `aspect-ratio: 1 / 1;`。
- **Lookbook Carousel (截圖 2)**:
  - 這不是 Grid，這是 Flexbox 的暴力拼接。
  - `display: flex; flex-wrap: nowrap; gap: 0; overflow-x: auto;`
  - 每張單體圖片寬度為 `15vw`，高度強制拉伸至 `75vw` (`aspect-ratio: 1 / 5`)，圖片之間 **0px** 間距。

## 4. 防禦性編碼指令 (Defensive Constraints)

在 Cursor Composer 生成程式碼時，必須包含以下防呆與容錯處理：

1.  **Image Fallback**: 所有 `<img />` 標籤必須掛載 `object-fit: cover;` 與 `object-position: center;`，並設置 `background-color: #F4F4F4;` 作為圖片載入失敗時的底色。
2.  **Grid Degradation**: 設置 `@media` 查詢，若螢幕寬度 `< 1024px`，`grid-template-columns` 必須自動降維為 `repeat(3, 1fr)`；`< 768px` 降維至 `repeat(2, 1fr)`。
3.  **Input Validation**: 若系統後端傳入的商品圖片 URL 為空值 (null/undefined)，前端組件必須自動攔截並渲染空心白框 (`border: 1px solid #000000`)。
