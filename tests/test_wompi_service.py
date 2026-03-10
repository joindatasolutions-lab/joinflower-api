import hashlib
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.services.wompi_service import (
    WOMPI_CHECKOUT_BASE_URL,
    WOMPI_CURRENCY,
    build_checkout_url,
    calculate_amount_in_cents,
    generate_integrity_signature,
    generate_reference,
    map_wompi_status,
)


class WompiServiceTests(unittest.TestCase):
    def test_generate_reference_contains_pedido_id(self) -> None:
        reference = generate_reference(31)
        self.assertTrue(reference.startswith("pedido_31_"))

    def test_calculate_amount_in_cents_rounds_half_up(self) -> None:
        self.assertEqual(calculate_amount_in_cents(20000), 2000000)
        self.assertEqual(calculate_amount_in_cents(123.455), 12346)

    @patch.dict(
        os.environ,
        {
            "WOMPI_PUBLIC_KEY": "pub_test_key",
            "WOMPI_INTEGRITY_SECRET": "secret_test",
            "WOMPI_REDIRECT_URL": "https://miapp.com/pago/resultado",
        },
        clear=False,
    )
    def test_build_checkout_url_contains_all_required_params(self) -> None:
        reference = "pedido_31_1712345678"
        amount_in_cents = 2000000
        email = "cliente@test.com"

        expected_signature = hashlib.sha256(
            f"{reference}{amount_in_cents}{WOMPI_CURRENCY}secret_test".encode("utf-8")
        ).hexdigest()

        signature = generate_integrity_signature(reference, amount_in_cents)
        self.assertEqual(signature, expected_signature)

        checkout_url = build_checkout_url(reference, amount_in_cents, email)

        parsed = urlparse(checkout_url)
        params = parse_qs(parsed.query)

        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", WOMPI_CHECKOUT_BASE_URL)
        self.assertEqual(params.get("public-key", [None])[0], "pub_test_key")
        self.assertEqual(params.get("currency", [None])[0], WOMPI_CURRENCY)
        self.assertEqual(params.get("amount-in-cents", [None])[0], str(amount_in_cents))
        self.assertEqual(params.get("reference", [None])[0], reference)
        self.assertEqual(params.get("signature:integrity", [None])[0], expected_signature)
        self.assertEqual(
            params.get("redirect-url", [None])[0],
            "https://miapp.com/pago/resultado",
        )
        self.assertEqual(params.get("customer-data:email", [None])[0], email)

    @patch.dict(
        os.environ,
        {
            "WOMPI_PUBLIC_KEY": "pub_test_key",
            "WOMPI_INTEGRITY_SECRET": "secret_test",
            "WOMPI_REDIRECT_URL": "",
        },
        clear=False,
    )
    def test_build_checkout_url_does_not_include_redirect_when_env_is_empty(self) -> None:
        checkout_url = build_checkout_url("pedido_31_1712345678", 2000000, "cliente@test.com")
        parsed = urlparse(checkout_url)
        params = parse_qs(parsed.query)

        self.assertNotIn("redirect-url", params)

    @patch.dict(
        os.environ,
        {
            "WOMPI_PUBLIC_KEY": "pub_test_key",
            "WOMPI_INTEGRITY_SECRET": "secret_test",
            "WOMPI_REDIRECT_URL": "http://127.0.0.1:5500/pago-resultado.html",
        },
        clear=False,
    )
    def test_build_checkout_url_rejects_non_https_or_localhost_redirect_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "WOMPI_REDIRECT_URL must use HTTPS"):
            build_checkout_url("pedido_31_1712345678", 2000000, "cliente@test.com")

    @patch.dict(
        os.environ,
        {
            "WOMPI_PUBLIC_KEY": "pub_test_key",
            "WOMPI_INTEGRITY_SECRET": "secret_test",
            "WOMPI_REDIRECT_URL": "https://localhost/pago-resultado.html",
        },
        clear=False,
    )
    def test_build_checkout_url_rejects_localhost_redirect_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "WOMPI_REDIRECT_URL cannot point to localhost"):
            build_checkout_url("pedido_31_1712345678", 2000000, "cliente@test.com")

    @patch.dict(
        os.environ,
        {
            "WOMPI_PUBLIC_KEY": "pub_test_key",
            "WOMPI_INTEGRITY_SECRET": "secret_test",
            "WOMPI_REDIRECT_URL": "https://yourdomain.com/pago-resultado.html",
        },
        clear=False,
    )
    def test_build_checkout_url_rejects_placeholder_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, "WOMPI_REDIRECT_URL cannot use placeholder domains"):
            build_checkout_url("pedido_31_1712345678", 2000000, "cliente@test.com")

    def test_map_wompi_status(self) -> None:
        self.assertEqual(map_wompi_status("APPROVED"), "approved")
        self.assertEqual(map_wompi_status("DECLINED"), "declined")
        self.assertEqual(map_wompi_status("PENDING"), "pending")


if __name__ == "__main__":
    unittest.main()
