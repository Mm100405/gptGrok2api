from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, MagicMock, call, patch
from urllib.parse import urlsplit

from services.checkout_protocol import pix_scheme3, pix_scheme3_core


class PixScheme3Test(unittest.TestCase):
    def test_loads_complete_billing_from_approved_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "20260716-000001_0001_pix_confirm.txt").write_text(
                """stage: pix_confirm
request: POST https://api.stripe.com/v1/payment_pages/cs_history/confirm
request_body:
{
  "payment_method_data[billing_details][name]": "Gabriel Almeida",
  "payment_method_data[billing_details][email]": "buyer@example.com",
  "payment_method_data[billing_details][phone]": "+5511999999999",
  "payment_method_data[billing_details][tax_id]": "578.214.331-28",
  "payment_method_data[billing_details][address][country]": "BR",
  "payment_method_data[billing_details][address][line1]": "Avenida Paulista 1000",
  "payment_method_data[billing_details][address][city]": "Sao Paulo",
  "payment_method_data[billing_details][address][state]": "SP",
  "payment_method_data[billing_details][address][postal_code]": "01310100"
}
""",
                encoding="utf-8",
            )
            (root / "20260716-000002_0002_approve.txt").write_text(
                'request_body:\n{"checkout_session_id":"cs_history"}\nresponse:\n{"result":"approved"}\n',
                encoding="utf-8",
            )
            accounts_path = root / "accounts.json"
            accounts_path.write_text(
                '[{"checkout_session_id":"cs_history","checkout_link_status":"ready"}]',
                encoding="utf-8",
            )

            profile = pix_scheme3.load_approved_pix_billing_profile(root, accounts_path)

        self.assertEqual(profile["name"], "Gabriel Almeida")
        self.assertEqual(profile["tax_id"], "57821433128")
        self.assertEqual(profile["state"], "SP")
        self.assertEqual(profile["postal_code"], "01310100")

    def test_br_billing_uses_brazilian_name_pool(self) -> None:
        billing = pix_scheme3_core.opll_billing_for_country("BR")

        self.assertIn(
            billing["name"],
            {"Gabriel Almeida", "Lucas Oliveira", "Mariana Santos", "Beatriz Costa"},
        )
        self.assertEqual(billing["country"], "BR")
        self.assertIn(billing["state"], {"SP", "RJ", "MG", "RS"})
        self.assertTrue(billing["postal_code"])

    def test_compact_proxy_is_normalized_and_rewritten_per_region(self) -> None:
        compact = "us.lajiaohttp.net:2000:test-user-region-BR:test-pass"

        br_proxy = pix_scheme3.proxy_for_region(compact, "BR")
        vn_proxy = pix_scheme3.proxy_for_region(compact, "VN")

        self.assertEqual(
            br_proxy,
            "http://test-user-region-BR:test-pass@us.lajiaohttp.net:2000",
        )
        self.assertEqual(
            vn_proxy,
            "http://test-user-region-VN:test-pass@us.lajiaohttp.net:2000",
        )

        randomized = pix_scheme3_core.randomize_proxy_sid(vn_proxy)
        parsed = urlsplit(randomized)
        self.assertEqual(parsed.username, "test-user-region-VN")
        self.assertEqual(parsed.password, "test-pass")
        self.assertEqual(parsed.hostname, "us.lajiaohttp.net")
        self.assertEqual(parsed.port, 2000)

    def test_smartproxy_area_selector_preserves_lifetime_and_session(self) -> None:
        proxy = (
            "socks5h://account_area-BR_life-120_session-sessionvalue:secret"
            "@proxy.example.test:1000"
        )

        rewritten = pix_scheme3.proxy_for_region(proxy, "VN")
        parsed = urlsplit(rewritten)

        self.assertEqual(
            parsed.username,
            "account_area-VN_life-120_session-sessionvalue",
        )
        self.assertEqual(parsed.password, "secret")
        self.assertEqual(parsed.hostname, "proxy.example.test")
        self.assertEqual(parsed.port, 1000)

    def test_provider_attempt_runs_reference_br_vn_sequence(self) -> None:
        billing = {
            "name": "Joao Silva",
            "email": "buyer@example.com",
            "phone": "+5511999999999",
            "country": "BR",
            "line1": "Avenida Paulista 1000",
            "city": "Sao Paulo",
            "state": "SP",
            "postal_code": "01310-100",
        }
        checkout = {
            "cs_id": "cs_scheme3",
            "processor_entity": "openai_ie",
            "stripe_publishable_key": "pk_scheme3",
            "billing_country": "BR",
            "currency": "BRL",
        }
        bootstrap = {"total_summary": {"due": 100}, "payment_method_types": ["card", "pix"]}
        final_init = {
            "total_summary": {"due": 0},
            "payment_method_types": ["card", "pix"],
            "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_scheme3",
            "config_id": "cfg_scheme3",
            "init_checksum": "checksum",
            "currency": "brl",
        }
        details = {
            "pix_hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_scheme3",
            "pix_qr_code": "",
            "pix_qr_image_url_png": "",
            "pix_qr_image_url_svg": "",
            "pix_expires_at": 0,
            "pix_redirect_url": "",
            "source": "pix_display_qr_code",
        }
        stripe = MagicMock()
        tax_stripe = MagicMock()

        with (
            patch.object(pix_scheme3, "load_approved_pix_billing_profile", return_value={}),
            patch.object(pix_scheme3.core, "opll_billing_for_country", return_value=billing),
            patch.object(pix_scheme3, "generate_valid_cpf", return_value="57821433128"),
            patch.object(pix_scheme3, "create_pix_checkout", return_value=checkout) as create_checkout,
            patch.object(pix_scheme3.core, "opll_stripe_key_for_checkout", return_value="pk_scheme3"),
            patch.object(
                pix_scheme3.core,
                "opll_build_stripe_session",
                side_effect=[stripe, tax_stripe],
            ) as build_stripe,
            patch.object(pix_scheme3, "stripe_init_pix", side_effect=[bootstrap, final_init]) as init,
            patch.object(
                pix_scheme3.core,
                "opll_stripe_amount_info",
                side_effect=[("100", "total_summary.due"), ("0", "total_summary.due")],
            ),
            patch.object(pix_scheme3.core, "opll_update_checkout_promotion") as promotion,
            patch.object(pix_scheme3, "update_pix_checkout_taxes") as taxes,
            patch.object(pix_scheme3, "stripe_update_tax_region") as tax_region,
            patch.object(
                pix_scheme3.core,
                "opll_stripe_context",
                return_value={
                    "stripe_js_id": "stripe-js",
                    "elements_session_id": "elements-session",
                    "elements_session_config_id": "elements-config",
                    "config_id": "cfg_scheme3",
                    "init_checksum": "checksum",
                    "checkout_amount": "0",
                    "currency": "brl",
                    "locale": "pt-BR",
                    "runtime_version": "6f8494a281",
                },
            ),
            patch.object(pix_scheme3, "stripe_create_pix_method", return_value="pm_scheme3") as create_pm,
            patch.object(pix_scheme3.core, "opll_stripe_confirm", return_value={"submission_attempt": {"state": "succeeded"}}) as confirm,
            patch.object(pix_scheme3, "resolve_pix_after_confirm", return_value=details) as resolve,
        ):
            result = pix_scheme3.run_pix_provider_attempt(
                "access-token",
                provider_proxy="http://br.example.test:8000",
                promotion_proxy="http://vn.example.test:8001",
            )

        self.assertEqual(init.call_args_list, [
            call(stripe, "cs_scheme3", "pk_scheme3"),
            call(stripe, "cs_scheme3", "pk_scheme3"),
        ])
        create_checkout.assert_called_once_with(
            "access-token",
            "http://br.example.test:8000",
            with_promo=False,
        )
        self.assertEqual(
            build_stripe.call_args_list,
            [
                call("http://br.example.test:8000"),
                call("http://br.example.test:8000"),
            ],
        )
        promotion.assert_called_once_with("access-token", checkout, "http://vn.example.test:8001")
        taxes.assert_called_once_with("access-token", checkout, billing, "http://br.example.test:8000")
        tax_region.assert_called_once_with(tax_stripe, "cs_scheme3", "pk_scheme3", billing)
        create_pm.assert_called_once()
        confirm.assert_called_once()
        resolve.assert_called_once_with(
            "access-token",
            stripe,
            {"submission_attempt": {"state": "succeeded"}},
            checkout,
            "pk_scheme3",
            ANY,
            "http://br.example.test:8000",
            log_cb=None,
        )
        self.assertEqual(result["long_url"], details["pix_hosted_instructions_url"])
        self.assertEqual(result["stripe_amount"], "0")

    def test_strict_amount_and_pix_guards_match_br_vn_br_chain(self) -> None:
        self.assertEqual(pix_scheme3.enforce_original_price("100", "bootstrap"), 100)
        self.assertEqual(pix_scheme3.enforce_pix_amount("0", "final"), 0)
        self.assertEqual(
            pix_scheme3.ensure_pix_offered({"payment_method_types": ["card", "pix"]}, "init"),
            ["card", "pix"],
        )

        with self.assertRaisesRegex(RuntimeError, "original-price checkout missing"):
            pix_scheme3.enforce_original_price("0", "bootstrap")
        with self.assertRaisesRegex(RuntimeError, "require zero"):
            pix_scheme3.enforce_pix_amount("1", "final")
        with self.assertRaisesRegex(RuntimeError, "pix line unavailable"):
            pix_scheme3.ensure_pix_offered({"payment_method_types": ["card"]}, "init")
        with self.assertRaisesRegex(RuntimeError, "pix line unavailable"):
            pix_scheme3.ensure_pix_offered({}, "init")

    def test_confirm_always_approves_on_original_br_proxy_before_poll(self) -> None:
        stripe = MagicMock()
        checkout = {"cs_id": "cs_scheme3", "billing_country": "BR", "processor_entity": "openai_ie"}
        ctx = {"elements_session_id": "elements-session"}
        details = {
            "pix_hosted_instructions_url": "https://payments.stripe.com/qr/instructions/pix_scheme3",
            "source": "pix_display_qr_code",
        }

        with (
            patch.object(pix_scheme3.core, "opll_chatgpt_approve_with_retry") as approve,
            patch.object(pix_scheme3, "poll_pix_payment_page", return_value=details) as poll,
            patch.object(pix_scheme3, "enrich_with_redirect", side_effect=lambda _stripe, value, _log: value),
        ):
            result = pix_scheme3.resolve_pix_after_confirm(
                "access-token",
                stripe,
                {"submission_attempt": {"state": "succeeded"}},
                checkout,
                "pk_scheme3",
                ctx,
                "http://br.example.test:8000",
            )

        approve.assert_called_once_with(
            "access-token",
            "cs_scheme3",
            checkout,
            "http://br.example.test:8000",
        )
        poll.assert_called_once_with(
            stripe,
            "cs_scheme3",
            "pk_scheme3",
            ctx,
            timeout_seconds=pix_scheme3.PIX_POLL_TIMEOUT_SECONDS,
        )
        self.assertEqual(result, details)

    def test_vn_promotion_failure_does_not_fall_back_to_br(self) -> None:
        checkout = {
            "cs_id": "cs_scheme3",
            "processor_entity": "openai_ie",
            "stripe_publishable_key": "pk_scheme3",
            "billing_country": "BR",
            "currency": "BRL",
        }
        bootstrap = {"total_summary": {"due": 100}, "payment_method_types": ["card", "pix"]}

        with (
            patch.object(pix_scheme3, "load_approved_pix_billing_profile", return_value={}),
            patch.object(pix_scheme3.core, "opll_billing_for_country", return_value={
                "name": "Joao Silva",
                "email": "buyer@example.com",
                "phone": "+5511999999999",
                "country": "BR",
                "line1": "Avenida Paulista 1000",
                "city": "Sao Paulo",
                "state": "SP",
                "postal_code": "01310-100",
            }),
            patch.object(pix_scheme3, "generate_valid_cpf", return_value="57821433128"),
            patch.object(pix_scheme3, "create_pix_checkout", return_value=checkout),
            patch.object(pix_scheme3.core, "opll_stripe_key_for_checkout", return_value="pk_scheme3"),
            patch.object(pix_scheme3.core, "opll_build_stripe_session", return_value=MagicMock()),
            patch.object(pix_scheme3, "stripe_init_pix", return_value=bootstrap),
            patch.object(pix_scheme3.core, "opll_stripe_amount_info", return_value=("100", "total_summary.due")),
            patch.object(
                pix_scheme3.core,
                "opll_update_checkout_promotion",
                side_effect=RuntimeError("VN promotion rejected"),
            ) as promotion,
            patch.object(pix_scheme3, "update_pix_checkout_taxes") as taxes,
        ):
            with self.assertRaisesRegex(RuntimeError, "VN promotion rejected"):
                pix_scheme3.run_pix_provider_attempt(
                    "access-token",
                    provider_proxy="http://br.example.test:8000",
                    promotion_proxy="http://vn.example.test:8001",
                )

        promotion.assert_called_once_with("access-token", checkout, "http://vn.example.test:8001")
        taxes.assert_not_called()

    def test_rejects_same_proxy_for_br_provider_and_vn_promotion(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "distinct VN promotion proxy"):
            pix_scheme3.run_pix_provider_attempt(
                "access-token",
                provider_proxy="http://shared.example.test:8000",
                promotion_proxy="http://shared.example.test:8000",
            )


if __name__ == "__main__":
    unittest.main()
