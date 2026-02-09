from app.core.pdf_service import PdfService


def test_generate_pdf_falls_back_to_legacy_on_renderer_error(monkeypatch) -> None:
    service = PdfService()

    def raise_render_error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.pdf_service.PdfThemeRenderer.render", raise_render_error)

    pdf = service.generate_pdf("hello", tariff="UNKNOWN", meta={"id": "1"})

    assert pdf.startswith(b"%PDF")
