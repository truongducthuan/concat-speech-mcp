import unittest

from concat_speech_mcp.segmentation import (
    group_tokens_by_span,
    parse_silences,
    speech_spans,
    tokens_from_whisper_json,
)


class WhisperTokensTest(unittest.TestCase):
    def test_tokens_prefer_dtw_time_and_drop_special_tokens(self):
        # Arrange
        data = {"transcription": [{"tokens": [
            {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}, "t_dtw": -1},
            {"text": "皆さん", "offsets": {"from": 0, "to": 540}, "t_dtw": 32},
            {"text": "京都", "offsets": {"from": 600, "to": 900}},
            {"text": " ", "offsets": {"from": 900, "to": 950}},
        ]}]}

        # Act
        tokens = tokens_from_whisper_json(data)

        # Assert
        self.assertEqual(tokens, [(320, 320, "皆さん"), (600, 900, "京都")])


class SilenceTest(unittest.TestCase):
    def test_parse_silences_pairs_lines_and_clamps_negative_start(self):
        log = "silence_start: -0.01\nsilence_end: 0.5\nsilence_start: 2.0\nsilence_end: 2.6"

        self.assertEqual(parse_silences(log), [(0.0, 0.5), (2.0, 2.6)])

    def test_parse_silences_unclosed_start_runs_to_infinity(self):
        self.assertEqual(parse_silences("silence_start: 9.0"), [(9.0, float("inf"))])

    def test_speech_spans_trailing_open_silence_ends_at_total(self):
        self.assertEqual(speech_spans([(0.0, 0.5), (4.0, float("inf"))], total=10.0), [(0.5, 4.0)])


class GroupingTest(unittest.TestCase):
    SPANS = [(0.0, 1.5), (2.1, 4.0)]

    def test_group_contiguous_offsets_still_split_on_audio_pauses(self):
        # Regression (PoC): back-to-back whisper offsets once merged a whole talk into one line.
        tokens = [(0, 500, "皆さん"), (500, 1400, "こんにちは"), (1400, 2600, "今日は"), (2600, 3800, "京都")]

        utterances = group_tokens_by_span(tokens, self.SPANS, drop_spaces=True)

        self.assertEqual([u["text"] for u in utterances], ["皆さんこんにちは", "今日は京都"])

    def test_group_vietnamese_keeps_word_spaces(self):
        # Arrange: whisper puts the space at the start of each word token
        tokens = [(100, 300, " Xin"), (300, 600, " chào"), (2200, 2500, " Kyoto")]

        # Act
        utterances = group_tokens_by_span(tokens, self.SPANS)

        # Assert
        self.assertEqual([u["text"] for u in utterances], ["Xin chào", "Kyoto"])

    def test_group_japanese_drops_whisper_spaces(self):
        utterances = group_tokens_by_span([(100, 200, "京都"), (200, 300, " を")], self.SPANS, drop_spaces=True)

        self.assertEqual(utterances[0]["text"], "京都を")

    def test_group_no_spans_returns_empty(self):
        self.assertEqual(group_tokens_by_span([(0, 1, "a")], []), [])


if __name__ == "__main__":
    unittest.main()
