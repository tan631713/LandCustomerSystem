# 自架 PostgreSQL／API／iPhone 正式版

本系統不使用付費雲端資料庫。PostgreSQL、FastAPI、附件與備份都放在自己的 Windows 電腦；Windows 桌面程式與 iPhone 行動版共用同一份 PostgreSQL。

```text
Windows 桌面程式 ─┐
                  ├─ FastAPI ─ PostgreSQL
iPhone 行動版 ────┘              ├─ 附件
                                  └─ 壓縮備份
```

正式部署時，圖中的 Windows 桌面程式可以位於公司筆電；FastAPI 與 PostgreSQL 固定在家中主機，兩者透過 NetBird HTTPS 連線。公司筆電不直接連 5432。

## 正式資料原則

- PostgreSQL 是唯一共用的正式資料來源。
- 舊 `customers.db` 只保留為歷史安全備份與裝置偏好，不參與手機同步。
- iPhone 不直接連 PostgreSQL，只能透過 HTTPS FastAPI。
- PostgreSQL 5432 僅供本機使用，不可開放到區網或網際網路。

## Windows 桌面版

執行：

```text
start_land_customer_system_postgresql.bat
```

啟動器會先檢查 PostgreSQL、檢查最近 24 小時備份、啟動本機 API，再開啟標題含「PostgreSQL 正式版」的桌面程式。登入使用 API／PostgreSQL 帳號，不再驗證舊 SQLite 帳號。

公司筆電請改用獨立 CompanyLaptopClient ZIP 內的：

```text
start_company_laptop_desktop.bat
```

公司啟動器只執行桌面 EXE，透過 `https://家中NetBird-IP:8732` 連線；不含或啟動 PostgreSQL／LandCustomerServer。裝置本機只建立 `desktop-client-settings.db` 保存欄寬、字體等偏好，不建立本機地主資料表。

## iPhone 第一次設定

完整步驟請看 `iPhone連線說明.txt`：

1. 以系統管理員身分執行 `allow_private_network_firewall.bat`。
2. 執行 `install_iphone_certificate.bat`。
3. iPhone Safari 開啟畫面顯示的 `http://192.168.x.x:8733/`。
4. 下載、安裝公開 CA 憑證，並在「憑證信任設定」開啟完整信任。
5. 回到電腦按 `Ctrl+C` 關閉臨時憑證下載服務。

憑證下載服務只提供公開 `.cer`；不會提供資料庫、附件、PostgreSQL 帳密或伺服器私鑰。

## iPhone 每次使用

執行：

```text
start_mobile_server_https.bat
```

視窗會顯示：

```text
https://192.168.x.x:8732/mobile/
```

手機瀏覽器必須輸入完整網址，包含 `https://`、`:8732` 與 `/mobile/`；只輸入 IP 會連到錯誤的 HTTP 連接埠。

切換到手機熱點後，Windows 常把該連線歸類為「公用網路」。新版防火牆輔助檔會同時支援私人／公用設定檔，但只接受目前本機子網路來源，不會把服務開放給整個網際網路。若畫面列出多個 IP，請選擇與手機目前所在網路相同的網址；每次切換網路都應關閉並重開啟動器，讓 HTTPS 憑證包含新的 IP。

部分 iPhone 系統版本可能隔離「熱點提供者」與連入熱點的裝置。若同一支 iPhone 開熱點給筆電後無法反向連回筆電，請讓兩台裝置改連同一台 Wi-Fi，或由 Windows 建立行動熱點再讓 iPhone 連入。

用 iPhone Safari 開啟、登入，然後可用「分享 → 加入主畫面」。已完成的行動功能：

- 首頁持分／地主／土地／待追蹤統計
- 姓名、身分證、地址搜尋地主
- 地區、地段、地號、地主搜尋土地
- 持分明細、坪數、公告現值與持分現值
- 新增聯絡／拜訪紀錄
- 設定與更新下次追蹤
- 管理員、編輯者、唯讀者角色限制

登入 token 只放在目前 Safari／主畫面 App 工作階段。行動版不快取 API 回應或敏感地主資料。

## 備份

正式 API 與手機啟動器會先執行：

```powershell
python backup_postgresql.py --label auto --if-due-hours 24
```

手動備份執行：

```text
backup_postgresql_now.bat
```

預設位置：

```text
%LOCALAPPDATA%\LandCustomerSystem\postgres-backups
```

每份 ZIP 包含：

- `database.dump`：PostgreSQL custom 格式
- `manifest.json`：schema、筆數、雜湊、附件統計
- `attachments/`：納管附件（若有）

建立時會以 `pg_restore --list` 驗證 dump，再檢查 ZIP。預設保留 90 天、最多 30 份，永遠至少保留最新 3 份。

## 開發檢查

```powershell
python start_api_server.py --postgres --check
python start_api_server.py --postgres
```

本機 API 文件：`http://127.0.0.1:8732/docs`

主要端點：

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET／POST／PUT／DELETE /api/v1/records`
- `GET /api/v1/owners`
- `GET /api/v1/lands`
- `GET／POST /api/v1/records/{id}/contact-logs`
- `GET／PUT／DELETE /api/v1/records/{id}/follow-up`
- `GET /api/v1/follow-ups`
- 案件、標籤、附件及 Excel 批量匯入端點

## 外出連線

本版本已接入 NetBird 私人 VPN：

1. 家中主機只需執行 `start_home_server_vpn.bat`；啟動器會檢查並在必要時引導修復 NetBird、PostgreSQL 服務、私人 VPN 防火牆、資料庫連線、HTTPS 與備份。
2. 首次設定依畫面完成 NetBird 登入、Windows 管理員授權與 PostgreSQL 管理員密碼輸入。
3. iPhone 安裝官方 NetBird App，使用同一帳號登入並 Connect。
4. Safari 開啟畫面顯示的 `https://100.x.x.x:8732/mobile/`。

NetBird 防火牆規則只允許該帳號的私人 `/16` 網段連入 8732／8733。不要在路由器轉發 5432、8732 或 8733；PostgreSQL 5432 仍只監聽 `127.0.0.1` 與 `::1`。電腦關機、休眠、斷網、NetBird 中斷或 API 關閉時，手機會暫時無法使用。完整步驟見 `私人VPN連線說明.txt`。
