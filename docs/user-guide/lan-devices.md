# Computadores na rede local

O OpenJarvis pode consultar computadores cadastrados manualmente na sua rede
local por SSH. O recurso não procura dispositivos no Wi-Fi: cada máquina precisa
ser informada pelo usuário, ter um servidor SSH ativado e aceitar uma chave SSH
autorizada.

## Limites de segurança

- O Jarvis aceita IPs privados/locais ou nomes simples de LAN (`.local`, `.lan`
  ou `.home.arpa`); endereços públicos e loopback são rejeitados.
- A verificação de chave do host SSH é obrigatória. Não desative
  `StrictHostKeyChecking`; confira a impressão digital do dispositivo antes de
  confiar nele.
- Cada chamada remota pede confirmação no terminal. Recusar cancela a chamada.
- O assistente só pode executar as ações fixas `system_info`, `disk_usage` e
  `process_summary`. Não existe parâmetro de comando shell livre; estas ações
  apenas consultam informações e não alteram os dispositivos.
- A configuração fica em `~/.openjarvis/devices.toml`, com permissões restritas.
  Ela guarda endereços, nomes de usuário e, opcionalmente, o caminho da chave
  privada — nunca o conteúdo da chave.

## Preparar cada computador remoto

Instale/ative o servidor OpenSSH no dispositivo e permita conexões de entrada
na porta SSH somente na rede privada. Não encaminhe essa porta para a Internet.

- **Windows:** habilite o recurso opcional **OpenSSH Server** e inicie o serviço
  `sshd` no dispositivo.
- **macOS:** em **Ajustes do Sistema → Geral → Compartilhamento**, habilite
  **Início de Sessão Remoto**.
- **Linux:** instale e inicie o servidor `openssh-server` usando o gerenciador
  de pacotes da distribuição.

No computador que executa o Jarvis, crie uma chave dedicada (ou escolha uma
chave já existente):

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\jarvis_lan" -C "openjarvis-lan"
```

Instale **a chave pública** `jarvis_lan.pub` no arquivo `authorized_keys` do
usuário SSH no dispositivo remoto. Nunca copie a chave privada
`jarvis_lan` para outro computador. Antes de cadastrar o dispositivo, conecte-se
manualmente com `ssh -i "$env:USERPROFILE\.ssh\jarvis_lan" usuario@192.168.1.20`,
verifique a impressão digital SSH por um canal confiável e aceite a chave do
host somente se ela corresponder. Encerre a sessão com `exit`.

## Cadastrar e usar

Substitua o endereço e o usuário pelos dados da sua máquina:

```powershell
uv run jarvis devices add sala --host 192.168.1.20 --user usuario --os windows --identity-file "$env:USERPROFILE\.ssh\jarvis_lan"
uv run jarvis devices list
```

O sistema informado (`windows`, `linux` ou `macos`) escolhe somente as consultas
fixas correspondentes. Para remover o cadastro local:

```powershell
uv run jarvis devices remove sala
```

Converse por voz com ferramentas habilitadas:

```powershell
uv run jarvis chat --agent orchestrator --tools lan_computer --voice
```

Exemplos: “consulte as informações de sistema de sala”, “mostre o espaço em
disco de sala” ou “resuma os processos de sala”. Antes da conexão, o terminal
mostra a ferramenta e os parâmetros e pede `y`/`yes`; qualquer outra resposta
nega a ação. A confirmação é feita no teclado, mesmo no modo de voz.

O modo `--voice-live` continua sendo uma conversa direta sem ferramentas. Ações
que alteram arquivos, instalam programas, iniciam serviços ou executam outros
comandos não estão habilitadas. Para adicionar uma capacidade, especifique
primeiro a ação exata desejada para que possa ser avaliada e incluída de forma
explícita na lista permitida.
