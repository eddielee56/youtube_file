"""Check that adding a music bed preserves narration gain and keeps music quiet."""
import array
import math
import shutil
import subprocess
import unittest

import autorender_v21_preview as renderer


@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg is required')
class MusicMix(unittest.TestCase):
    def test_voice_gain_is_preserved_and_music_is_audible_but_quiet(self):
        filters=renderer.music_mix_filters(1.5,{'gain_db':-24,'fade_in_s':0.1,'fade_out_s':0.1})
        filters=[part.replace('[1:a]','[0:a]').replace('[2:a]','[1:a]') for part in filters]
        result=subprocess.run([
            'ffmpeg','-hide_banner','-loglevel','error',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1.5',
            '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=1.5',
            '-filter_complex',';'.join(filters),'-map','[a]','-t','1.5',
            '-f','f32le','pipe:1'],capture_output=True,check=True,timeout=15)
        values=array.array('f')
        values.frombytes(result.stdout)
        samples=values[::2][12000:-12000]
        def amplitude(frequency):
            cosine=sum(value*math.cos(2*math.pi*frequency*index/48000) for index,value in enumerate(samples))
            sine=sum(value*math.sin(2*math.pi*frequency*index/48000) for index,value in enumerate(samples))
            return 2*math.hypot(cosine,sine)/len(samples)
        voice=amplitude(440)
        music=amplitude(220)
        self.assertAlmostEqual(voice,0.125,delta=0.002)
        self.assertGreater(music,0.00001)
        self.assertLess(music,voice/10)
        self.assertLess(max(abs(value) for value in values),0.95)


if __name__=='__main__':
    unittest.main()
