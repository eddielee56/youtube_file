"""Subtitle revision regressions, without speech or network calls."""
from pathlib import Path
import tempfile
import unittest

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


if __name__=='__main__':
    unittest.main()
