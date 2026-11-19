AutoRender V4.3 與 Muse 審核流程

Muse 審核頁為唯一審核入口。
審核資料存於 Git repo 的 reviews 目錄。Windows 不接受檔名中的 |，請用 %7C 編碼，JSON 內 event_key 保持原值。
本地審核頁已停用。Gmail 通知已關閉。舊本地審閱通過紀錄已失效。

每筆 review JSON 包含
event_key、title、program、video、facts、evidence、checks、status、decision、publication_approved。
video 綁定 repo_path、raw_url、duration_s、width、height、version、commit_sha。
由 AutoRender 建立的 version 使用 sha256 加上影片內容雜湊，raw_url 固定到影片所在的 Git commit。
checks 的 fact、originality、copyright、sensitive、quality 各有 status 和 note。
status 可為 pending、approved、returned。checks.status 可為 pass、fail、pending。
publication_approved 明確記錄發布核准。

製片採用 V3.8 選題與 V3.9 優惠事實核准，透過 V4.2 產生內部試播。
製作完成與 Muse 的審核狀態分別記錄。成片的審核狀態每次都讀取 repo 的 review JSON。
本機 SQLite 僅保留製片進度、影片位置、雜湊及交接事件。
每週執行仍由 run_v43.ps1 啟動，Gemini 暫時錯誤採有限次數等待重試。

本機已部署的 YouTubeAI 可用 runtime_config.json 的 review_repository 指向 youtube_file Git checkout。
也可設定 AUTORENDER_REVIEW_REPO。
直接從 Git checkout 執行時，預設使用該 repo。

驗證 repo 審核資料

py -3.12 autorender_v43.py validate-reviews
py -3.12 autorender_v43.py review-queue

影片已提交到 Git 後，可建立待審核紀錄

py -3.12 autorender_v43.py prepare-review --offer "優惠JSON路徑" --video "MP4路徑" --repo-path "影片在repo中的相對路徑" --commit-sha "影片所在的完整commit SHA"

Muse 決定可直接寫入 reviews，或透過完整 JSON 匯入

py -3.12 autorender_v43.py import-muse-review --file "Muse決定JSON路徑" --expected-version "Muse頁面審核時的影片version"

同一版本與相同事實重新 prepare-review 會保留 Muse 決定。
新版影片會重新進入 pending。匯入時若影片版本已改變，需先重新整理 Muse 頁面。
退回後修正素材與優惠資料，再用 retry --event-key "事件鍵" 開放下一次製片。
另由 V4.2 產生的修正版可用 adopt-preview --receipt "修正版收據路徑" --replace 登錄。

完成與失敗事件輸出至 output/muse_events.json，並以 MUSE_EVENT JSON 行輸出到執行日誌，交由 Muse 在對話裡發通知。
PENDING_MUSE 表示待 Muse 接手，並非對話通知已送達。
本程式不包含 Muse 頁面的實作，Muse 端由使用者管理。

回歸測試

py -3.12 -B -m unittest discover -s . -p "test_*.py"
