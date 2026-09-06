from __future__ import annotations

import unittest

from nn_davinci.formula import FORMULA_SYNTAX_VERSION, normalize_formula


class FormulaNormalizationTests(unittest.TestCase):
    def test_greek_scripts_operators_fraction_and_root_stay_editable(self) -> None:
        result = normalize_formula(r"\alpha_i^2 + \beta \leq \sqrt{x} + \frac{1}{N}")
        self.assertTrue(result.valid)
        self.assertFalse(result.fallback)
        self.assertEqual(FORMULA_SYNTAX_VERSION, result.syntax_version)
        self.assertIn("αᵢ²", result.text)
        self.assertIn("β ≤ √(x)", result.text)
        self.assertIn("(1)/(N)", result.text)
        self.assertEqual({"fraction", "greek", "operator", "root", "subscript", "superscript"}, set(result.features))

    def test_simple_matrix_is_multiline_editable_text(self) -> None:
        result = normalize_formula(r"A = \begin{bmatrix}a & b \\ c & \delta\end{bmatrix}")
        self.assertTrue(result.valid)
        self.assertEqual(2, len(result.lines))
        self.assertIn("[a b]", result.lines[0])
        self.assertIn("[c δ]", result.lines[1])
        self.assertIn("matrix", result.features)

    def test_common_attention_and_convolution_expressions_fit_safe_subset(self) -> None:
        attention = normalize_formula(
            r"S = QK^T / \sqrt{d_k},\quad A = \mathrm{softmax}(S)V"
        )
        convolution = normalize_formula(
            r"y_{i,j} = \sum_{m,n} x_{i+m,j+n} \times k_{m,n}"
        )
        self.assertTrue(attention.valid)
        self.assertIn("QKᵀ / √(dₖ)", attention.text)
        self.assertIn("softmax(S)V", attention.text)
        self.assertTrue(convolution.valid)
        self.assertIn("∑", convolution.text)
        self.assertIn("×", convolution.text)
        self.assertIn("y", convolution.text)

    def test_invalid_formula_is_visible_and_never_executed_or_dropped(self) -> None:
        for source in (r"\input{/etc/passwd}", r"x_{", "", r"\frac{a}{b_{c}}"):
            with self.subTest(source=source):
                result = normalize_formula(source)
                self.assertFalse(result.valid)
                self.assertTrue(result.fallback)
                self.assertIn("Invalid formula:", result.text)
                self.assertIn(source, result.source)
                self.assertTrue(result.error)


if __name__ == "__main__":
    unittest.main()
