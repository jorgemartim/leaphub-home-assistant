# Segurança do Leap Hub Gateway

- Não publique a porta 8099.
- Não compartilhe chaves HMAC, token do Cloudflare ou credenciais Leapmotor.
- Use chaves diferentes para Beta e Produção.
- Em caso de exposição, gere novas chaves no Leap Hub e rotacione o token no Cloudflare.
- O painel e os endpoints públicos não exibem credenciais.
- O binário do Cloudflared é validado por SHA-256 durante a compilação.
- As imagens são compiladas no GitHub Actions e assinadas pelo workflow oficial do Home Assistant Builder.
