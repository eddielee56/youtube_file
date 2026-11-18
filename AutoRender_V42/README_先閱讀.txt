AutoRender V4.2 — Gemini 潤稿 + Azure 曉臻內部試播

放置方式：YouTubeAI\AutoRender_V42，與 AutoRender_V39、AutoRender_V21 同一層。

本版只處理經 V3.9 人工核准的優惠 JSON。source_verified、approved_for_preview 必須 true，publication_approved 必須 false；官方查核日期不得超過兩天，過期優惠拒絕製作。

一、自動測試（不連網、不耗 API）：
  py -3.12 autorender_v42.py selftest

二、產生 Gemini 改善後的六段旁白與分鏡（需要你的 Gemini Key）：
  py -3.12 autorender_v42.py draft --mode gemini --model gemini-3.5-flash --input "..\AutoRender_V39\approved_for_preview\accor_cathay_APPROVED_PREVIEW_ONLY.json"

若只要先檢查串接，不呼叫 Gemini：
  py -3.12 autorender_v42.py draft --mode offline --input "..\AutoRender_V39\approved_for_preview\accor_cathay_APPROVED_PREVIEW_ONLY.json"

三、請先讀 output\accor_cathay_preview_2026\narration_draft.txt，確認語氣和事實。

四、製作內部曉臻有聲 Shorts（需要 Azure Speech Key；不會上傳）：
  py -3.12 autorender_v42.py preview --input "..\AutoRender_V39\approved_for_preview\accor_cathay_APPROVED_PREVIEW_ONLY.json"

影片會儲存在 AutoRender_V21\output\DEMO_v42_accor_cathay_preview_2026。

安全限制：沒有 API Key 自動持久化；Gemini 只撰寫過場，不生成優惠事實；經審核 JSON 原文用作資訊卡與旁白事實；任何草稿及最終影片都保留「內部試播／未核准發布」。不會啟動 Windows 排程、發 Gmail、上傳 YouTube。

使用者已自行修改的 V4.1 不會覆蓋。本套件不會自己讀取官網，也不能取代人工確認適用條款。

依賴：AutoRender_V21 的 autorender_v21_preview.py、Python Pillow / Azure Speech SDK、FFmpeg。
