AutoRender V4.3 — 每週已審核優惠自動產生「內部試播」

1. 保留 AutoRender_V38、AutoRender_V39、AutoRender_V42、AutoRender_V21 原有資料夾。
2. 解壓 AutoRender_V43 至 YouTubeAI 根目錄，與上述資料夾同層。
3. 在 AutoRender_V43 開 PowerShell，先執行：
   py -3.12 autorender_v43.py selftest
   py -3.12 autorender_v43.py status
   py -3.12 autorender_v43.py dry-run
4. 測試成功且準備好無人值守 API 呼叫後，執行：
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_secrets.ps1
   依序在 Windows 輸入 Gemini API Key 與 Azure Speech API Key（輸入不顯示）。
   金鑰由 Windows DPAPI 加密，寫入 %LOCALAPPDATA%\AutoRenderV43，避免在 OneDrive 放置憑證。
5. 安裝獨立排程（不會改動 V3.8）：
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_schedule.ps1
   每週五台灣時間 18:15 執行；需要目前的 Windows 使用者已登入、電腦未關機。
6. 檢查：
   Get-ScheduledTask -TaskName AutoRender_V43_WeeklyPreview
   Get-ScheduledTaskInfo -TaskName AutoRender_V43_WeeklyPreview
   檢查 output\last_weekly_render.json 以及 logs\ 的最新日誌。

重要工作規則：
- V3.8 每週五 18:00 選題是一篇「新聞線索」，不是獲核准的優惠。
- V4.3 僅會挑選 event_key 與當週選題一致、通過 V3.9 人工審核閘門且查核日期未過期的單一 JSON。
- 若缺少核准，V4.3 會輸出 WAITING_REVIEW，不會製作影片、也不會寄送通知。
- 已完成同一 event_key 的試播，V4.3 不會自動重做。
- 出錯重試上限為三次；人工檢查後可用 retry --event-key "原始事件鍵" 重設。
- 所有影片僅供內部試播，沒有任何 YouTube 上傳功能；正式發布必須另外由你核准。
- V4.2 的實際文字生成採用 Gemini；事實用人工審核 JSON 鎖定，但仍需人工閱讀草稿和成片。
- 排程執行不會詢問金鑰；需要 Windows 同一使用者登入，才能解開 DPAPI 金鑰。
- 注意：使用 Gemini/Azure API 可能產生費用；請自行在服務商後台設定預算與配額。
- 只有自己信任、經過檢查的程式才應使用解除執行政策的 PowerShell 指令。
- 本套件沒有修改你原有的任何版本檔案，不會自動啟用排程。


2026-11-19 審核與通知更新

雙擊 open_review.cmd，會啟動本機審核服務並開啟瀏覽器。服務僅接受 127.0.0.1 連線。
頁面提供影片播放、旁白、官方來源、查核日期、期限及審閱紀錄。
通過與退回都綁定該支 MP4 的 SHA256，退回時須填寫原因。
既有的 APPROVED 狀態會保留，原有登錄時間顯示於頁面中。
關閉命令視窗或按 Ctrl+C 可停止服務。

每週製片會更新 output/review_queue.json，並透過 V3.8 已啟用的 Gmail 設定寄給自己。
完成、失敗、檔案異常與等待優惠資料審核都有通知紀錄。
重複執行同一個完成結果會使用同一則通知紀錄。
SMTP 寄送失敗時，通知保留為 FAILED，避免不確定是否送達時自動重複寄送。
output/last_notification.json 顯示寄送結果，失敗不會抹除已完成的製片狀態。

在 AutoRender_V43 目錄執行

py -3.12 autorender_v43.py review-queue
py -3.12 autorender_v43.py review
py -3.12 autorender_v43.py notify --dry-run
py -3.12 autorender_v43.py notify

需要以命令列記錄審核時，使用 review-preview 並填入 review_queue.json 中的 event_key 和 SHA256

py -3.12 autorender_v43.py review-preview --event-key "事件鍵" --sha256 "影片雜湊" --decision approve
py -3.12 autorender_v43.py review-preview --event-key "事件鍵" --sha256 "影片雜湊" --decision reject --note "修改原因"

退回後先修正素材與核准資料，再用 retry --event-key "事件鍵" 開放下一次製片。
若修正版由 V4.2 另外產生，使用 adopt-preview --receipt "修正版收據路徑" --replace。
新版本會重新進入 PENDING，原版本的審核歷史仍會保留。
已通過的成片仍受到重複製片保護。

確認失敗通知確實未送達後，可執行 notify --retry-failed。
若狀態停在 SENDING，請先核對 Gmail 寄件備份，再處理該筆寄送紀錄。
審閱通過會記錄內容審核結果，正式發布仍依 publication_approved 欄位管理。

回歸測試

py -3.12 -B -m unittest discover -s . -p "test_*.py"
