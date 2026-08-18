"""Gravação local de sessão e clipagem (estilo Medal/OBS).

Nesta fase inicial oferecemos a estrutura e a gravação básica em arquivo.
Clipes dos últimos minutos e integração completa com a sessão virão em seguida.
"""

from midia.gravacao.gravador import GravadorSessao, EstadoGravacao

__all__ = ["GravadorSessao", "EstadoGravacao"]
