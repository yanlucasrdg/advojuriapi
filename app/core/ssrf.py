"""
Validação anti-SSRF de URLs de webhook fornecidas pelo cliente.

O worker de monitoramento faz um POST para a `webhook_url` cadastrada pelo
cliente. Sem validação, um cliente malicioso pode apontar essa URL para um
endereço interno (loopback, rede privada, link-local — ex: 169.254.169.254,
o endpoint de metadados de cloud) e usar nosso worker como proxy para atingir
serviços que só são acessíveis de dentro da rede (SSRF).

Estratégia: resolver o hostname e rejeitar se QUALQUER IP resolvido cair numa
faixa não roteável publicamente. A verificação é feita tanto na criação do
monitoramento quanto imediatamente antes de cada envio no worker (defesa
contra DNS rebinding — um host que resolve para IP público na criação e para
IP interno na hora do envio).
"""

import ipaddress
import socket
from urllib.parse import urlparse


class WebhookUrlInseguraError(ValueError):
    pass


def _ip_e_seguro(ip: str) -> bool:
    endereco = ipaddress.ip_address(ip)
    return not (
        endereco.is_private
        or endereco.is_loopback
        or endereco.is_link_local
        or endereco.is_multicast
        or endereco.is_reserved
        or endereco.is_unspecified
    )


def validar_url_webhook(url: str) -> None:
    """
    Levanta WebhookUrlInseguraError se a URL não for um destino HTTPS público.
    Retorna None (silencioso) se estiver ok.
    """
    try:
        parsed = urlparse(url)
        porta = parsed.port or 443
    except ValueError as exc:
        raise WebhookUrlInseguraError(f"webhook_url malformada: {exc}") from exc

    if parsed.scheme != "https":
        raise WebhookUrlInseguraError(
            "webhook_url deve ser HTTPS (o payload carrega dados de processo judicial)"
        )

    hostname = parsed.hostname
    if not hostname:
        raise WebhookUrlInseguraError("webhook_url sem hostname válido")

    try:
        infos = socket.getaddrinfo(hostname, porta, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookUrlInseguraError(f"Não foi possível resolver o host de webhook_url: {exc}") from exc

    ips = {info[4][0] for info in infos}
    if not ips:
        raise WebhookUrlInseguraError("webhook_url não resolveu para nenhum IP")

    for ip in ips:
        if not _ip_e_seguro(ip):
            raise WebhookUrlInseguraError(
                "webhook_url aponta para um endereço interno/reservado (SSRF bloqueado)"
            )


def url_webhook_segura(url: str) -> bool:
    try:
        validar_url_webhook(url)
        return True
    except WebhookUrlInseguraError:
        return False
