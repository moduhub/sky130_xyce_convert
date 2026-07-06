import unittest

from converter.joiner import join_continuations, split_for_output


class JoinContinuationsTest(unittest.TestCase):
    def test_plain_continuation(self):
        lines = [".model foo nmos", "+ level = 54", "+ vth0 = 0.4"]
        logical = join_continuations(lines)
        self.assertEqual(len(logical), 1)
        self.assertEqual(logical[0].text, ".model foo nmos level = 54 vth0 = 0.4")

    def test_comment_inside_continuation_block_does_not_swallow_params(self):
        # Regressao: sky130 intercala "* Model Flag Parameters" no meio de
        # blocos .model de varias linhas. O comentario NAO pode virar o
        # inicio de uma nova linha logica que absorve as continuacoes "+"
        # seguintes -- isso apagava lmin/lmax/wmin/wmax/level/... (o
        # .model inteiro ficava sem parametros eletricos, causando "no
        # valid model card found" no Xyce).
        lines = [
            ".model sky130_fd_pr__nfet_01v8__model.13 nmos",
            "* Model Flag Parameters",
            "+ lmin = 1.5e-07 lmax = 1.8e-07 wmin = 1.0e-06 wmax = 1.26e-6",
            "+ level = 54.0",
            "* Process Parameters",
            "+ toxe = 4.148e-09",
        ]
        logical = join_continuations(lines)

        model_lines = [ll for ll in logical if not ll.text.strip().startswith("*")]
        comment_lines = [ll for ll in logical if ll.text.strip().startswith("*")]

        self.assertEqual(len(model_lines), 1)
        self.assertIn("lmin = 1.5e-07", model_lines[0].text)
        self.assertIn("level = 54.0", model_lines[0].text)
        self.assertIn("toxe = 4.148e-09", model_lines[0].text)
        self.assertEqual(
            [c.text for c in comment_lines],
            ["* Model Flag Parameters", "* Process Parameters"],
        )

    def test_split_for_output_roundtrip_short_line(self):
        self.assertEqual(split_for_output("short line"), ["short line"])


if __name__ == "__main__":
    unittest.main()
