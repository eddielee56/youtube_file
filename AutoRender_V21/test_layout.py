"""Subtitle revision regressions, without speech or network calls."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw

import autorender_v21_preview as renderer


class SubtitleLayout(unittest.TestCase):
    def test_two_line_captions_use_the_reserved_band(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            renderer.ass_subs([{'start':1.2,'end':3.4,'text':'測試字幕長度超過十六個中文字就必須自動分成兩行'}],root)
            text=(root/'captions.ass').read_text(encoding='utf-8-sig')
            self.assertIn(renderer.CAPTION_STYLE,text)
            self.assertIn('1,2,38,38,94,1',text)
            self.assertIn('\\N',text)
            self.assertIn('0:00:01.20,0:00:03.40',text)

    def test_restyle_preserves_all_dialogue_text_and_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            renderer.ass_subs([{'start':0.25,'end':2.5,'text':'原有字幕內容保持一致'}],root)
            original=(root/'captions.ass').read_text(encoding='utf-8-sig')
            original=original.replace(',38,38,94,1',',38,38,140,1')
            (root/'old.ass').write_text(original,encoding='utf-8')
            renderer.restyle_captions(root/'old.ass',root/'new.ass')
            revised=(root/'new.ass').read_text(encoding='utf-8-sig')
            old_lines=[line for line in original.splitlines() if line.startswith('Dialogue:')]
            new_lines=[line for line in revised.splitlines() if line.startswith('Dialogue:')]
            self.assertEqual(old_lines,new_lines)
            self.assertIn(renderer.CAPTION_STYLE,revised)

    def test_duplicate_or_missing_style_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'missing.ass').write_text('[Events]',encoding='utf-8')
            with self.assertRaises(ValueError):
                renderer.restyle_captions(root/'missing.ass',root/'new.ass')
            (root/'duplicate.ass').write_text(renderer.CAPTION_STYLE+'\n'+renderer.CAPTION_STYLE,encoding='utf-8')
            with self.assertRaises(ValueError):
                renderer.restyle_captions(root/'duplicate.ass',root/'new.ass')

    def test_reward_points_stays_on_one_line(self):
        text='合格住宿額外獲得50% Reward Points。'
        wrapped=renderer.wrap_caption(text)
        self.assertIn('Reward Points',wrapped)
        self.assertNotIn('Rewa\\Nrd',wrapped)
        self.assertNotIn('\\N。',wrapped)
        self.assertLessEqual(len(wrapped.split('\\N')),2)
        draw=ImageDraw.Draw(Image.new('RGB',(1,1)))
        for line in wrapped.split('\\N'):
            self.assertLessEqual(draw.textlength(line,font=renderer.font(26,True)),448)

    def test_new_voice_cues_preserve_words_and_original_offsets(self):
        text='這段中文用來檢查字幕分段仍會完整保留英文Reward Points並依時間顯示。'
        fragments=list(renderer.caption_fragments(text))
        self.assertEqual(''.join(fragment for _,fragment in fragments),text)
        self.assertTrue(any('Reward Points' in fragment for _,fragment in fragments))
        for offset,fragment in fragments:
            self.assertEqual(text[offset:offset+len(fragment)],fragment)

    def test_existing_broken_word_is_repaired_without_retiming(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            renderer.ass_subs([{'start':1.2,'end':3.4,'text':'合格住宿額外獲得50% Reward Points。'}],root)
            text=(root/'captions.ass').read_text(encoding='utf-8-sig')
            prefix=next(line for line in text.splitlines() if line.startswith('Dialogue:')).split(',',9)[:9]
            old=','.join(prefix)+',合格住宿額外獲得50% Rewa\\Nrd Points。'
            lines=[old if line.startswith('Dialogue:') else line for line in text.splitlines()]
            (root/'old.ass').write_text('\n'.join(lines),encoding='utf-8')
            renderer.restyle_captions(root/'old.ass',root/'new.ass')
            revised=(root/'new.ass').read_text(encoding='utf-8-sig')
            dialogue=next(line for line in revised.splitlines() if line.startswith('Dialogue:'))
            self.assertEqual(dialogue.split(',',9)[:9],prefix)
            self.assertIn('Reward Points',dialogue)

    def test_scene_three_and_five_details_fit_above_preview_notice(self):
        draw=ImageDraw.Draw(Image.new('RGB',(540,960)))
        for heading,detail in (
            ('參加條件','入住前設定 Asia Miles 自動轉換；需合格訂房，至少住一晚。'),
            ('注意事項','每位會員最多三次；第三方訂房平台不適用。'),
        ):
            with self.subTest(heading=heading):
                layout=renderer.card_text_layout(draw,heading,detail)
                self.assertEqual(''.join(layout[3]),detail)
                self.assertLessEqual(layout[6]+len(layout[3])*layout[5],636)
                if heading=='注意事項':
                    self.assertIn('第三方訂房平台不適用。',layout[3])


if __name__=='__main__':
    unittest.main()
