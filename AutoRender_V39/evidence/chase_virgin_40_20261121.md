# Chase → Virgin Atlantic 40% 人工查核紀錄

2026-11-21：使用者確認已查核並授權試播，未授權發布。

source_url 與三項 evidence 統一使用 Chase 官方 Ultimate Rewards 登入入口：
https://www.chase.com/personal/credit-cards/ultimate-rewards

此網址為登入入口，並非本次促銷條款的公開深層連結。促銷事實依據使用者提供的人工查核。兩段 Chase 英文條款由使用者提供，來源為 LoyaltyLobby 全文引用；中文內容為查核摘要而非逐字引文。Codex 未登入 Chase，也未獨立查閱登入後促銷條款。

Virgin 官方公開頁列一般1:1、最低1,000點、1,000點單位及轉點不可逆；擷取內容未列40%與促銷期間，故不將本次促銷引文歸到該頁：
https://www.virginatlantic.com/en-US/flying-club/earn-points/chase-ultimate-rewards

V3.9 validator 實測接受上述兩個網址；只檢查 HTTPS 格式及三項 evidence URL 與 source_url 相同，不會驗證網頁內容或登入。

週報保留2026-11-20 18:00原始 V3.8 輸出及 EDITORIAL_REVIEW_ONLY 狀態；本次人工確認另存於 approved_for_preview JSON。

18:00來源：V3.8 install_schedule_fixed.ps1 的 AutoRender_V38_Weekly（週五），只產生選題週報。V4.3 install_schedule.ps1 的 AutoRender_V43_WeeklyPreview 於週五18:15讀週報製片。18:00應保留，是必要上游流程。6ddf517 已統一執行資料路徑。2026-11-20 18:00日誌確認產生週報。此環境無法存取 Windows 排程服務，未重新驗證所有已安裝觸發器，亦未變更排程。
