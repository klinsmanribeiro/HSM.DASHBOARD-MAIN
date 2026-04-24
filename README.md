📊 HSM Dashboard — Relatório de Disparos
Este projeto foi desenvolvido para resolver a necessidade de acompanhamento em tempo real de envios de mensagens (HSM) via WhatsApp. Ele substitui a extração manual de arquivos CSV por um painel dinâmico, facilitando a tomada de decisão e a monitoria de falhas técnicas.

🚀 Tecnologias Utilizadas
Python 3.12

Flask/Dash (para a interface e servidor web)

Pandas (para tratamento e manipulação de dados brutos)

API Integration (Consumo de dados de mensajeria)

HTML/CSS (Customização de interface e badges de status)

💡 Solução de Negócio
Antes desta ferramenta, a equipe realizava extrações manuais a cada 15 minutos. O HSM Dashboard automatiza esse processo, oferecendo:

Visualização Imediata: Dados tratados em vez de logs brutos.

Redução de Erros: Identificação rápida de mensagens pendentes ou com falha.

Autonomia: Filtros por data e template que permitem análises granulares sem necessidade de novas consultas ao banco.

🛠️ Funcionalidades
[x] Filtros Inteligentes: Seleção por período e população automática de templates.

[x] Auto-Refresh: Atualização automática a cada 20 minutos com contador regressivo.

[x] Cards de Resumo: Visualização rápida de Total, Sucesso, Erros, Entregues e Lidos.

[x] Badges de Status: Identificação visual colorida para diferentes estados da mensagem.

⚙️ Como Rodar o Projeto Localmente
Clonar o repositório:

Bash
git clone https://github.com/klinsmanribeiro/hsm.relatorio.git
Instalar dependências:

Bash
pip install -r requirements.txt
Configurar Variáveis de Ambiente:
Certifique-se de configurar as credenciais de API e banco de dados no arquivo .env (ou variáveis de sistema).

Iniciar o servidor:

Bash
python app.py
Acessar no navegador:
http://localhost:5050
