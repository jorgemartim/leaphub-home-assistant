# Leap Hub Gateway 1.12.18.1 — recuperação

- mesma base funcional da 1.12.18;
- sem campo `image`, permitindo compilação local quando a tag GHCR não estiver disponível;
- build local mais rápido porque cloudflared só é baixado quando o túnel embutido estiver ativado;
- use apenas como recuperação. Para atualizações normais, prefira a 1.12.18 pré-compilada.
