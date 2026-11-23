# SocialBot：Threads 每日自動發文機器人

每天台灣時間早上 8 點左右，由 GitHub Actions 自動從 `posts.json` 取出第一篇未發布的文章，透過**官方 Threads API**（免費）發到你的帳號。

- 發文成功後自動更新 `posts.json` 並 commit 回 repo
- 未發布文章少於 5 篇時，自動開 Issue 提醒補文章
- Token 剩 10 天內到期時，自動開 Issue 提醒續期
- 超過 500 字元的文章會被跳過並在執行紀錄中警告
- 支援 dry-run：只顯示今天要發哪一篇，不實際發文

---

## 目錄

1. [專案結構](#1-專案結構)
2. [申請 Meta 開發者帳號與 Threads API 權限](#2-申請-meta-開發者帳號與-threads-api-權限)
3. [取得長期 Access Token](#3-取得長期-access-token)
4. [設定 GitHub Secrets 與 Variables](#4-設定-github-secrets-與-variables)
5. [啟用排程與第一次執行](#5-啟用排程與第一次執行)
6. [posts.json 格式](#6-postsjson-格式)
7. [如何新增文章](#7-如何新增文章)
8. [本機測試方法](#8-本機測試方法)
9. [更新長期 Token（約每 50 天一次）](#9-更新長期-token約每-50-天一次)
10. [常見錯誤排解](#10-常見錯誤排解)

---

## 1. 專案結構

```
.github/workflows/
  daily-post.yml     每日排程發文（也可手動觸發，可選 dry-run）
  tests.yml          每次 push 自動跑 pytest
bot/
  config.py          從環境變數讀設定
  posts.py           讀寫 posts.json、挑文章、組內文、檢查長度
  threads_api.py     Threads API 呼叫與錯誤分類
  github_issue.py    開提醒 Issue（不重複開）
  main.py            主流程（python -m bot.main）
  token_tool.py      本機用的 token 取得／續期工具
tests/               pytest 測試（API 全部 mock，不會真的發文）
posts.json           文章資料
```

## 2. 申請 Meta 開發者帳號與 Threads API 權限

> Meta 後台介面常改版，按鈕名稱可能略有不同，但流程大致如下。整個過程**免費**，自己帳號用不需要送 App Review。

1. **準備帳號**：你需要一個 Threads 帳號（它綁定在 Instagram 帳號上），以及一個 Facebook 帳號用來登入開發者後台。
2. **註冊開發者**：到 <https://developers.facebook.com/>，右上角「開始使用」／「Get Started」，完成開發者註冊（驗證手機或信箱）。
3. **建立 App**：「我的應用程式」→「建立應用程式」，使用案例選 **「存取 Threads API」（Access the Threads API）**。
4. **加入權限**：在 App 後台「使用案例」→ Threads API →「自訂」，確認權限包含：
   - `threads_basic`
   - `threads_content_publish`
5. **設定 Redirect URI**：同一頁的「設定」中，「重新導向回呼網址」（Redirect Callback URLs）填入例如 `https://localhost/`（必須是 https；頁面打不開沒關係，我們只需要網址列上的 code）。
6. **加入測試人員**：「應用程式角色」→「角色」→ 新增 **Threads 測試人員**，輸入你的 Threads 帳號名稱。
7. **在 Threads 接受邀請**：打開 Threads（網頁或 App）→ 設定 → 帳號 → 網站權限 → 邀請，接受剛才的邀請。
8. **記下 App ID 與 App Secret**：在「使用案例 → 自訂 → 設定」可以看到 **Threads App ID** 與 **Threads App Secret**（注意：不是 Facebook App 的那組）。

> App 維持在「開發模式」即可，只有測試人員（你自己）能授權，這正好符合需求。

## 3. 取得長期 Access Token

Threads 的 token 分兩種：短期（1 小時）與長期（60 天）。機器人要用**長期 token**。

在本機 repo 資料夾執行（安裝方式見第 8 節）：

```bash
python -m bot.token_tool login
```

依提示操作：

1. 輸入 Threads App ID 與 Redirect URI（要跟後台設定**一字不差**，包含結尾的 `/`）
2. 打開它印出的網址，按「允許」
3. 瀏覽器會被導向 `https://localhost/?code=XXXX#_`，頁面打不開沒關係，複製 `code=` 後面的值（`#_` 有沒有一起複製都可以）
4. 貼上 code 與 App Secret（輸入時不會顯示）
5. 工具會印出**長期 token** 與建議的**到期日**

> ⚠️ 這個 token 等同你的帳號發文權限：**不要**貼到聊天室、不要存成 repo 裡的檔案、不要 commit。直接貼到下一步的 GitHub Secrets 即可。

（如果你已經用其他方式拿到短期 token，可改用 `python -m bot.token_tool exchange`。）

### 📱 只有手機、沒有電腦的取得方式

全程在手機瀏覽器完成，**不需要安裝任何東西**。建議用 Chrome／Safari 並開啟「要求桌面版網站」，Meta 與 GitHub 的設定頁面在手機版常常顯示不完整。

**A. 取得短期 token（1 小時效期）**

1. 打開 Graph API Explorer：<https://developers.facebook.com/tools/explorer/>
2. 右側選擇你在第 2 節建立的 App
3. 在 Tools／產生 token 的選單中選 **「Generate Threads Access Token」**，用你的 Threads 帳號按「允許」
4. 複製產生的 token（這是短期 token）

> 如果出現「user has not accepted the invite」之類錯誤，代表第 2 節第 7 步的測試人員邀請還沒接受。

**B. 換成長期 token（60 天）**

開一個**無痕分頁**，把下面網址的兩處換成你的值後打開：

```
https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=你的AppSecret&access_token=短期token
```

頁面會顯示類似：

```json
{"access_token":"THAA...很長一串","token_type":"bearer","expires_in":5184000}
```

- `access_token` 那串就是長期 token
- `expires_in` 5184000 秒 = 60 天。到期日 = 今天 + 59 天（保守提早一天），例如今天 11/22 → 填 `2027-01-20`

**C. 收尾**

1. 把長期 token 貼到 GitHub Secret（第 4 節），另外存一份到手機的密碼管理工具（之後續期要用，GitHub Secret 存進去後無法再讀出）
2. 關閉無痕分頁。因為網址中含有 App Secret 與 token，**不要**用一般分頁開，也不要把這個網址傳給任何人

**檢查 token 是否有效**（無痕分頁打開，顯示你的帳號名稱就代表有效）：

```
https://graph.threads.net/v1.0/me?fields=id,username&access_token=你的token
```

## 4. 設定 GitHub Secrets 與 Variables

到 GitHub repo →「Settings」→「Secrets and variables」→「Actions」：

| 類型 | 名稱 | 值 | 用途 |
|---|---|---|---|
| **Secret**（Secrets 分頁） | `THREADS_ACCESS_TOKEN` | 第 3 步拿到的長期 token | 發文用，加密儲存，log 中會被遮蔽 |
| **Variable**（Variables 分頁） | `THREADS_TOKEN_EXPIRES_AT` | 第 3 步印出的日期，如 `2027-01-19` | 提前 10 天開 Issue 提醒續期 |

`GITHUB_TOKEN` 由 GitHub 自動提供，不用設定。

另外確認：「Settings」→「Actions」→「General」→「Workflow permissions」選 **Read and write permissions**（讓 workflow 能 commit `posts.json` 並開 Issue）。如果預設分支有分支保護（禁止直接 push），bot 會無法 commit，需要另外允許 `github-actions[bot]`。

## 5. 啟用排程與第一次執行

- **排程只會在預設分支（通常是 `main`）上執行**，請確認這些檔案已合併到預設分支。
- 排程時間：每天 UTC 00:07 = **台灣 08:07**。GitHub 排程在尖峰時段可能延遲幾分鐘到半小時。
- **第一次建議先 dry-run**：到「Actions」→「Daily Threads Post」→「Run workflow」，勾選 Dry run（預設已勾）→ 執行，在執行紀錄或 Summary 看到今天要發的文章。
- 確認無誤後，可再手動執行一次並**取消勾選** Dry run，實際發一篇測試；之後交給每日排程即可。
- 手動執行時不勾 dry-run 就會真的發文，而且會發下一篇，請注意。

> GitHub 會停用「60 天內 repo 沒有任何活動」的排程。本機器人每天都會 commit，所以正常運作時不會被停用；但如果文章用完、連續 60 天沒發文，排程可能被停用，補完文章後到 Actions 頁面重新啟用即可。

## 6. posts.json 格式

最外層是一個陣列，每篇文章是一個物件：

```json
[
  {
    "id": 1,
    "topic": "Spring Boot",
    "content": "文章內文，可以用 \n 換行",
    "hashtags": ["Java", "SpringBoot", "後端面試"],
    "published": false,
    "published_at": null,
    "threads_post_id": null
  }
]
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | 數字 | 唯一編號，不可重複 |
| `topic` | 字串 | 主題分類，只用於顯示與紀錄 |
| `content` | 字串 | 內文，不可空白 |
| `hashtags` | 字串陣列 | 不用加 `#`，不可含空格。**第一個最重要**（Threads 通常只把一個標籤變成可點擊的主題） |
| `published` | `true`／`false` | 是否已發布，新文章填 `false` |
| `published_at` | 字串或 `null` | 發布時間（台灣時間 ISO 格式），由 bot 自動填 |
| `threads_post_id` | 字串或 `null` | Threads 回傳的貼文 id，由 bot 自動填（選填欄位） |

**實際發出的文字** = `content` + 空行 + `#tag1 #tag2 #tag3`，這整段必須 ≤ 500 字元。長度以保守方式計算：中英文各算 1，emoji 等特殊字元算 2。

**關於 `@`**：Threads 會把 `@文字` 當成標記帳號。為了避免 `@Service`、`@Test` 這類 Java 註解標記到陌生人，發文時會自動把它們換成全形 `＠`（`posts.json` 內容不變，email 不受影響）。若想關閉，把 `bot/posts.py` 的 `ESCAPE_MENTIONS` 改成 `False`。

## 7. 如何新增文章

1. 打開 `posts.json`，在陣列**最後**新增物件（文章按順序發布）
2. `id` 用目前最大值 +1，`published` 填 `false`，`published_at` 與 `threads_post_id` 填 `null`
3. 注意 JSON 語法：物件之間要逗號、最後一個物件後面**不能**有逗號；內文換行寫 `\n`，雙引號寫 `\"`
4. 本機執行檢查：
   ```bash
   python -m pytest tests/test_repo_posts.py   # 格式與長度檢查
   python -m bot.main --dry-run                 # 預覽下一篇
   ```
5. commit 並 push。push 後 GitHub 會自動跑測試，有錯會顯示紅色 ✗
6. 補完後把「📝 posts.json 只剩 N 篇」的 Issue 關掉

> 小技巧：也可以直接在 GitHub 網頁上編輯 `posts.json`，但記得先在本機或看 Tests workflow 確認格式正確。

## 8. 本機測試方法

需要 Python 3.10 以上。

```bash
# 1. 下載專案
git clone https://github.com/<你的帳號>/SocialBot.git
cd SocialBot

# 2. 建立虛擬環境（只需做一次）
python -m venv .venv
source .venv/bin/activate        # Windows：.venv\Scripts\activate

# 3. 安裝套件
pip install -r requirements-dev.txt

# 4. 跑全部測試（不會連網、不會發文）
python -m pytest
python -m pytest -v                       # 顯示每個測試名稱
python -m pytest tests/test_posts.py      # 只跑某個檔案

# 5. 預覽今天要發哪一篇（不需要 token）
python -m bot.main --dry-run
```

**在本機真的發文**（通常不需要，正式發文交給 GitHub Actions）：

```bash
read -s THREADS_ACCESS_TOKEN && export THREADS_ACCESS_TOKEN   # 隱藏輸入，不留在歷史紀錄
python -m bot.main
```

這會真的發文並修改本機的 `posts.json`，記得把變更 commit 回 repo，否則 GitHub Actions 明天會再發同一篇。本機沒有設定 `GITHUB_TOKEN` 時，開 Issue 的步驟會顯示警告後略過，不影響發文。

**檢查 token 是否有效**：`python -m bot.token_tool check`

## 9. 更新長期 Token（約每 50 天一次）

長期 token 效期 60 天，可以免費延長，但**必須在過期前**做（且 token 至少發出 24 小時）。到期前 10 天，bot 會開一張「🔑 Threads token 將在 N 天後到期」的 Issue。收到後：

1. 本機執行 `python -m bot.token_tool refresh`，貼上目前的 token（可從你的密碼管理工具取得；GitHub Secret 存進去後無法再讀出，所以建議自己另外安全保存一份）
2. 把印出的**新 token** 更新到 Secret `THREADS_ACCESS_TOKEN`
3. 把印出的**新日期**更新到 Variable `THREADS_TOKEN_EXPIRES_AT`
4. 關閉提醒 Issue

**📱 只用手機續期**：在無痕分頁打開以下網址（換成目前的長期 token），把回傳的新 `access_token` 與新到期日（今天 + 59 天）照上面第 2、3 步更新：

```
https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=目前的長期token
```

**如果已經過期了**：refresh 會失敗，請重做第 3 節（電腦用 `login`，手機用「只有手機」的 A、B 步驟）取得新 token，再更新 Secret 與 Variable。之後可以手動執行 workflow 補發今天的文章。

## 10. 常見錯誤排解

| 錯誤訊息 | 原因與處理 |
|---|---|
| `找不到 THREADS_ACCESS_TOKEN：GitHub Secret 沒有設定或名稱拼錯` | Secret 要建在**這個 repo** 的 Settings → Secrets and variables → Actions → **Secrets** 分頁 →「Repository secrets」，名稱完全一致。不是 Variables、不是 Environment secrets |
| `Threads access token 已過期或無效` | token 過期、被撤銷，或你改了密碼。依第 9 節處理（過期則重做第 3 節） |
| `權限不足，請確認 App 已取得 threads_basic 與 threads_content_publish 權限` | 第 2 節第 4 步的權限沒加，或取得 token 時沒勾選；加好後重做第 3 節 |
| `已達 Threads API 呼叫上限` | 短時間呼叫太多次（Threads 每 24 小時最多 250 篇），稍後再試 |
| `文章 id=N 長度 X 超過上限 500，已跳過` | 縮短該篇內文或減少 hashtag；修正前 bot 會先發後面的文章 |
| `THREADS_TOKEN_EXPIRES_AT 格式錯誤` | Variable 要寫成 `YYYY-MM-DD`，例如 `2027-01-19` |
| `無法建立提醒 Issue` | 檢查第 4 節的 Workflow permissions 是否為 Read and write |
| `無法 push posts.json` | 預設分支有保護規則；**請手動把該篇改成 `published: true`**，避免隔天重複發文 |
| `posts.json 不是合法的 JSON（第 N 行）` | 該行附近多了或少了逗號、引號，可貼到 JSON 檢查工具找錯 |
