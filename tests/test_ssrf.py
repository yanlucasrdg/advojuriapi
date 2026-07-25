"""
Testes da validação anti-SSRF de webhook_url. Não sobe app nem rede real:
o resolvedor de DNS é substituído por um fake para exercitar as faixas de IP
sem depender de resolução externa.
"""

import pytest

import app.core.ssrf as ssrf
from app.core.ssrf import WebhookUrlInseguraError, url_webhook_segura, validar_url_webhook


def _fake_getaddrinfo(ip: str):
    def _inner(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (ip, port or 443))]

    return _inner


def test_rejeita_scheme_nao_https():
    with pytest.raises(WebhookUrlInseguraError):
        validar_url_webhook("http://exemplo.com/webhook")


def test_rejeita_sem_hostname():
    with pytest.raises(WebhookUrlInseguraError):
        validar_url_webhook("https:///webhook")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # privado
        "192.168.1.10",    # privado
        "172.16.0.1",      # privado
        "169.254.169.254",  # link-local / metadados de cloud
        "0.0.0.0",         # unspecified
        "::1",             # loopback IPv6
    ],
)
def test_rejeita_ips_internos(monkeypatch, ip):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo(ip))
    assert url_webhook_segura("https://interno.exemplo.com/webhook") is False


def test_aceita_ip_publico(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    validar_url_webhook("https://exemplo.com/webhook")
    assert url_webhook_segura("https://exemplo.com/webhook") is True
